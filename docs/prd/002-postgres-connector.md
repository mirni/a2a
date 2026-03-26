# PRD-002: PostgreSQL Production-Grade MCP Connector

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

AI agents need database access for data retrieval, analytics, and state management. Existing PostgreSQL MCP servers execute raw SQL without guardrails — no schema validation, no connection pooling, no query parameterization enforcement, no protection against destructive queries. This is unusable in production.

## Target Buyer

- AI agent developers building data-heavy agents
- Startups with PostgreSQL backends wanting agent-accessible data layers
- Analytics/BI agent builders

## Product Scope

An MCP server for PostgreSQL with production safety guarantees:

### Tools Provided
- `query` — Execute parameterized SELECT queries (read-only by default)
- `execute` — Execute parameterized INSERT/UPDATE/DELETE (requires explicit write mode)
- `list_tables` — Schema introspection
- `describe_table` — Column types, constraints, indexes
- `explain_query` — Query plan analysis
- `list_schemas` — Available schemas

### Production Guarantees (Differentiators)
- **Connection pooling**: Configurable pool size, health checks, reconnection
- **Query parameterization**: Enforced — no string interpolation, ever
- **Read-only mode**: Default mode prevents accidental writes
- **Schema validation**: Validate table/column existence before query execution
- **Query timeout**: Configurable per-query timeout to prevent runaway queries
- **Row limit**: Configurable max rows returned (prevent memory exhaustion)
- **Audit logging**: Every query logged with timestamp, duration, row count

## Pricing Hypothesis

- $39/month subscription
- Free tier: open-source core with read-only, no pooling

## Success Metrics

- 75+ GitHub stars in 30 days
- 15+ paid subscribers in 60 days
- Zero SQL injection vulnerabilities (ever)

## Kill Criteria

- <15 GitHub stars in 30 days → re-evaluate
- <3 paid subscribers in 90 days → kill
