"""GitHub API client with httpx, retry, and rate limiting."""

import base64
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("a2a.github.client")

# Lazy imports for shared modules
_retry_mod = None
_rate_limiter_mod = None
_errors_mod = None


def _get_retry():
    global _retry_mod
    if _retry_mod is None:
        import importlib
        _retry_mod = importlib.import_module("shared.src.retry")
    return _retry_mod


def _get_rate_limiter():
    global _rate_limiter_mod
    if _rate_limiter_mod is None:
        import importlib
        _rate_limiter_mod = importlib.import_module("shared.src.rate_limiter")
    return _rate_limiter_mod


def _get_errors():
    global _errors_mod
    if _errors_mod is None:
        import importlib
        _errors_mod = importlib.import_module("shared.src.errors")
    return _errors_mod


# Keys to keep from GitHub API responses for token-efficient output
_REPO_KEYS = frozenset({
    "id", "name", "full_name", "description", "private", "fork",
    "html_url", "language", "default_branch", "stargazers_count",
    "forks_count", "open_issues_count", "created_at", "updated_at",
    "pushed_at", "archived", "disabled", "topics",
})

_ISSUE_KEYS = frozenset({
    "number", "title", "state", "body", "html_url",
    "created_at", "updated_at", "closed_at", "labels", "assignees",
    "comments", "user",
})

_PR_KEYS = frozenset({
    "number", "title", "state", "body", "html_url",
    "created_at", "updated_at", "closed_at", "merged_at",
    "head", "base", "user", "labels", "draft",
    "additions", "deletions", "changed_files", "mergeable",
    "merged", "commits", "comments", "review_comments",
})

_COMMIT_KEYS = frozenset({
    "sha", "commit", "html_url", "author", "committer",
})

_SEARCH_CODE_ITEM_KEYS = frozenset({
    "name", "path", "sha", "html_url", "repository",
})


def _slim(data: dict[str, Any], allowed_keys: frozenset[str]) -> dict[str, Any]:
    """Strip a response dict down to only the allowed keys."""
    return {k: v for k, v in data.items() if k in allowed_keys}


def _slim_user(user: dict[str, Any] | None) -> dict[str, str] | None:
    """Slim a user object to just login and html_url."""
    if user is None:
        return None
    return {"login": user.get("login", ""), "html_url": user.get("html_url", "")}


def _slim_label(label: dict[str, Any]) -> dict[str, str]:
    """Slim a label object."""
    return {"name": label.get("name", ""), "color": label.get("color", "")}


def slim_repo(data: dict[str, Any]) -> dict[str, Any]:
    """Produce a token-efficient repo dict."""
    result = _slim(data, _REPO_KEYS)
    if "owner" in data:
        result["owner"] = _slim_user(data["owner"])
    return result


def slim_issue(data: dict[str, Any]) -> dict[str, Any]:
    """Produce a token-efficient issue dict."""
    result = _slim(data, _ISSUE_KEYS)
    if "user" in result:
        result["user"] = _slim_user(result["user"])
    if "labels" in result and isinstance(result["labels"], list):
        result["labels"] = [_slim_label(lb) for lb in result["labels"]]
    if "assignees" in result and isinstance(result["assignees"], list):
        result["assignees"] = [_slim_user(a) for a in result["assignees"]]
    return result


def slim_pr(data: dict[str, Any]) -> dict[str, Any]:
    """Produce a token-efficient pull request dict."""
    result = _slim(data, _PR_KEYS)
    if "user" in result:
        result["user"] = _slim_user(result["user"])
    if "labels" in result and isinstance(result["labels"], list):
        result["labels"] = [_slim_label(lb) for lb in result["labels"]]
    if "head" in result and isinstance(result["head"], dict):
        result["head"] = {
            "ref": result["head"].get("ref", ""),
            "sha": result["head"].get("sha", ""),
            "label": result["head"].get("label", ""),
        }
    if "base" in result and isinstance(result["base"], dict):
        result["base"] = {
            "ref": result["base"].get("ref", ""),
            "sha": result["base"].get("sha", ""),
            "label": result["base"].get("label", ""),
        }
    return result


def slim_commit(data: dict[str, Any]) -> dict[str, Any]:
    """Produce a token-efficient commit dict."""
    result = _slim(data, _COMMIT_KEYS)
    if "author" in result:
        result["author"] = _slim_user(result["author"])
    if "committer" in result:
        result["committer"] = _slim_user(result["committer"])
    if "commit" in result and isinstance(result["commit"], dict):
        commit_inner = result["commit"]
        result["commit"] = {
            "message": commit_inner.get("message", ""),
            "author": commit_inner.get("author", {}),
            "committer": commit_inner.get("committer", {}),
        }
    return result


def slim_search_code_item(data: dict[str, Any]) -> dict[str, Any]:
    """Produce a token-efficient search code item dict."""
    result = _slim(data, _SEARCH_CODE_ITEM_KEYS)
    if "repository" in result and isinstance(result["repository"], dict):
        result["repository"] = {
            "full_name": result["repository"].get("full_name", ""),
            "html_url": result["repository"].get("html_url", ""),
        }
    return result


class GitHubClient:
    """Async GitHub REST API client with retry and rate limiting.

    Features:
    - Exponential backoff on transient 5xx errors
    - Automatic rate-limit awareness (X-RateLimit-* headers, 429 auto-wait)
    - Token bucket rate limiter to prevent hitting limits proactively
    - Token-efficient response slimming
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None):
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        if not self._token:
            raise _get_errors().AuthenticationError("GITHUB_TOKEN environment variable is required")
        self._client: httpx.AsyncClient | None = None
        rate_limiter_mod = _get_rate_limiter()
        # GitHub allows 5000 req/hr for authenticated users
        self._rate_limiter = rate_limiter_mod.RateLimiter(max_requests=5000, window_seconds=3600.0)
        retry_mod = _get_retry()
        self._retry_config = retry_mod.RetryConfig(
            max_retries=3,
            base_delay=1.0,
            max_delay=60.0,
        )

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily create the httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.close()
            self._client = None

    def _check_rate_limit_headers(self, response: httpx.Response) -> None:
        """Log rate limit status from response headers."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")
        reset_ts = response.headers.get("X-RateLimit-Reset")
        if remaining is not None and limit is not None:
            logger.debug("Rate limit: %s/%s remaining", remaining, limit)
            if int(remaining) < 100:
                logger.warning(
                    "Rate limit low: %s/%s remaining, resets at %s",
                    remaining, limit, reset_ts,
                )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make a single HTTP request with rate limiting and retry."""
        errors = _get_errors()
        retry_mod = _get_retry()

        await self._rate_limiter.acquire()

        async def _do_request() -> httpx.Response:
            client = await self._ensure_client()
            response = await client.request(method, path, params=params, json=json_body)
            self._check_rate_limit_headers(response)

            if response.status_code == 401:
                raise errors.AuthenticationError("Invalid or expired GitHub token")
            if response.status_code == 403:
                # Could be rate limit or permission denied
                if "rate limit" in response.text.lower():
                    retry_after = response.headers.get("Retry-After")
                    reset_ts = response.headers.get("X-RateLimit-Reset")
                    wait_seconds = None
                    if retry_after:
                        wait_seconds = float(retry_after)
                    elif reset_ts:
                        wait_seconds = max(0.0, float(reset_ts) - time.time())
                    if wait_seconds:
                        await self._rate_limiter.wait_for_rate_limit(wait_seconds)
                    raise errors.RateLimitError(retry_after=wait_seconds)
                raise errors.ConnectorError(
                    f"Forbidden: {response.text}", code="FORBIDDEN", retryable=False
                )
            if response.status_code == 404:
                raise errors.ConnectorError(
                    "Resource not found", code="NOT_FOUND",
                    details={"path": path}, retryable=False,
                )
            if response.status_code == 422:
                raise errors.ValidationError(
                    f"Validation failed: {response.text}",
                    details={"response": response.json() if response.text else {}},
                )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else 60.0
                await self._rate_limiter.wait_for_rate_limit(wait)
                raise httpx.HTTPStatusError(
                    "Rate limited", request=response.request, response=response
                )
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Server error {response.status_code}",
                    request=response.request,
                    response=response,
                )

            return response

        try:
            return await retry_mod.retry_async(_do_request, config=self._retry_config)
        except retry_mod.RetryExhausted as e:
            last = e.last_error
            if isinstance(last, errors.ConnectorError):
                raise last from e
            raise errors.UpstreamError(
                str(last),
                status_code=getattr(getattr(last, "response", None), "status_code", None),
                retryable=False,
            ) from e

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET request, returns parsed JSON."""
        response = await self._request("GET", path, params=params)
        return response.json()

    async def post(self, path: str, json_body: dict[str, Any]) -> Any:
        """POST request, returns parsed JSON."""
        response = await self._request("POST", path, json_body=json_body)
        return response.json()

    # ── Repositories ─────────────────────────────────────────────

    async def list_repos(
        self,
        owner: str = "",
        type: str = "all",
        sort: str = "updated",
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List repositories for a user/org or the authenticated user."""
        if owner:
            path = f"/users/{owner}/repos"
        else:
            path = "/user/repos"
        params = {"type": type, "sort": sort, "page": page, "per_page": per_page}
        data = await self.get(path, params=params)
        return [slim_repo(r) for r in data]

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        """Get repository metadata."""
        data = await self.get(f"/repos/{owner}/{repo}")
        return slim_repo(data)

    # ── Issues ───────────────────────────────────────────────────

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        labels: str = "",
        sort: str = "created",
        direction: str = "desc",
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List issues for a repository."""
        params: dict[str, Any] = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": per_page,
        }
        if labels:
            params["labels"] = labels
        data = await self.get(f"/repos/{owner}/{repo}/issues", params=params)
        return [slim_issue(i) for i in data]

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an issue."""
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        data = await self.post(f"/repos/{owner}/{repo}/issues", payload)
        return slim_issue(data)

    # ── Pull Requests ────────────────────────────────────────────

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        sort: str = "created",
        direction: str = "desc",
        head: str = "",
        base: str = "",
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List pull requests for a repository."""
        params: dict[str, Any] = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": per_page,
        }
        if head:
            params["head"] = head
        if base:
            params["base"] = base
        data = await self.get(f"/repos/{owner}/{repo}/pulls", params=params)
        return [slim_pr(p) for p in data]

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any]:
        """Get a single pull request with diff stats."""
        data = await self.get(f"/repos/{owner}/{repo}/pulls/{pull_number}")
        return slim_pr(data)

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a pull request."""
        payload: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
        }
        if body:
            payload["body"] = body
        data = await self.post(f"/repos/{owner}/{repo}/pulls", payload)
        return slim_pr(data)

    # ── Commits ──────────────────────────────────────────────────

    async def list_commits(
        self,
        owner: str,
        repo: str,
        sha: str = "",
        path: str = "",
        since: str = "",
        until: str = "",
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List commits for a repository."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if sha:
            params["sha"] = sha
        if path:
            params["path"] = path
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        data = await self.get(f"/repos/{owner}/{repo}/commits", params=params)
        return [slim_commit(c) for c in data]

    # ── File Contents ────────────────────────────────────────────

    async def get_file_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "",
    ) -> dict[str, Any]:
        """Get file contents, handling base64 decoding for large files."""
        params: dict[str, Any] = {}
        if ref:
            params["ref"] = ref
        data = await self.get(f"/repos/{owner}/{repo}/contents/{path}", params=params)

        # If it's a file (not directory), decode content
        if isinstance(data, dict) and data.get("encoding") == "base64" and data.get("content"):
            try:
                raw_content = data["content"].replace("\n", "")
                decoded = base64.b64decode(raw_content).decode("utf-8", errors="replace")
                return {
                    "name": data.get("name", ""),
                    "path": data.get("path", ""),
                    "sha": data.get("sha", ""),
                    "size": data.get("size", 0),
                    "type": data.get("type", "file"),
                    "content": decoded,
                    "encoding": "utf-8",
                    "html_url": data.get("html_url", ""),
                }
            except Exception:
                # Return raw if decoding fails
                return {
                    "name": data.get("name", ""),
                    "path": data.get("path", ""),
                    "sha": data.get("sha", ""),
                    "size": data.get("size", 0),
                    "type": data.get("type", "file"),
                    "content": data.get("content", ""),
                    "encoding": "base64",
                    "html_url": data.get("html_url", ""),
                }

        # Directory listing or already decoded
        if isinstance(data, list):
            return {
                "type": "directory",
                "entries": [
                    {
                        "name": entry.get("name", ""),
                        "path": entry.get("path", ""),
                        "type": entry.get("type", ""),
                        "size": entry.get("size", 0),
                        "sha": entry.get("sha", ""),
                    }
                    for entry in data
                ],
            }

        return {
            "name": data.get("name", ""),
            "path": data.get("path", ""),
            "sha": data.get("sha", ""),
            "size": data.get("size", 0),
            "type": data.get("type", ""),
            "content": data.get("content", ""),
            "encoding": data.get("encoding", "none"),
            "html_url": data.get("html_url", ""),
        }

    # ── Code Search ──────────────────────────────────────────────

    async def search_code(
        self,
        query: str,
        page: int = 1,
        per_page: int = 30,
    ) -> dict[str, Any]:
        """Search code across repositories."""
        params: dict[str, Any] = {"q": query, "page": page, "per_page": per_page}
        data = await self.get("/search/code", params=params)
        return {
            "total_count": data.get("total_count", 0),
            "incomplete_results": data.get("incomplete_results", False),
            "items": [slim_search_code_item(item) for item in data.get("items", [])],
        }
