# ADR-001: Technology Stack

**Date**: 2026-03-26
**Status**: Accepted
**Role**: CTO

## Context

We need a tech stack for building production-grade MCP server connectors and a billing/usage tracking layer. Key requirements:
- MCP SDK maturity and ecosystem support
- Fast development by AI agents
- Production reliability (async I/O, error handling, typing)
- Testability (mocking, coverage tooling)

## Decision

- **Language**: Python 3.12+ (type hints, async/await)
- **MCP SDK**: `mcp` (official Python SDK)
- **HTTP/API client**: `httpx` (async, retry-friendly)
- **Database**: `asyncpg` (for PostgreSQL connector), `sqlite3` (for billing local storage)
- **Testing**: `pytest` + `pytest-asyncio` + `pytest-cov`
- **Linting**: `ruff` (fast, replaces flake8+isort+black)
- **Package management**: `pip` with `pyproject.toml` per product
- **Shared code**: `products/shared/` package for common utilities (retry, rate limiting, logging, billing hooks)

## Alternatives Considered

- **TypeScript**: Good MCP support, but Python has stronger async database libraries and our team (AI agents) is equally proficient in both. Python's type hints + ruff give equivalent safety.
- **Go**: Too heavyweight for rapid iteration on connector products.

## Consequences

- All products use consistent tooling
- Shared utilities reduce duplication across connectors
- `ruff` enforces style without configuration debates
