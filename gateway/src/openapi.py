"""OpenAPI 3.1.0 spec generator for the A2A Commerce Gateway.

Reads the tool catalog and produces a complete OpenAPI specification,
including per-tool examples on the POST /execute endpoint.
"""

from __future__ import annotations

from gateway.src.catalog import get_catalog


def generate_openapi_spec() -> dict:
    """Generate and return the full OpenAPI 3.1.0 spec as a dict."""
    catalog = get_catalog()

    # ── Build per-tool examples for POST /execute ────────────────────
    execute_examples: dict = {}
    for tool in catalog:
        name = tool["name"]
        # Build a minimal example params dict from the input_schema
        example_params: dict = {}
        props = tool.get("input_schema", {}).get("properties", {})
        required = tool.get("input_schema", {}).get("required", [])
        for field, schema in props.items():
            if field not in required:
                continue
            ftype = schema.get("type", "string")
            if ftype == "string":
                example_params[field] = f"example-{field}"
            elif ftype == "number":
                example_params[field] = 1.0
            elif ftype == "integer":
                example_params[field] = 1
            elif ftype == "boolean":
                example_params[field] = True
            elif ftype == "object":
                example_params[field] = {}
            elif ftype == "array":
                example_params[field] = []
            else:
                example_params[field] = f"example-{field}"

        execute_examples[name] = {
            "summary": tool.get("description", name),
            "value": {
                "tool": name,
                "params": example_params,
            },
        }

    # ── Tool pricing items for GET /pricing response ─────────────────
    tool_pricing_examples = []
    for tool in catalog:
        tool_pricing_examples.append(
            {
                "name": tool["name"],
                "service": tool["service"],
                "description": tool.get("description", ""),
                "pricing": tool.get("pricing", {}),
                "sla": tool.get("sla", {}),
                "tier_required": tool.get("tier_required", "free"),
            }
        )

    spec: dict = {
        "openapi": "3.1.0",
        "info": {
            "title": "A2A Commerce Gateway",
            "version": "0.1.0",
            "description": (
                "Unified gateway for agent-to-agent commerce. "
                "Provides tool execution with metered billing, "
                "payment intents, escrow, marketplace search, "
                "trust scoring, and cross-product event bus."
            ),
        },
        "servers": [{"url": "/v1"}],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "health_check",
                    "summary": "Health check",
                    "description": "Returns the gateway health status.",
                    "tags": ["system"],
                    "responses": {
                        "200": {
                            "description": "Gateway is healthy.",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/HealthResponse"}}
                            },
                        }
                    },
                }
            },
            "/pricing": {
                "get": {
                    "operationId": "list_pricing",
                    "summary": "List tool catalog with pricing",
                    "description": "Returns the full tool catalog including pricing, SLA, and tier info.",
                    "tags": ["catalog"],
                    "responses": {
                        "200": {
                            "description": "Tool catalog list.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/ToolPricing"},
                                    },
                                    "example": tool_pricing_examples,
                                }
                            },
                        }
                    },
                }
            },
            "/pricing/{tool}": {
                "get": {
                    "operationId": "get_tool_pricing",
                    "summary": "Get pricing for a single tool",
                    "description": "Returns pricing, SLA, and tier info for the specified tool.",
                    "tags": ["catalog"],
                    "parameters": [
                        {
                            "name": "tool",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Tool name from the catalog.",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Tool pricing details.",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolPricing"}}},
                        },
                        "404": {
                            "description": "Tool not found.",
                            "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                        },
                    },
                }
            },
            "/execute": {
                "post": {
                    "operationId": "execute_tool",
                    "summary": "Execute a tool",
                    "description": (
                        "Execute a tool from the catalog. The request body specifies "
                        "the tool name and its parameters. Billing is applied automatically."
                    ),
                    "tags": ["execution"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ExecuteRequest"},
                                "examples": execute_examples,
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Tool executed successfully.",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/ExecuteResponse"}}
                            },
                        },
                        "400": {
                            "description": "Invalid request (missing tool, bad params).",
                            "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                        },
                        "402": {
                            "description": "Insufficient balance.",
                            "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                        },
                        "404": {
                            "description": "Tool not found.",
                            "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                        },
                        "500": {
                            "description": "Internal execution error.",
                            "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                        },
                    },
                }
            },
            "/openapi.json": {
                "get": {
                    "operationId": "get_openapi_spec",
                    "summary": "OpenAPI specification",
                    "description": "Returns this OpenAPI 3.1.0 specification as JSON.",
                    "tags": ["system"],
                    "responses": {
                        "200": {
                            "description": "OpenAPI spec.",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/metrics": {
                "get": {
                    "operationId": "get_metrics",
                    "summary": "Prometheus metrics",
                    "description": "Returns Prometheus-formatted metrics for the gateway.",
                    "tags": ["system"],
                    "responses": {
                        "200": {
                            "description": "Prometheus metrics in text exposition format.",
                            "content": {"text/plain": {"schema": {"type": "string"}}},
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "HealthResponse": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Health status string.",
                            "example": "ok",
                        },
                        "version": {
                            "type": "string",
                            "description": "Gateway version.",
                            "example": "0.1.0",
                        },
                        "timestamp": {
                            "type": "number",
                            "description": "Unix timestamp of the response.",
                        },
                    },
                    "required": ["status"],
                },
                "ExecuteRequest": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Name of the tool to execute.",
                            "example": "get_balance",
                        },
                        "params": {
                            "type": "object",
                            "description": "Parameters to pass to the tool.",
                            "additionalProperties": True,
                            "example": {"agent_id": "agent-123"},
                        },
                    },
                    "required": ["tool", "params"],
                },
                "ExecuteResponse": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Name of the tool that was executed.",
                        },
                        "result": {
                            "type": "object",
                            "description": "Tool-specific result payload.",
                            "additionalProperties": True,
                        },
                        "cost": {
                            "type": "number",
                            "description": "Cost charged for this execution.",
                        },
                        "balance_after": {
                            "type": "number",
                            "description": "Agent's wallet balance after execution.",
                        },
                    },
                    "required": ["tool", "result"],
                },
                "ErrorResponse": {
                    "type": "object",
                    "description": "RFC 9457 Problem Details error response.",
                    "properties": {
                        "type": {
                            "type": "string",
                            "format": "uri",
                            "description": "URI reference identifying the problem type.",
                            "example": "https://api.greenhelix.net/errors/unknown-tool",
                        },
                        "title": {
                            "type": "string",
                            "description": "Short human-readable summary of the problem type.",
                            "example": "Bad Request",
                        },
                        "status": {
                            "type": "integer",
                            "description": "HTTP status code.",
                            "example": 400,
                        },
                        "detail": {
                            "type": "string",
                            "description": "Human-readable explanation specific to this occurrence.",
                            "example": "Unknown tool: nonexistent",
                        },
                        "instance": {
                            "type": "string",
                            "description": "URI reference identifying the specific occurrence.",
                            "example": "/v1/execute",
                        },
                    },
                    "required": ["type", "title", "status", "detail"],
                },
                # Per-tool output schemas for key tools
                "GetBalanceOutput": {
                    "type": "object",
                    "properties": {
                        "balance": {
                            "type": "number",
                            "description": "Current wallet balance.",
                        },
                        "currency": {
                            "type": "string",
                            "description": "Currency code (only present if non-default).",
                        },
                    },
                    "required": ["balance"],
                },
                "CreateIntentOutput": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Payment intent ID.",
                        },
                        "status": {
                            "type": "string",
                            "description": "Intent status (e.g. pending, captured).",
                        },
                        "payer": {
                            "type": "string",
                            "description": "Payer agent ID.",
                        },
                        "payee": {
                            "type": "string",
                            "description": "Payee agent ID.",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Payment amount in atomic units.",
                        },
                    },
                    "required": ["id", "status", "payer", "payee", "amount"],
                },
                "GetPaymentHistoryOutput": {
                    "type": "object",
                    "properties": {
                        "history": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "description": "Record type (intent, settlement, escrow).",
                                    },
                                    "amount": {
                                        "type": "number",
                                        "description": "Payment amount.",
                                    },
                                    "created_at": {
                                        "type": "number",
                                        "description": "Unix timestamp.",
                                    },
                                },
                            },
                            "description": "List of payment history records.",
                        },
                    },
                    "required": ["history"],
                },
                "ToolPricing": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Tool name.",
                        },
                        "service": {
                            "type": "string",
                            "description": "Service the tool belongs to.",
                        },
                        "description": {
                            "type": "string",
                            "description": "What the tool does.",
                        },
                        "pricing": {
                            "type": "object",
                            "description": "Pricing information.",
                            "properties": {
                                "per_call": {
                                    "type": "number",
                                    "description": "Cost per invocation.",
                                }
                            },
                        },
                        "sla": {
                            "type": "object",
                            "description": "Service-level agreement.",
                            "properties": {
                                "max_latency_ms": {
                                    "type": "integer",
                                    "description": "Maximum expected latency in milliseconds.",
                                }
                            },
                        },
                        "tier_required": {
                            "type": "string",
                            "description": "Minimum tier required to use this tool.",
                            "enum": ["free", "starter", "pro", "enterprise"],
                        },
                    },
                    "required": ["name", "service", "pricing", "tier_required"],
                },
            },
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API key passed as Bearer token in the Authorization header.",
                },
                "X402Payment": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-PAYMENT",
                    "description": "x402 payment proof for stateless authentication.",
                },
            },
        },
        "security": [{"BearerAuth": []}, {"X402Payment": []}],
    }

    return spec
