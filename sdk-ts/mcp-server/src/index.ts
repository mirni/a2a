/**
 * @greenhelix/mcp-server — MCP server for the A2A Commerce Gateway.
 *
 * Exports the reusable primitives so downstream consumers can embed the
 * gateway client or tool-discovery logic in their own MCP servers.
 */

export {
  GatewayClient,
  GatewayError,
  GatewayAuthError,
  GatewayRateLimitError,
} from './gatewayClient.js';
export type { GatewayClientOptions, CatalogTool } from './gatewayClient.js';
export { catalogToMcpTools } from './toolDiscovery.js';
export type { McpTool } from './toolDiscovery.js';
export { buildServer } from './server.js';
