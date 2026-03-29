"""Tests for GitHub tool handlers with mocked client."""

from unittest.mock import AsyncMock

import pytest
from src.tools import (
    handle_create_issue,
    handle_create_pull_request,
    handle_get_file_contents,
    handle_get_pull_request,
    handle_get_repo,
    handle_list_commits,
    handle_list_issues,
    handle_list_pull_requests,
    handle_list_repos,
    handle_search_code,
)


def make_mock_client():
    """Create a mock GitHubClient."""
    client = AsyncMock()
    return client


class TestHandleListRepos:
    @pytest.mark.asyncio
    async def test_returns_repos(self):
        client = make_mock_client()
        client.list_repos.return_value = [
            {"name": "repo1", "full_name": "o/repo1"},
            {"name": "repo2", "full_name": "o/repo2"},
        ]
        result = await handle_list_repos(client, {"owner": "o"})
        assert result["count"] == 2
        assert result["repos"][0]["name"] == "repo1"
        assert result["page"] == 1
        assert result["per_page"] == 30

    @pytest.mark.asyncio
    async def test_pagination(self):
        client = make_mock_client()
        client.list_repos.return_value = [{"name": "repo1"}]
        result = await handle_list_repos(client, {"page": 3, "per_page": 10})
        assert result["page"] == 3
        assert result["per_page"] == 10
        client.list_repos.assert_called_once_with(
            owner="",
            type="all",
            sort="updated",
            page=3,
            per_page=10,
        )

    @pytest.mark.asyncio
    async def test_invalid_type(self):
        client = make_mock_client()
        with pytest.raises(Exception, match="type must be one of"):
            await handle_list_repos(client, {"type": "invalid"})

    @pytest.mark.asyncio
    async def test_audit_on_error(self):
        client = make_mock_client()
        client.list_repos.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError, match="API down"):
            await handle_list_repos(client, {})


class TestHandleGetRepo:
    @pytest.mark.asyncio
    async def test_returns_repo(self):
        client = make_mock_client()
        client.get_repo.return_value = {"name": "hello", "full_name": "o/hello"}
        result = await handle_get_repo(client, {"owner": "o", "repo": "hello"})
        assert result["full_name"] == "o/hello"

    @pytest.mark.asyncio
    async def test_missing_owner(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_get_repo(client, {"repo": "hello"})

    @pytest.mark.asyncio
    async def test_missing_repo(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_get_repo(client, {"owner": "o"})


class TestHandleListIssues:
    @pytest.mark.asyncio
    async def test_returns_issues(self):
        client = make_mock_client()
        client.list_issues.return_value = [
            {"number": 1, "title": "Bug", "state": "open"},
            {"number": 2, "title": "Feature", "state": "open"},
        ]
        result = await handle_list_issues(client, {"owner": "o", "repo": "r"})
        assert result["count"] == 2
        assert result["issues"][0]["number"] == 1

    @pytest.mark.asyncio
    async def test_with_filters(self):
        client = make_mock_client()
        client.list_issues.return_value = []
        await handle_list_issues(
            client,
            {
                "owner": "o",
                "repo": "r",
                "state": "closed",
                "labels": "bug",
            },
        )
        client.list_issues.assert_called_once_with(
            owner="o",
            repo="r",
            state="closed",
            labels="bug",
            sort="created",
            direction="desc",
            page=1,
            per_page=30,
        )

    @pytest.mark.asyncio
    async def test_invalid_state(self):
        client = make_mock_client()
        with pytest.raises(Exception, match="state must be one of"):
            await handle_list_issues(client, {"owner": "o", "repo": "r", "state": "invalid"})


class TestHandleCreateIssue:
    @pytest.mark.asyncio
    async def test_creates_issue(self):
        client = make_mock_client()
        client.create_issue.return_value = {"number": 42, "title": "Bug report"}
        result = await handle_create_issue(
            client,
            {
                "owner": "o",
                "repo": "r",
                "title": "Bug report",
                "body": "Detailed description",
                "labels": ["bug"],
            },
        )
        assert result["number"] == 42
        client.create_issue.assert_called_once_with(
            owner="o",
            repo="r",
            title="Bug report",
            body="Detailed description",
            labels=["bug"],
            assignees=[],
        )

    @pytest.mark.asyncio
    async def test_missing_title(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_create_issue(client, {"owner": "o", "repo": "r"})

    @pytest.mark.asyncio
    async def test_empty_title(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_create_issue(client, {"owner": "o", "repo": "r", "title": ""})


class TestHandleListPullRequests:
    @pytest.mark.asyncio
    async def test_returns_prs(self):
        client = make_mock_client()
        client.list_pull_requests.return_value = [
            {"number": 1, "title": "Feature", "state": "open"},
        ]
        result = await handle_list_pull_requests(client, {"owner": "o", "repo": "r"})
        assert result["count"] == 1
        assert result["pull_requests"][0]["number"] == 1

    @pytest.mark.asyncio
    async def test_with_branch_filter(self):
        client = make_mock_client()
        client.list_pull_requests.return_value = []
        await handle_list_pull_requests(
            client,
            {
                "owner": "o",
                "repo": "r",
                "head": "user:feature",
                "base": "main",
            },
        )
        client.list_pull_requests.assert_called_once_with(
            owner="o",
            repo="r",
            state="open",
            sort="created",
            direction="desc",
            head="user:feature",
            base="main",
            page=1,
            per_page=30,
        )


class TestHandleGetPullRequest:
    @pytest.mark.asyncio
    async def test_returns_pr(self):
        client = make_mock_client()
        client.get_pull_request.return_value = {
            "number": 7,
            "title": "Feature",
            "additions": 100,
            "deletions": 20,
            "changed_files": 5,
        }
        result = await handle_get_pull_request(
            client,
            {
                "owner": "o",
                "repo": "r",
                "pull_number": 7,
            },
        )
        assert result["additions"] == 100
        assert result["changed_files"] == 5

    @pytest.mark.asyncio
    async def test_invalid_pull_number(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_get_pull_request(
                client,
                {
                    "owner": "o",
                    "repo": "r",
                    "pull_number": 0,
                },
            )


class TestHandleCreatePullRequest:
    @pytest.mark.asyncio
    async def test_creates_pr(self):
        client = make_mock_client()
        client.create_pull_request.return_value = {
            "number": 10,
            "title": "New feature",
        }
        result = await handle_create_pull_request(
            client,
            {
                "owner": "o",
                "repo": "r",
                "title": "New feature",
                "head": "feature",
                "base": "main",
            },
        )
        assert result["number"] == 10

    @pytest.mark.asyncio
    async def test_draft_pr(self):
        client = make_mock_client()
        client.create_pull_request.return_value = {"number": 11}
        await handle_create_pull_request(
            client,
            {
                "owner": "o",
                "repo": "r",
                "title": "WIP",
                "head": "wip",
                "base": "main",
                "draft": True,
            },
        )
        client.create_pull_request.assert_called_once_with(
            owner="o",
            repo="r",
            title="WIP",
            head="wip",
            base="main",
            body="",
            draft=True,
        )

    @pytest.mark.asyncio
    async def test_missing_head(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_create_pull_request(
                client,
                {
                    "owner": "o",
                    "repo": "r",
                    "title": "T",
                    "base": "main",
                },
            )


class TestHandleListCommits:
    @pytest.mark.asyncio
    async def test_returns_commits(self):
        client = make_mock_client()
        client.list_commits.return_value = [
            {"sha": "abc", "commit": {"message": "Fix bug"}},
            {"sha": "def", "commit": {"message": "Add feature"}},
        ]
        result = await handle_list_commits(client, {"owner": "o", "repo": "r"})
        assert result["count"] == 2
        assert result["commits"][0]["sha"] == "abc"

    @pytest.mark.asyncio
    async def test_with_filters(self):
        client = make_mock_client()
        client.list_commits.return_value = []
        await handle_list_commits(
            client,
            {
                "owner": "o",
                "repo": "r",
                "sha": "main",
                "path": "src/",
                "since": "2026-01-01",
                "until": "2026-03-01",
            },
        )
        client.list_commits.assert_called_once_with(
            owner="o",
            repo="r",
            sha="main",
            path="src/",
            since="2026-01-01",
            until="2026-03-01",
            page=1,
            per_page=30,
        )


class TestHandleGetFileContents:
    @pytest.mark.asyncio
    async def test_returns_file(self):
        client = make_mock_client()
        client.get_file_contents.return_value = {
            "name": "main.py",
            "path": "src/main.py",
            "type": "file",
            "content": "print('hello')",
            "encoding": "utf-8",
        }
        result = await handle_get_file_contents(
            client,
            {
                "owner": "o",
                "repo": "r",
                "path": "src/main.py",
            },
        )
        assert result["content"] == "print('hello')"

    @pytest.mark.asyncio
    async def test_returns_directory(self):
        client = make_mock_client()
        client.get_file_contents.return_value = {
            "type": "directory",
            "entries": [{"name": "main.py", "path": "src/main.py", "type": "file"}],
        }
        result = await handle_get_file_contents(
            client,
            {
                "owner": "o",
                "repo": "r",
                "path": "src/",
            },
        )
        assert result["type"] == "directory"

    @pytest.mark.asyncio
    async def test_with_ref(self):
        client = make_mock_client()
        client.get_file_contents.return_value = {"type": "file", "content": "x"}
        await handle_get_file_contents(
            client,
            {
                "owner": "o",
                "repo": "r",
                "path": "README.md",
                "ref": "v1.0",
            },
        )
        client.get_file_contents.assert_called_once_with(
            owner="o",
            repo="r",
            path="README.md",
            ref="v1.0",
        )

    @pytest.mark.asyncio
    async def test_missing_path(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_get_file_contents(client, {"owner": "o", "repo": "r"})


class TestHandleSearchCode:
    @pytest.mark.asyncio
    async def test_returns_results(self):
        client = make_mock_client()
        client.search_code.return_value = {
            "total_count": 42,
            "incomplete_results": False,
            "items": [{"name": "main.py", "path": "src/main.py"}],
        }
        result = await handle_search_code(
            client,
            {
                "query": "class HTTPClient language:python",
            },
        )
        assert result["total_count"] == 42
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_empty_query(self):
        client = make_mock_client()
        with pytest.raises(Exception):
            await handle_search_code(client, {"query": ""})

    @pytest.mark.asyncio
    async def test_pagination(self):
        client = make_mock_client()
        client.search_code.return_value = {
            "total_count": 100,
            "incomplete_results": False,
            "items": [],
        }
        await handle_search_code(client, {"query": "test", "page": 2, "per_page": 50})
        client.search_code.assert_called_once_with(
            query="test",
            page=2,
            per_page=50,
        )
