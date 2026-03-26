# GitHub MCP Connector

Production-grade MCP server for GitHub with automatic pagination, rate-limit handling, and token-efficient responses.

## Tools

| Tool | Description |
|------|-------------|
| `list_repos` | Paginated repository listing with filters |
| `get_repo` | Repository metadata (stars, forks, language, topics) |
| `list_issues` | Issue listing with state/label/sort filters |
| `create_issue` | Issue creation with labels and assignees |
| `list_pull_requests` | PR listing with state/branch filters |
| `get_pull_request` | PR details including diff stats |
| `create_pull_request` | PR creation with draft support |
| `list_commits` | Commit history with pagination |
| `get_file_contents` | File/directory content retrieval |
| `search_code` | Code search across repositories |

## Quick Start

```bash
# Set your GitHub token
export GITHUB_TOKEN=ghp_...

# Run the MCP server
python -m src.server
```

## Configuration

| Env Variable | Required | Description |
|-------------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub personal access token or fine-grained token |

## Production Features

- **Auto-pagination**: All list operations support transparent cursor-based pagination
- **Rate-limit handling**: Respects `X-RateLimit-*` headers, auto-waits on 429/403 rate limits
- **Token-efficient**: Responses stripped to essential fields (no node_ids, URLs, internal metadata)
- **Retry**: Exponential backoff on transient 5xx errors
- **Structured errors**: Machine-readable error codes
- **Audit logging**: Every operation logged with timing and results

## Example Usage

```json
{
  "tool": "search_code",
  "arguments": {
    "query": "async def retry language:python",
    "per_page": 10
  }
}
```

```json
{
  "tool": "create_pull_request",
  "arguments": {
    "owner": "myorg",
    "repo": "myapp",
    "title": "Fix authentication bug",
    "head": "fix/auth-bug",
    "base": "main",
    "body": "Fixes the token refresh race condition",
    "draft": false
  }
}
```
