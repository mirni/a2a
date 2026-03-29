"""MCP tool handlers for GitHub connector."""

import logging
import time
from typing import Any

from src.models import (
    CreateIssueParams,
    CreatePullRequestParams,
    GetFileContentsParams,
    GetPullRequestParams,
    GetRepoParams,
    ListCommitsParams,
    ListIssuesParams,
    ListPullRequestsParams,
    ListReposParams,
    SearchCodeParams,
)

logger = logging.getLogger("a2a.github")

# Shared module imports — lazy to avoid module name collisions
_audit = None
_errors = None


def _get_audit():
    global _audit
    if _audit is None:
        import importlib

        _audit = importlib.import_module("shared.src.audit_log")
    return _audit


def _get_errors():
    global _errors
    if _errors is None:
        import importlib

        _errors = importlib.import_module("shared.src.errors")
    return _errors


async def handle_list_repos(client, params: dict[str, Any]) -> dict[str, Any]:
    """List repositories with pagination."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = ListReposParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        repos = await client.list_repos(
            owner=validated.owner,
            type=validated.type,
            sort=validated.sort,
            page=validated.page,
            per_page=validated.per_page,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_repos",
            connector="github",
            params={"owner": validated.owner, "type": validated.type, "page": validated.page},
            result_summary=f"returned {len(repos)} repos",
            duration_ms=duration,
        )
        return {
            "repos": repos,
            "count": len(repos),
            "page": validated.page,
            "per_page": validated.per_page,
        }
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_repos",
            connector="github",
            params={"owner": validated.owner},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_get_repo(client, params: dict[str, Any]) -> dict[str, Any]:
    """Get repository metadata."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = GetRepoParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        repo = await client.get_repo(owner=validated.owner, repo=validated.repo)
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="get_repo",
            connector="github",
            params={"owner": validated.owner, "repo": validated.repo},
            result_summary=f"found {validated.owner}/{validated.repo}",
            duration_ms=duration,
        )
        return repo
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="get_repo",
            connector="github",
            params={"owner": validated.owner, "repo": validated.repo},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_list_issues(client, params: dict[str, Any]) -> dict[str, Any]:
    """List issues with pagination and filters."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = ListIssuesParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        issues = await client.list_issues(
            owner=validated.owner,
            repo=validated.repo,
            state=validated.state,
            labels=validated.labels,
            sort=validated.sort,
            direction=validated.direction,
            page=validated.page,
            per_page=validated.per_page,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_issues",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "state": validated.state,
                "page": validated.page,
            },
            result_summary=f"returned {len(issues)} issues",
            duration_ms=duration,
        )
        return {
            "issues": issues,
            "count": len(issues),
            "page": validated.page,
            "per_page": validated.per_page,
        }
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_issues",
            connector="github",
            params={"owner": validated.owner, "repo": validated.repo},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_create_issue(client, params: dict[str, Any]) -> dict[str, Any]:
    """Create an issue."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = CreateIssueParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        issue = await client.create_issue(
            owner=validated.owner,
            repo=validated.repo,
            title=validated.title,
            body=validated.body,
            labels=validated.labels,
            assignees=validated.assignees,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="create_issue",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "title": validated.title,
            },
            result_summary=f"created issue #{issue.get('number', '?')}",
            duration_ms=duration,
        )
        return issue
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="create_issue",
            connector="github",
            params={"owner": validated.owner, "repo": validated.repo, "title": validated.title},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_list_pull_requests(client, params: dict[str, Any]) -> dict[str, Any]:
    """List pull requests with pagination."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = ListPullRequestsParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        prs = await client.list_pull_requests(
            owner=validated.owner,
            repo=validated.repo,
            state=validated.state,
            sort=validated.sort,
            direction=validated.direction,
            head=validated.head,
            base=validated.base,
            page=validated.page,
            per_page=validated.per_page,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_pull_requests",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "state": validated.state,
                "page": validated.page,
            },
            result_summary=f"returned {len(prs)} pull requests",
            duration_ms=duration,
        )
        return {
            "pull_requests": prs,
            "count": len(prs),
            "page": validated.page,
            "per_page": validated.per_page,
        }
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_pull_requests",
            connector="github",
            params={"owner": validated.owner, "repo": validated.repo},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_get_pull_request(client, params: dict[str, Any]) -> dict[str, Any]:
    """Get pull request details."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = GetPullRequestParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        pr = await client.get_pull_request(
            owner=validated.owner,
            repo=validated.repo,
            pull_number=validated.pull_number,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="get_pull_request",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "pull_number": validated.pull_number,
            },
            result_summary=f"found PR #{validated.pull_number}",
            duration_ms=duration,
        )
        return pr
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="get_pull_request",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "pull_number": validated.pull_number,
            },
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_create_pull_request(client, params: dict[str, Any]) -> dict[str, Any]:
    """Create a pull request."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = CreatePullRequestParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        pr = await client.create_pull_request(
            owner=validated.owner,
            repo=validated.repo,
            title=validated.title,
            head=validated.head,
            base=validated.base,
            body=validated.body,
            draft=validated.draft,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="create_pull_request",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "title": validated.title,
                "head": validated.head,
                "base": validated.base,
            },
            result_summary=f"created PR #{pr.get('number', '?')}",
            duration_ms=duration,
        )
        return pr
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="create_pull_request",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "title": validated.title,
            },
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_list_commits(client, params: dict[str, Any]) -> dict[str, Any]:
    """List commits with pagination."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = ListCommitsParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        commits = await client.list_commits(
            owner=validated.owner,
            repo=validated.repo,
            sha=validated.sha,
            path=validated.path,
            since=validated.since,
            until=validated.until,
            page=validated.page,
            per_page=validated.per_page,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_commits",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "page": validated.page,
            },
            result_summary=f"returned {len(commits)} commits",
            duration_ms=duration,
        )
        return {
            "commits": commits,
            "count": len(commits),
            "page": validated.page,
            "per_page": validated.per_page,
        }
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="list_commits",
            connector="github",
            params={"owner": validated.owner, "repo": validated.repo},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_get_file_contents(client, params: dict[str, Any]) -> dict[str, Any]:
    """Get file contents from a repository."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = GetFileContentsParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        contents = await client.get_file_contents(
            owner=validated.owner,
            repo=validated.repo,
            path=validated.path,
            ref=validated.ref,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="get_file_contents",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "path": validated.path,
                "ref": validated.ref,
            },
            result_summary=f"type={contents.get('type', 'unknown')}",
            duration_ms=duration,
        )
        return contents
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="get_file_contents",
            connector="github",
            params={
                "owner": validated.owner,
                "repo": validated.repo,
                "path": validated.path,
            },
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_search_code(client, params: dict[str, Any]) -> dict[str, Any]:
    """Search code across repositories."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = SearchCodeParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        results = await client.search_code(
            query=validated.query,
            page=validated.page,
            per_page=validated.per_page,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="search_code",
            connector="github",
            params={"query": validated.query, "page": validated.page},
            result_summary=f"total_count={results.get('total_count', 0)}, returned {len(results.get('items', []))} items",
            duration_ms=duration,
        )
        return results
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="search_code",
            connector="github",
            params={"query": validated.query},
            error=str(e),
            duration_ms=duration,
        )
        raise
