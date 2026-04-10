import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  GatewayClient,
  GatewayAuthError,
  GatewayError,
  GatewayRateLimitError,
} from '../src/gatewayClient.js';

function mockFetch(handler: (req: Request) => Response | Promise<Response>) {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input.toString(), init);
    return handler(request);
  };
}

test('listTools GETs /v1/pricing with Bearer auth', async () => {
  let capturedUrl = '';
  let capturedAuth: string | null = null;
  const client = new GatewayClient({
    baseUrl: 'https://api.greenhelix.net',
    apiKey: 'a2a_test_abc',
    fetch: mockFetch((req) => {
      capturedUrl = req.url;
      capturedAuth = req.headers.get('authorization');
      return new Response(
        JSON.stringify({
          tools: [
            {
              name: 'get_balance',
              service: 'billing',
              description: 'Get balance',
              input_schema: { type: 'object', properties: {}, required: [] },
              pricing: { per_call: 0 },
              tier_required: 'free',
            },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }),
  });
  const tools = await client.listTools();
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, 'get_balance');
  assert.ok(capturedUrl.endsWith('/v1/pricing'));
  assert.equal(capturedAuth, 'Bearer a2a_test_abc');
});

test('invokeTool POSTs single call to /v1/batch and unwraps result', async () => {
  let capturedUrl = '';
  let capturedBody = '';
  const client = new GatewayClient({
    baseUrl: 'https://api.greenhelix.net',
    apiKey: 'a2a_test_abc',
    fetch: mockFetch(async (req) => {
      capturedUrl = req.url;
      capturedBody = await req.text();
      return new Response(
        JSON.stringify({ results: [{ success: true, result: { balance: 500 } }] }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    }),
  });
  const result = (await client.invokeTool('get_balance', { agent_id: 'alice' })) as {
    balance: number;
  };
  assert.deepEqual(result, { balance: 500 });
  assert.ok(capturedUrl.endsWith('/v1/batch'));
  assert.ok(capturedBody.includes('get_balance'));
  assert.ok(capturedBody.includes('alice'));
});

test('invokeTool raises GatewayError when result has success=false', async () => {
  const client = new GatewayClient({
    baseUrl: 'https://api.greenhelix.net',
    apiKey: 'a2a_test_abc',
    fetch: mockFetch(
      () =>
        new Response(
          JSON.stringify({
            results: [
              {
                success: false,
                error: { code: 'unknown_tool', message: 'Unknown tool: foo' },
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    ),
  });
  await assert.rejects(() => client.invokeTool('foo'), (err: unknown) => {
    assert.ok(err instanceof GatewayError);
    assert.match((err as Error).message, /Unknown tool/);
    return true;
  });
});

test('401 raises GatewayAuthError', async () => {
  const client = new GatewayClient({
    baseUrl: 'https://api.greenhelix.net',
    apiKey: 'bad',
    fetch: mockFetch(
      () =>
        new Response(JSON.stringify({ error: { message: 'Missing API key' } }), {
          status: 401,
          headers: { 'content-type': 'application/json' },
        }),
    ),
  });
  await assert.rejects(() => client.listTools(), (err: unknown) => {
    assert.ok(err instanceof GatewayAuthError);
    return true;
  });
});

test('429 raises GatewayRateLimitError', async () => {
  const client = new GatewayClient({
    baseUrl: 'https://api.greenhelix.net',
    apiKey: 'a2a_test_abc',
    fetch: mockFetch(
      () =>
        new Response(JSON.stringify({ error: { message: 'Rate limit exceeded' } }), {
          status: 429,
          headers: { 'content-type': 'application/json' },
        }),
    ),
  });
  await assert.rejects(() => client.invokeTool('get_balance'), (err: unknown) => {
    assert.ok(err instanceof GatewayRateLimitError);
    return true;
  });
});
