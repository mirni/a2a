/**
 * Tests for A2AClient construction and method behavior.
 *
 * Uses a mock HTTP server (node:http) to verify real fetch calls
 * from the client, avoiding mock-coupling to internal implementation.
 */

import { describe, it, before, after } from "node:test";
import * as assert from "node:assert/strict";
import * as http from "node:http";

import { A2AClient } from "../client";
import {
  AuthenticationError,
  ToolNotFoundError,
  RateLimitError,
} from "../errors";

// ---------------------------------------------------------------------------
// Test HTTP server
// ---------------------------------------------------------------------------

let server: http.Server;
let baseUrl: string;

/** Route handlers keyed by "METHOD /path". */
const routes: Record<string, (req: http.IncomingMessage, body: string) => [number, any]> = {};

function route(method: string, path: string, handler: (req: http.IncomingMessage, body: string) => [number, any]) {
  routes[`${method} ${path}`] = handler;
}

before(async () => {
  server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk: Buffer) => { body += chunk.toString(); });
    req.on("end", () => {
      const key = `${req.method} ${req.url}`;
      const handler = routes[key];
      if (handler) {
        const [status, data] = handler(req, body);
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
      } else {
        res.writeHead(404);
        res.end(JSON.stringify({ error: { code: "not_found", message: `No handler for ${key}` } }));
      }
    });
  });

  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address() as any;
      baseUrl = `http://127.0.0.1:${addr.port}`;
      resolve();
    });
  });
});

after(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

// ---------------------------------------------------------------------------
// Client construction
// ---------------------------------------------------------------------------

describe("A2AClient construction", () => {
  it("defaults to localhost:8000", () => {
    const client = new A2AClient();
    // Can't directly inspect private fields, but health() would go to localhost
    assert.ok(client);
  });

  it("strips trailing slashes from baseUrl", async () => {
    route("GET", "/v1/health", () => [200, { status: "ok", version: "0.1.0", tools: 10 }]);
    const client = new A2AClient({ baseUrl: baseUrl + "///", apiKey: "test" });
    const health = await client.health();
    assert.equal(health.status, "ok");
  });
});

// ---------------------------------------------------------------------------
// health()
// ---------------------------------------------------------------------------

describe("health()", () => {
  it("returns health response", async () => {
    route("GET", "/v1/health", () => [200, { status: "ok", version: "0.1.0", tools: 85 }]);
    const client = new A2AClient({ baseUrl });
    const health = await client.health();
    assert.equal(health.status, "ok");
    assert.equal(health.version, "0.1.0");
    assert.equal(health.tools, 85);
  });
});

// ---------------------------------------------------------------------------
// pricing()
// ---------------------------------------------------------------------------

describe("pricing()", () => {
  it("returns tool list", async () => {
    route("GET", "/v1/pricing", () => [200, {
      tools: [
        { name: "get_balance", service: "billing", description: "Get balance", pricing: { per_call: 0 }, tier_required: "free" },
      ],
    }]);
    const client = new A2AClient({ baseUrl });
    const tools = await client.pricing();
    assert.equal(tools.length, 1);
    assert.equal(tools[0].name, "get_balance");
  });

  it("caches results on second call", async () => {
    let callCount = 0;
    route("GET", "/v1/pricing", () => {
      callCount++;
      return [200, { tools: [{ name: "cached", service: "test", description: "", pricing: {}, tier_required: "free" }] }];
    });
    const client = new A2AClient({ baseUrl, pricingCacheTtl: 60_000 });
    await client.pricing();
    await client.pricing();
    assert.equal(callCount, 1); // Second call uses cache
  });

  it("invalidatePricingCache forces refetch", async () => {
    let callCount = 0;
    route("GET", "/v1/pricing", () => {
      callCount++;
      return [200, { tools: [] }];
    });
    const client = new A2AClient({ baseUrl, pricingCacheTtl: 60_000 });
    await client.pricing();
    client.invalidatePricingCache();
    await client.pricing();
    assert.equal(callCount, 2);
  });
});

// ---------------------------------------------------------------------------
// execute()
// ---------------------------------------------------------------------------

describe("execute()", () => {
  it("sends tool and params, returns result", async () => {
    route("POST", "/v1/execute", (_req, body) => {
      const parsed = JSON.parse(body);
      assert.equal(parsed.tool, "get_balance");
      assert.equal(parsed.params.agent_id, "test-agent");
      return [200, { success: true, result: { balance: 42.0 }, charged: 0 }];
    });
    const client = new A2AClient({ baseUrl, apiKey: "test_key" });
    const resp = await client.execute("get_balance", { agent_id: "test-agent" });
    assert.equal(resp.success, true);
    assert.equal(resp.result.balance, 42.0);
    assert.equal(resp.charged, 0);
  });

  it("sends Authorization header", async () => {
    route("POST", "/v1/execute", (req) => {
      assert.equal(req.headers.authorization, "Bearer my_secret_key");
      return [200, { success: true, result: {}, charged: 0 }];
    });
    const client = new A2AClient({ baseUrl, apiKey: "my_secret_key" });
    await client.execute("any_tool", {});
  });

  it("throws AuthenticationError on 401", async () => {
    route("POST", "/v1/execute", () => [401, { error: { code: "invalid_key", message: "Bad key" } }]);
    const client = new A2AClient({ baseUrl, apiKey: "bad" });
    await assert.rejects(
      () => client.execute("get_balance", {}),
      (err: any) => err instanceof AuthenticationError,
    );
  });

  it("throws ToolNotFoundError on 400", async () => {
    route("POST", "/v1/execute", () => [400, { error: { code: "unknown_tool", message: "Unknown" } }]);
    const client = new A2AClient({ baseUrl, apiKey: "key" });
    await assert.rejects(
      () => client.execute("nonexistent", {}),
      (err: any) => err instanceof ToolNotFoundError,
    );
  });
});

// ---------------------------------------------------------------------------
// Convenience methods
// ---------------------------------------------------------------------------

describe("Convenience methods", () => {
  it("getBalance extracts balance from result", async () => {
    route("POST", "/v1/execute", () => [200, { success: true, result: { balance: 99.5 }, charged: 0 }]);
    const client = new A2AClient({ baseUrl, apiKey: "key" });
    const balance = await client.getBalance("agent-1");
    assert.equal(balance, 99.5);
  });

  it("deposit extracts new_balance from result", async () => {
    route("POST", "/v1/execute", () => [200, { success: true, result: { new_balance: 199.5 }, charged: 0 }]);
    const client = new A2AClient({ baseUrl, apiKey: "key" });
    const newBalance = await client.deposit("agent-1", 100);
    assert.equal(newBalance, 199.5);
  });

  it("searchServices extracts services array", async () => {
    route("POST", "/v1/execute", () => [200, {
      success: true,
      result: { services: [{ name: "svc1" }, { name: "svc2" }] },
      charged: 0,
    }]);
    const client = new A2AClient({ baseUrl, apiKey: "key" });
    const services = await client.searchServices({ query: "test" });
    assert.equal(services.length, 2);
  });
});

// ---------------------------------------------------------------------------
// Retry behavior
// ---------------------------------------------------------------------------

describe("Retry behavior", () => {
  it("retries on 429 then succeeds", async () => {
    let attempt = 0;
    route("POST", "/v1/execute", () => {
      attempt++;
      if (attempt === 1) {
        return [429, { error: { code: "rate_limit", message: "slow down" } }];
      }
      return [200, { success: true, result: { ok: true }, charged: 0 }];
    });
    const client = new A2AClient({ baseUrl, apiKey: "key", retryBaseDelay: 50 });
    const resp = await client.execute("test", {});
    assert.equal(resp.success, true);
    assert.equal(attempt, 2);
  });

  it("retries on 500 then succeeds", async () => {
    let attempt = 0;
    route("POST", "/v1/execute", () => {
      attempt++;
      if (attempt === 1) {
        return [500, { error: { code: "internal", message: "oops" } }];
      }
      return [200, { success: true, result: {}, charged: 0 }];
    });
    const client = new A2AClient({ baseUrl, apiKey: "key", retryBaseDelay: 50 });
    const resp = await client.execute("test", {});
    assert.equal(resp.success, true);
    assert.equal(attempt, 2);
  });

  it("throws RateLimitError after max retries exhausted", async () => {
    route("POST", "/v1/execute", () => [429, { error: { code: "rate_limit", message: "nope" } }]);
    const client = new A2AClient({ baseUrl, apiKey: "key", maxRetries: 1, retryBaseDelay: 50 });
    await assert.rejects(
      () => client.execute("test", {}),
      (err: any) => err instanceof RateLimitError,
    );
  });

  it("does not retry on 400", async () => {
    let attempt = 0;
    route("POST", "/v1/execute", () => {
      attempt++;
      return [400, { error: { code: "bad_request", message: "bad" } }];
    });
    const client = new A2AClient({ baseUrl, apiKey: "key", retryBaseDelay: 50 });
    await assert.rejects(() => client.execute("test", {}));
    assert.equal(attempt, 1); // No retry
  });
});
