"""Tests for GitHub connector input validation models."""

import pytest
from pydantic import ValidationError as PydanticValidationError

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


class TestListReposParams:
    def test_defaults(self):
        p = ListReposParams()
        assert p.owner == ""
        assert p.type == "all"
        assert p.sort == "updated"
        assert p.page == 1
        assert p.per_page == 30

    def test_custom_values(self):
        p = ListReposParams(owner="octocat", type="public", sort="created", page=2, per_page=50)
        assert p.owner == "octocat"
        assert p.type == "public"
        assert p.sort == "created"
        assert p.page == 2
        assert p.per_page == 50

    def test_invalid_type(self):
        with pytest.raises(PydanticValidationError, match="type must be one of"):
            ListReposParams(type="invalid")

    def test_invalid_sort(self):
        with pytest.raises(PydanticValidationError, match="sort must be one of"):
            ListReposParams(sort="stars")

    def test_page_must_be_positive(self):
        with pytest.raises(PydanticValidationError):
            ListReposParams(page=0)

    def test_per_page_max_100(self):
        with pytest.raises(PydanticValidationError):
            ListReposParams(per_page=101)


class TestGetRepoParams:
    def test_valid(self):
        p = GetRepoParams(owner="octocat", repo="hello-world")
        assert p.owner == "octocat"
        assert p.repo == "hello-world"

    def test_owner_required(self):
        with pytest.raises(PydanticValidationError):
            GetRepoParams(owner="", repo="hello-world")

    def test_repo_required(self):
        with pytest.raises(PydanticValidationError):
            GetRepoParams(owner="octocat", repo="")


class TestListIssuesParams:
    def test_defaults(self):
        p = ListIssuesParams(owner="octocat", repo="hello-world")
        assert p.state == "open"
        assert p.labels == ""
        assert p.sort == "created"
        assert p.direction == "desc"

    def test_invalid_state(self):
        with pytest.raises(PydanticValidationError, match="state must be one of"):
            ListIssuesParams(owner="o", repo="r", state="invalid")

    def test_invalid_direction(self):
        with pytest.raises(PydanticValidationError, match="direction must be one of"):
            ListIssuesParams(owner="o", repo="r", direction="sideways")

    def test_with_labels(self):
        p = ListIssuesParams(owner="o", repo="r", labels="bug,enhancement")
        assert p.labels == "bug,enhancement"


class TestCreateIssueParams:
    def test_valid(self):
        p = CreateIssueParams(owner="o", repo="r", title="Bug report")
        assert p.title == "Bug report"
        assert p.body == ""
        assert p.labels == []
        assert p.assignees == []

    def test_with_all_fields(self):
        p = CreateIssueParams(
            owner="o", repo="r", title="Bug",
            body="Details here", labels=["bug"], assignees=["user1"],
        )
        assert p.body == "Details here"
        assert p.labels == ["bug"]
        assert p.assignees == ["user1"]

    def test_title_required(self):
        with pytest.raises(PydanticValidationError):
            CreateIssueParams(owner="o", repo="r", title="")

    def test_title_max_length(self):
        with pytest.raises(PydanticValidationError):
            CreateIssueParams(owner="o", repo="r", title="x" * 257)


class TestListPullRequestsParams:
    def test_defaults(self):
        p = ListPullRequestsParams(owner="o", repo="r")
        assert p.state == "open"
        assert p.head == ""
        assert p.base == ""

    def test_invalid_state(self):
        with pytest.raises(PydanticValidationError, match="state must be one of"):
            ListPullRequestsParams(owner="o", repo="r", state="merged")

    def test_invalid_direction(self):
        with pytest.raises(PydanticValidationError, match="direction must be one of"):
            ListPullRequestsParams(owner="o", repo="r", direction="up")

    def test_with_filters(self):
        p = ListPullRequestsParams(
            owner="o", repo="r", head="user:feature", base="main",
        )
        assert p.head == "user:feature"
        assert p.base == "main"


class TestGetPullRequestParams:
    def test_valid(self):
        p = GetPullRequestParams(owner="o", repo="r", pull_number=42)
        assert p.pull_number == 42

    def test_pull_number_positive(self):
        with pytest.raises(PydanticValidationError):
            GetPullRequestParams(owner="o", repo="r", pull_number=0)


class TestCreatePullRequestParams:
    def test_valid(self):
        p = CreatePullRequestParams(
            owner="o", repo="r", title="New feature",
            head="feature-branch", base="main",
        )
        assert p.title == "New feature"
        assert p.draft is False

    def test_draft_pr(self):
        p = CreatePullRequestParams(
            owner="o", repo="r", title="WIP",
            head="wip-branch", base="main", draft=True,
        )
        assert p.draft is True

    def test_head_required(self):
        with pytest.raises(PydanticValidationError):
            CreatePullRequestParams(
                owner="o", repo="r", title="T", head="", base="main",
            )

    def test_base_required(self):
        with pytest.raises(PydanticValidationError):
            CreatePullRequestParams(
                owner="o", repo="r", title="T", head="branch", base="",
            )


class TestListCommitsParams:
    def test_defaults(self):
        p = ListCommitsParams(owner="o", repo="r")
        assert p.sha == ""
        assert p.path == ""
        assert p.since == ""
        assert p.until == ""

    def test_with_filters(self):
        p = ListCommitsParams(
            owner="o", repo="r", sha="main", path="src/",
            since="2026-01-01", until="2026-03-01",
        )
        assert p.sha == "main"
        assert p.path == "src/"


class TestGetFileContentsParams:
    def test_valid(self):
        p = GetFileContentsParams(owner="o", repo="r", path="README.md")
        assert p.ref == ""

    def test_with_ref(self):
        p = GetFileContentsParams(owner="o", repo="r", path="src/main.py", ref="v1.0")
        assert p.ref == "v1.0"

    def test_path_required(self):
        with pytest.raises(PydanticValidationError):
            GetFileContentsParams(owner="o", repo="r", path="")


class TestSearchCodeParams:
    def test_valid(self):
        p = SearchCodeParams(query="class HTTPClient language:python")
        assert p.page == 1
        assert p.per_page == 30

    def test_query_required(self):
        with pytest.raises(PydanticValidationError):
            SearchCodeParams(query="")

    def test_per_page_max(self):
        with pytest.raises(PydanticValidationError):
            SearchCodeParams(query="test", per_page=101)
