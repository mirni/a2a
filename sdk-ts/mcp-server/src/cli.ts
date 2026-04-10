#!/usr/bin/env node
/**
 * CLI entry point for @greenhelix/mcp-server.
 *
 * Usage:
 *   a2a-mcp-server                    # stdio transport (default)
 *   A2A_API_KEY=... a2a-mcp-server
 *
 * Env vars:
 *   A2A_API_KEY   required
 *   A2A_BASE_URL  optional (default: https://api.greenhelix.net)
 */

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { GatewayClient } from './gatewayClient.js';
import { buildServer } from './server.js';

async function main(): Promise<void> {
  const apiKey = process.env.A2A_API_KEY;
  if (!apiKey) {
    console.error('ERROR: A2A_API_KEY environment variable is required.');
    console.error('Get a free API key at https://greenhelix.net (500 credits, 100 req/hr).');
    process.exit(2);
  }

  const baseUrl = process.env.A2A_BASE_URL ?? 'https://api.greenhelix.net';
  const client = new GatewayClient({ baseUrl, apiKey });
  const server = buildServer(client);

  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Keep the process alive; stdio transport manages its own lifecycle.
  process.stdin.resume();
}

main().catch((err) => {
  console.error('a2a-mcp-server fatal error:', err);
  process.exit(1);
});
