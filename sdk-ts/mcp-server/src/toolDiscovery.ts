/**
 * Convert /v1/pricing catalog entries into MCP Tool descriptors.
 *
 * Pricing + tier metadata is folded into each tool's description so
 * that planner LLMs can pick the cheapest / lowest-tier alternative.
 */

import type { CatalogTool } from './gatewayClient.js';

export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
}

export function catalogToMcpTools(catalog: CatalogTool[]): McpTool[] {
  const tools: McpTool[] = [];
  for (const entry of catalog) {
    if (!entry?.name) continue;
    const description = buildDescription(entry);
    const inputSchema = (entry.input_schema as Record<string, unknown>) ?? {
      type: 'object',
      properties: {},
    };
    const tool: McpTool = {
      name: entry.name,
      description,
      inputSchema,
    };
    if (entry.output_schema && Object.keys(entry.output_schema).length > 0) {
      tool.outputSchema = entry.output_schema as Record<string, unknown>;
    }
    tools.push(tool);
  }
  return tools;
}

function buildDescription(entry: CatalogTool): string {
  const base = (entry.description ?? '').trim();
  const extras: string[] = [];
  if (entry.service) extras.push(`service=${entry.service}`);
  const perCall = entry.pricing?.per_call;
  if (typeof perCall === 'number') {
    if (perCall === 0) {
      extras.push('cost=0 credits');
    } else {
      extras.push(`cost=${perCall} credits/call`);
    }
  }
  extras.push(`tier=${entry.tier_required ?? 'free'}`);
  const suffix = ` [${extras.join(', ')}]`;
  return base ? base + suffix : `A2A gateway tool${suffix}`;
}
