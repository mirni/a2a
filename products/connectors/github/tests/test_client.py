"""Tests for GitHub API client with mocked httpx responses."""

import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from src.client import (
    GitHubClient,
    _slim_label,
    _slim_user,
    slim_commit,
    slim_issue,
    slim_pr,
    slim_repo,
    slim_search_code_item,
)

# ── Slim helpers ─────────────────────────────────────────────────────


class TestSlimHelpers:
    def test_slim_user(self):
        user = {"login": "octocat", "html_url": "https://github.com/octocat", "id": 1, "node_id": "x"}
        result = _slim_user(user)
        assert result == {"login": "octocat", "html_url": "https://github.com/octocat"}

    def test_slim_user_none(self):
        assert _slim_user(None) is None

    def test_slim_label(self):
        label = {"name": "bug", "color": "d73a4a", "id": 1, "url": "http://..."}
        result = _slim_label(label)
        assert result == {"name": "bug", "color": "d73a4a"}

    def test_slim_repo(self):
        full_repo = {
            "id": 1,
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "description": "A test repo",
            "private": False,
            "fork": False,
            "html_url": "https://github.com/octocat/hello-world",
            "language": "Python",
            "default_branch": "main",
            "stargazers_count": 100,
            "forks_count": 50,
            "open_issues_count": 10,
            "created_at": "2020-01-01",
            "updated_at": "2026-03-01",
            "pushed_at": "2026-03-01",
            "archived": False,
            "disabled": False,
            "topics": ["python"],
            "owner": {"login": "octocat", "html_url": "h", "id": 1},
            # Fields that should be stripped:
            "node_id": "xxx",
            "git_url": "git://...",
            "clone_url": "https://...",
            "hooks_url": "https://...",
            "subscribers_count": 999,
        }
        result = slim_repo(full_repo)
        assert "name" in result
        assert "node_id" not in result
        assert "git_url" not in result
        assert "subscribers_count" not in result
        assert result["owner"]["login"] == "octocat"

    def test_slim_issue(self):
        full_issue = {
            "number": 42,
            "title": "Bug",
            "state": "open",
            "body": "Details",
            "html_url": "https://...",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-02",
            "closed_at": None,
            "labels": [{"name": "bug", "color": "d73a4a", "id": 1}],
            "assignees": [{"login": "user1", "html_url": "h", "id": 2}],
            "comments": 3,
            "user": {"login": "author", "html_url": "h", "id": 3},
            # Stripped:
            "node_id": "x",
            "events_url": "https://...",
        }
        result = slim_issue(full_issue)
        assert result["number"] == 42
        assert "node_id" not in result
        assert result["user"]["login"] == "author"
        assert result["labels"][0]["name"] == "bug"
        assert result["assignees"][0]["login"] == "user1"

    def test_slim_pr(self):
        full_pr = {
            "number": 7,
            "title": "Feature",
            "state": "open",
            "body": "...",
            "html_url": "h",
            "created_at": "c",
            "updated_at": "u",
            "closed_at": None,
            "merged_at": None,
            "head": {"ref": "feature", "sha": "abc", "label": "user:feature", "repo": {}},
            "base": {"ref": "main", "sha": "def", "label": "owner:main", "repo": {}},
            "user": {"login": "author", "html_url": "h", "id": 1},
            "labels": [{"name": "enhancement", "color": "a2eeef", "id": 2}],
            "draft": False,
            "additions": 100,
            "deletions": 20,
            "changed_files": 5,
            "mergeable": True,
            "merged": False,
            "commits": 3,
            "comments": 1,
            "review_comments": 2,
            # Stripped:
            "node_id": "x",
            "diff_url": "d",
        }
        result = slim_pr(full_pr)
        assert result["number"] == 7
        assert "node_id" not in result
        assert result["head"]["ref"] == "feature"
        assert result["base"]["ref"] == "main"
        assert result["additions"] == 100
        assert result["user"]["login"] == "author"

    def test_slim_commit(self):
        full_commit = {
            "sha": "abc123",
            "commit": {
                "message": "Fix bug",
                "author": {"name": "User", "email": "user@example.com", "date": "2026-01-01"},
                "committer": {"name": "User", "email": "user@example.com", "date": "2026-01-01"},
                "tree": {"sha": "tree123"},
            },
            "html_url": "h",
            "author": {"login": "user", "html_url": "h", "id": 1},
            "committer": {"login": "user", "html_url": "h", "id": 1},
            # Stripped:
            "node_id": "x",
            "parents": [],
        }
        result = slim_commit(full_commit)
        assert result["sha"] == "abc123"
        assert result["commit"]["message"] == "Fix bug"
        assert "node_id" not in result
        assert "parents" not in result

    def test_slim_search_code_item(self):
        full_item = {
            "name": "main.py",
            "path": "src/main.py",
            "sha": "abc",
            "html_url": "h",
            "repository": {
                "full_name": "octocat/hello",
                "html_url": "h",
                "id": 1,
                "node_id": "x",
            },
            # Stripped:
            "git_url": "g",
            "score": 1.0,
        }
        result = slim_search_code_item(full_item)
        assert result["name"] == "main.py"
        assert "git_url" not in result
        assert "score" not in result
        assert result["repository"]["full_name"] == "octocat/hello"


# ── Client initialization ────────────────────────────────────────────


class TestClientInit:
    def test_requires_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(Exception, match="GITHUB_TOKEN"):
                GitHubClient(token="")

    def test_token_from_param(self):
        client = GitHubClient(token="ghp_test123")
        assert client._token == "ghp_test123"

    def test_token_from_env(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_envtoken"}):
            client = GitHubClient()
            assert client._token == "ghp_envtoken"


# ── HTTP request method ──────────────────────────────────────────────


def _make_response(status_code: int, json_data=None, text="", headers=None):
    """Create a mock httpx.Response."""
    request = httpx.Request("GET", "https://api.github.com/test")
    if json_data is not None:
        content = json.dumps(json_data).encode("utf-8")
        final_headers = {"content-type": "application/json"}
        if headers:
            final_headers.update(headers)
        response = httpx.Response(
            status_code=status_code,
            request=request,
            content=content,
            headers=final_headers,
        )
    else:
        response = httpx.Response(
            status_code=status_code,
            request=request,
            text=text,
            headers=headers or {},
        )
    return response


class TestClientRequests:
    @pytest.fixture
    def client(self):
        c = GitHubClient(token="ghp_test")
        return c

    @pytest.mark.asyncio
    async def test_get_success(self, client):
        mock_response = _make_response(200, json_data=[{"id": 1, "name": "repo1"}])
        mock_http_client = AsyncMock()
        mock_http_client.request = AsyncMock(return_value=mock_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        result = await client.get("/user/repos", params={"page": 1})
        assert result == [{"id": 1, "name": "repo1"}]

    @pytest.mark.asyncio
    async def test_post_success(self, client):
        mock_response = _make_response(200, json_data={"number": 42, "title": "Bug"})
        mock_http_client = AsyncMock()
        mock_http_client.request = AsyncMock(return_value=mock_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        result = await client.post("/repos/o/r/issues", {"title": "Bug"})
        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self, client):
        mock_response = _make_response(404, text="Not Found")
        mock_http_client = AsyncMock()
        mock_http_client.request = AsyncMock(return_value=mock_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        with pytest.raises(Exception, match="not found"):
            await client.get("/repos/o/nonexistent")

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, client):
        mock_response = _make_response(401, text="Bad credentials")
        mock_http_client = AsyncMock()
        mock_http_client.request = AsyncMock(return_value=mock_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        with pytest.raises(Exception, match="token"):
            await client.get("/user")

    @pytest.mark.asyncio
    async def test_422_raises_validation_error(self, client):
        mock_response = _make_response(
            422,
            json_data={"message": "Validation Failed", "errors": []},
        )
        mock_http_client = AsyncMock()
        mock_http_client.request = AsyncMock(return_value=mock_response)
        mock_http_client.is_closed = False
        client._client = mock_http_client

        with pytest.raises(Exception, match="Validation failed"):
            await client.post("/repos/o/r/issues", {"title": ""})

    @pytest.mark.asyncio
    async def test_close(self, client):
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        client._client = mock_http_client

        await client.close()
        mock_http_client.close.assert_called_once()


# ── Domain methods ───────────────────────────────────────────────────


class TestClientDomainMethods:
    @pytest.fixture
    def client(self):
        c = GitHubClient(token="ghp_test")
        return c

    def _patch_get(self, client, return_value):
        """Patch client.get to return a value without HTTP."""
        client.get = AsyncMock(return_value=return_value)

    def _patch_post(self, client, return_value):
        """Patch client.post to return a value without HTTP."""
        client.post = AsyncMock(return_value=return_value)

    @pytest.mark.asyncio
    async def test_list_repos_authenticated_user(self, client):
        self._patch_get(
            client,
            [
                {
                    "id": 1,
                    "name": "repo1",
                    "full_name": "me/repo1",
                    "description": "",
                    "private": False,
                    "fork": False,
                    "html_url": "h",
                    "language": "Python",
                    "default_branch": "main",
                    "stargazers_count": 0,
                    "forks_count": 0,
                    "open_issues_count": 0,
                    "created_at": "c",
                    "updated_at": "u",
                    "pushed_at": "p",
                    "archived": False,
                    "disabled": False,
                    "topics": [],
                },
            ],
        )
        repos = await client.list_repos()
        assert len(repos) == 1
        assert repos[0]["name"] == "repo1"
        client.get.assert_called_once_with(
            "/user/repos",
            params={
                "type": "all",
                "sort": "updated",
                "page": 1,
                "per_page": 30,
            },
        )

    @pytest.mark.asyncio
    async def test_list_repos_by_owner(self, client):
        self._patch_get(client, [])
        await client.list_repos(owner="octocat")
        client.get.assert_called_once_with(
            "/users/octocat/repos",
            params={
                "type": "all",
                "sort": "updated",
                "page": 1,
                "per_page": 30,
            },
        )

    @pytest.mark.asyncio
    async def test_get_repo(self, client):
        self._patch_get(
            client,
            {
                "id": 1,
                "name": "hello",
                "full_name": "o/hello",
                "description": "desc",
                "private": False,
                "fork": False,
                "html_url": "h",
                "language": "Go",
                "default_branch": "main",
                "stargazers_count": 10,
                "forks_count": 5,
                "open_issues_count": 2,
                "created_at": "c",
                "updated_at": "u",
                "pushed_at": "p",
                "archived": False,
                "disabled": False,
                "topics": [],
            },
        )
        repo = await client.get_repo("o", "hello")
        assert repo["full_name"] == "o/hello"

    @pytest.mark.asyncio
    async def test_list_issues(self, client):
        self._patch_get(
            client,
            [
                {
                    "number": 1,
                    "title": "Bug",
                    "state": "open",
                    "body": "",
                    "html_url": "h",
                    "created_at": "c",
                    "updated_at": "u",
                    "closed_at": None,
                    "labels": [],
                    "assignees": [],
                    "comments": 0,
                    "user": {"login": "a", "html_url": "h"},
                },
            ],
        )
        issues = await client.list_issues("o", "r")
        assert len(issues) == 1
        assert issues[0]["number"] == 1

    @pytest.mark.asyncio
    async def test_create_issue(self, client):
        self._patch_post(
            client,
            {
                "number": 42,
                "title": "New bug",
                "state": "open",
                "body": "Details",
                "html_url": "h",
                "created_at": "c",
                "updated_at": "u",
                "closed_at": None,
                "labels": [{"name": "bug", "color": "red"}],
                "assignees": [],
                "comments": 0,
                "user": {"login": "me", "html_url": "h"},
            },
        )
        issue = await client.create_issue("o", "r", "New bug", body="Details", labels=["bug"])
        assert issue["number"] == 42
        assert issue["labels"][0]["name"] == "bug"

    @pytest.mark.asyncio
    async def test_list_pull_requests(self, client):
        self._patch_get(
            client,
            [
                {
                    "number": 7,
                    "title": "PR",
                    "state": "open",
                    "body": "",
                    "html_url": "h",
                    "created_at": "c",
                    "updated_at": "u",
                    "closed_at": None,
                    "merged_at": None,
                    "head": {"ref": "f", "sha": "a", "label": "u:f"},
                    "base": {"ref": "main", "sha": "b", "label": "o:main"},
                    "user": {"login": "u", "html_url": "h"},
                    "labels": [],
                    "draft": False,
                    "additions": 10,
                    "deletions": 5,
                    "changed_files": 2,
                    "mergeable": True,
                    "merged": False,
                    "commits": 1,
                    "comments": 0,
                    "review_comments": 0,
                },
            ],
        )
        prs = await client.list_pull_requests("o", "r")
        assert len(prs) == 1

    @pytest.mark.asyncio
    async def test_get_pull_request(self, client):
        self._patch_get(
            client,
            {
                "number": 7,
                "title": "PR",
                "state": "open",
                "body": "",
                "html_url": "h",
                "created_at": "c",
                "updated_at": "u",
                "closed_at": None,
                "merged_at": None,
                "head": {"ref": "f", "sha": "a", "label": "u:f"},
                "base": {"ref": "main", "sha": "b", "label": "o:main"},
                "user": {"login": "u", "html_url": "h"},
                "labels": [],
                "draft": False,
                "additions": 100,
                "deletions": 20,
                "changed_files": 5,
                "mergeable": True,
                "merged": False,
                "commits": 3,
                "comments": 1,
                "review_comments": 2,
            },
        )
        pr = await client.get_pull_request("o", "r", 7)
        assert pr["additions"] == 100
        assert pr["changed_files"] == 5

    @pytest.mark.asyncio
    async def test_create_pull_request(self, client):
        self._patch_post(
            client,
            {
                "number": 10,
                "title": "New feature",
                "state": "open",
                "body": "",
                "html_url": "h",
                "created_at": "c",
                "updated_at": "u",
                "closed_at": None,
                "merged_at": None,
                "head": {"ref": "feat", "sha": "a", "label": "u:feat"},
                "base": {"ref": "main", "sha": "b", "label": "o:main"},
                "user": {"login": "u", "html_url": "h"},
                "labels": [],
                "draft": False,
                "additions": 0,
                "deletions": 0,
                "changed_files": 0,
                "mergeable": None,
                "merged": False,
                "commits": 1,
                "comments": 0,
                "review_comments": 0,
            },
        )
        pr = await client.create_pull_request("o", "r", "New feature", "feat", "main")
        assert pr["number"] == 10

    @pytest.mark.asyncio
    async def test_list_commits(self, client):
        self._patch_get(
            client,
            [
                {
                    "sha": "abc",
                    "commit": {"message": "Fix", "author": {}, "committer": {}},
                    "html_url": "h",
                    "author": {"login": "u", "html_url": "h"},
                    "committer": {"login": "u", "html_url": "h"},
                },
            ],
        )
        commits = await client.list_commits("o", "r")
        assert len(commits) == 1
        assert commits[0]["sha"] == "abc"

    @pytest.mark.asyncio
    async def test_get_file_contents_base64(self, client):
        content = base64.b64encode(b"print('hello')").decode()
        self._patch_get(
            client,
            {
                "name": "main.py",
                "path": "src/main.py",
                "sha": "abc",
                "size": 14,
                "type": "file",
                "encoding": "base64",
                "content": content,
                "html_url": "h",
            },
        )
        result = await client.get_file_contents("o", "r", "src/main.py")
        assert result["content"] == "print('hello')"
        assert result["encoding"] == "utf-8"
        assert result["type"] == "file"

    @pytest.mark.asyncio
    async def test_get_file_contents_directory(self, client):
        self._patch_get(
            client,
            [
                {"name": "main.py", "path": "src/main.py", "type": "file", "size": 100, "sha": "a"},
                {"name": "utils.py", "path": "src/utils.py", "type": "file", "size": 200, "sha": "b"},
            ],
        )
        result = await client.get_file_contents("o", "r", "src/")
        assert result["type"] == "directory"
        assert len(result["entries"]) == 2
        assert result["entries"][0]["name"] == "main.py"

    @pytest.mark.asyncio
    async def test_search_code(self, client):
        self._patch_get(
            client,
            {
                "total_count": 42,
                "incomplete_results": False,
                "items": [
                    {
                        "name": "main.py",
                        "path": "src/main.py",
                        "sha": "abc",
                        "html_url": "h",
                        "repository": {"full_name": "o/r", "html_url": "h"},
                    },
                ],
            },
        )
        result = await client.search_code("class HTTPClient language:python")
        assert result["total_count"] == 42
        assert len(result["items"]) == 1
        assert result["items"][0]["path"] == "src/main.py"
