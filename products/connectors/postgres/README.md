# PostgreSQL MCP Connector

Production-grade MCP server for PostgreSQL with connection pooling, parameterized queries, read-only mode, and SQL injection prevention.

## Tools

| Tool | Description |
|------|-------------|
| `query` | Execute read-only SELECT queries (parameterized) |
| `execute` | Execute INSERT/UPDATE/DELETE (requires write mode) |
| `list_tables` | List tables in a schema |
| `describe_table` | Get column types, constraints, defaults |
| `explain_query` | Get query execution plan |
| `list_schemas` | List available schemas |

## Quick Start

```bash
# Set database connection
export PG_HOST=localhost
export PG_PORT=5432
export PG_DATABASE=mydb
export PG_USER=myuser
export PG_PASSWORD=mypass

# Run the MCP server (read-only by default)
python -m src.server
```

## Configuration

| Env Variable | Required | Default | Description |
|-------------|----------|---------|-------------|
| `PG_HOST` | No | localhost | Database host |
| `PG_PORT` | No | 5432 | Database port |
| `PG_DATABASE` | Yes | — | Database name |
| `PG_USER` | Yes | — | Database user |
| `PG_PASSWORD` | No | — | Database password |
| `PG_SSL` | No | false | Enable SSL |
| `PG_READ_ONLY` | No | true | Block write operations |

## Safety Guarantees

- **Parameterized queries**: All queries use `$1, $2, ...` parameters — no string interpolation, ever
- **Read-only default**: Write operations blocked unless explicitly enabled
- **Multi-statement block**: Semicolons within queries are rejected (prevents injection)
- **Identifier validation**: Table/schema names validated against `[a-zA-Z0-9_]` pattern
- **Query timeout**: Configurable per-query (max 300s)
- **Row limit**: Configurable max rows returned (max 10,000)
- **Connection pooling**: Configurable pool size with health checks
- **Audit logging**: Every query logged with duration and row count

## Example Usage

```json
{
  "tool": "query",
  "arguments": {
    "sql": "SELECT id, name, email FROM users WHERE created_at > $1 ORDER BY created_at DESC",
    "params": ["2026-01-01"],
    "max_rows": 100
  }
}
```

Response:
```json
{
  "rows": [
    {"id": 1, "name": "Alice", "email": "alice@example.com"},
    {"id": 2, "name": "Bob", "email": "bob@example.com"}
  ],
  "row_count": 2,
  "truncated": false
}
```
