/**
 * Thin async HTTP client for the A2A Commerce Gateway.
 *
 * Only exposes what the MCP server needs:
 *   - listTools()              → GET /v1/pricing
 *   - invokeTool(name, params) → POST /v1/batch (single call)
 *
 * /v1/batch is used instead of the legacy /v1/execute endpoint because the
 * latter is restricted to connector tools in gateway v1.2+.
 */

export class GatewayError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = 'GatewayError';
    this.code = code;
  }
}

export class GatewayAuthError extends GatewayError {
  constructor(message: string) {
    super('unauthorized', message);
    this.name = 'GatewayAuthError';
  }
}

export class GatewayRateLimitError extends GatewayError {
  constructor(message: string) {
    super('rate_limit_exceeded', message);
    this.name = 'GatewayRateLimitError';
  }
}

export interface GatewayClientOptions {
  baseUrl: string;
  apiKey: string;
  userAgent?: string;
  fetch?: typeof fetch;
}

export interface CatalogTool {
  name: string;
  service?: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  pricing?: { per_call?: number };
  tier_required?: string;
  [key: string]: unknown;
}

export class GatewayClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly userAgent: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey;
    this.userAgent = options.userAgent ?? '@greenhelix/mcp-server/0.1.0';
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    if (!this.fetchImpl) {
      throw new Error('No global fetch available. Node >=18 is required, or inject options.fetch.');
    }
  }

  async listTools(): Promise<CatalogTool[]> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/pricing`, {
      method: 'GET',
      headers: this.headers(),
    });
    await this.ensureOk(resp);
    const body = (await resp.json()) as { tools?: CatalogTool[] };
    if (!body || !Array.isArray(body.tools)) {
      throw new GatewayError('bad_response', `Unexpected /v1/pricing payload: ${JSON.stringify(body)}`);
    }
    return body.tools;
  }

  async invokeTool(name: string, params: Record<string, unknown> = {}): Promise<unknown> {
    const resp = await this.fetchImpl(`${this.baseUrl}/v1/batch`, {
      method: 'POST',
      headers: {
        ...this.headers(),
        'content-type': 'application/json',
      },
      body: JSON.stringify({ calls: [{ tool: name, params }] }),
    });
    await this.ensureOk(resp);
    const body = (await resp.json()) as { results?: Array<{ success: boolean; result?: unknown; error?: { code?: string; message?: string } }> };
    if (!body || !Array.isArray(body.results) || body.results.length === 0) {
      throw new GatewayError('bad_response', `Unexpected /v1/batch payload: ${JSON.stringify(body)}`);
    }
    const first = body.results[0];
    if (first.success) {
      return first.result;
    }
    const code = first.error?.code ?? 'gateway_error';
    const message = first.error?.message ?? 'Unknown gateway error';
    throw new GatewayError(code, `[${code}] ${message}`);
  }

  private headers(): Record<string, string> {
    return {
      authorization: `Bearer ${this.apiKey}`,
      'user-agent': this.userAgent,
      accept: 'application/json',
    };
  }

  private async ensureOk(resp: Response): Promise<void> {
    if (resp.ok) return;
    const message = await extractMessage(resp);
    if (resp.status === 401 || resp.status === 403) {
      throw new GatewayAuthError(message ?? 'Gateway rejected API key');
    }
    if (resp.status === 429) {
      throw new GatewayRateLimitError(message ?? 'Gateway rate limit exceeded');
    }
    throw new GatewayError('http_error', `Gateway returned ${resp.status}: ${message ?? ''}`);
  }
}

async function extractMessage(resp: Response): Promise<string | null> {
  try {
    const body = await resp.json();
    if (body && typeof body === 'object') {
      const err = (body as Record<string, unknown>).error;
      if (err && typeof err === 'object' && typeof (err as Record<string, unknown>).message === 'string') {
        return (err as Record<string, string>).message;
      }
      if (typeof (body as Record<string, unknown>).detail === 'string') {
        return (body as Record<string, string>).detail;
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}
