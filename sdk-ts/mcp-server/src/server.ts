/**
 * Build a configured MCP Server instance wired to the gateway client.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

import { GatewayClient, GatewayError } from './gatewayClient.js';
import { catalogToMcpTools, type McpTool } from './toolDiscovery.js';

const CATALOG_TTL_MS = 10_000;

export function buildServer(client: GatewayClient): Server {
  const server = new Server(
    { name: 'a2a-mcp-server', version: '0.1.0' },
    { capabilities: { tools: {} } },
  );

  let cache: { tools: McpTool[]; expires: number } = { tools: [], expires: 0 };

  server.setRequestHandler(ListToolsRequestSchema, async () => {
    const now = Date.now();
    if (cache.tools.length && cache.expires > now) {
      return { tools: cache.tools };
    }
    const catalog = await client.listTools();
    const tools = catalogToMcpTools(catalog);
    cache = { tools, expires: now + CATALOG_TTL_MS };
    return { tools };
  });

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
      const result = await client.invokeTool(name, args ?? {});
      return {
        content: [{ type: 'text', text: JSON.stringify(result) }],
      };
    } catch (err) {
      const message = err instanceof GatewayError ? err.message : String(err);
      return {
        content: [{ type: 'text', text: JSON.stringify({ error: message }) }],
        isError: true,
      };
    }
  });

  return server;
}
