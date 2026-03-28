/**
 * Tests for error classes and raiseForStatus.
 */

import { describe, it } from "node:test";
import * as assert from "node:assert/strict";

import {
  A2AError,
  AuthenticationError,
  InsufficientBalanceError,
  InsufficientTierError,
  ToolNotFoundError,
  RateLimitError,
  ServerError,
  RETRYABLE_STATUS_CODES,
  raiseForStatus,
} from "../errors";

describe("Error classes", () => {
  it("A2AError stores message, code, status", () => {
    const err = new A2AError("test msg", "test_code", 418);
    assert.equal(err.message, "test msg");
    assert.equal(err.code, "test_code");
    assert.equal(err.status, 418);
    assert.equal(err.name, "A2AError");
    assert.ok(err instanceof Error);
  });

  it("AuthenticationError has status 401", () => {
    const err = new AuthenticationError("bad key");
    assert.equal(err.status, 401);
    assert.equal(err.name, "AuthenticationError");
    assert.ok(err instanceof A2AError);
  });

  it("InsufficientBalanceError has status 402", () => {
    const err = new InsufficientBalanceError("low funds");
    assert.equal(err.status, 402);
    assert.ok(err instanceof A2AError);
  });

  it("InsufficientTierError has status 403", () => {
    const err = new InsufficientTierError("need pro");
    assert.equal(err.status, 403);
    assert.ok(err instanceof A2AError);
  });

  it("ToolNotFoundError has status 404", () => {
    const err = new ToolNotFoundError("no such tool");
    assert.equal(err.status, 404);
    assert.ok(err instanceof A2AError);
  });

  it("RateLimitError has status 429", () => {
    const err = new RateLimitError("slow down");
    assert.equal(err.status, 429);
    assert.ok(err instanceof A2AError);
  });

  it("ServerError defaults to status 500", () => {
    const err = new ServerError("boom");
    assert.equal(err.status, 500);
    assert.ok(err instanceof A2AError);
  });

  it("ServerError accepts custom status", () => {
    const err = new ServerError("gateway", "bad_gateway", 502);
    assert.equal(err.status, 502);
    assert.equal(err.code, "bad_gateway");
  });
});

describe("RETRYABLE_STATUS_CODES", () => {
  it("contains 429, 500, 502, 503, 504", () => {
    for (const code of [429, 500, 502, 503, 504]) {
      assert.ok(RETRYABLE_STATUS_CODES.has(code), `missing ${code}`);
    }
  });

  it("does not contain 400, 401, 403, 404", () => {
    for (const code of [400, 401, 403, 404]) {
      assert.ok(!RETRYABLE_STATUS_CODES.has(code), `should not have ${code}`);
    }
  });
});

describe("raiseForStatus", () => {
  it("throws AuthenticationError for 401", () => {
    assert.throws(
      () => raiseForStatus(401, { error: { message: "bad", code: "invalid_key" } }),
      (err: any) => err instanceof AuthenticationError && err.code === "invalid_key",
    );
  });

  it("throws InsufficientBalanceError for 402", () => {
    assert.throws(
      () => raiseForStatus(402, { error: { message: "low", code: "insufficient_balance" } }),
      (err: any) => err instanceof InsufficientBalanceError,
    );
  });

  it("throws InsufficientTierError for 403", () => {
    assert.throws(
      () => raiseForStatus(403, { error: { message: "need pro", code: "insufficient_tier" } }),
      (err: any) => err instanceof InsufficientTierError,
    );
  });

  it("throws ToolNotFoundError for 400", () => {
    assert.throws(
      () => raiseForStatus(400, { error: { message: "unknown", code: "unknown_tool" } }),
      (err: any) => err instanceof ToolNotFoundError,
    );
  });

  it("throws ToolNotFoundError for 404", () => {
    assert.throws(
      () => raiseForStatus(404, { error: { message: "not found", code: "not_found" } }),
      (err: any) => err instanceof ToolNotFoundError,
    );
  });

  it("throws RateLimitError for 429", () => {
    assert.throws(
      () => raiseForStatus(429, { error: { message: "too fast", code: "rate_limit" } }),
      (err: any) => err instanceof RateLimitError,
    );
  });

  it("throws ServerError for unknown status", () => {
    assert.throws(
      () => raiseForStatus(503, { error: { message: "down", code: "unavailable" } }),
      (err: any) => err instanceof ServerError,
    );
  });

  it("handles missing error fields gracefully", () => {
    assert.throws(
      () => raiseForStatus(500, {}),
      (err: any) => err instanceof ServerError && err.message === "Unknown error",
    );
  });
});
