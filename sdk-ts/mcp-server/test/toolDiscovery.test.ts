import { test } from 'node:test';
import assert from 'node:assert/strict';

import { catalogToMcpTools } from '../src/toolDiscovery.js';

test('preserves name, description, and input schema', () => {
  const tools = catalogToMcpTools([
    {
      name: 'get_balance',
      service: 'billing',
      description: 'Get wallet balance.',
      input_schema: {
        type: 'object',
        properties: { agent_id: { type: 'string' } },
        required: ['agent_id'],
      },
      pricing: { per_call: 0 },
      tier_required: 'free',
    },
  ]);
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, 'get_balance');
  assert.match(tools[0].description, /balance/i);
  assert.match(tools[0].description, /cost=0/);
  assert.match(tools[0].description, /tier=free/);
});

test('folds pricing and tier into description for non-free tools', () => {
  const tools = catalogToMcpTools([
    {
      name: 'create_intent',
      service: 'payments',
      description: 'Create a payment intent.',
      input_schema: { type: 'object', properties: {}, required: [] },
      pricing: { per_call: 0.5 },
      tier_required: 'pro',
    },
  ]);
  assert.match(tools[0].description, /0\.5/);
  assert.match(tools[0].description, /pro/);
});

test('skips entries without a name', () => {
  const tools = catalogToMcpTools([
    { description: 'nameless' } as any,
    { name: 'valid', input_schema: { type: 'object' } },
  ]);
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, 'valid');
});
