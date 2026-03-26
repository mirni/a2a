"""Pydantic models for GitHub connector input validation."""

from pydantic import BaseModel, Field, field_validator


class PaginationMixin(BaseModel):
    """Common pagination parameters."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    per_page: int = Field(default=30, ge=1, le=100, description="Results per page (max 100)")


class ListReposParams(PaginationMixin):
    """Parameters for listing repositories."""

    owner: str = Field(default="", description="User or organization. If empty, lists authenticated user's repos")
    type: str = Field(default="all", description="Filter: all, owner, public, private, member")
    sort: str = Field(default="updated", description="Sort by: created, updated, pushed, full_name")

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        allowed = {"all", "owner", "public", "private", "member"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v

    @field_validator("sort")
    @classmethod
    def valid_sort(cls, v: str) -> str:
        allowed = {"created", "updated", "pushed", "full_name"}
        if v not in allowed:
            raise ValueError(f"sort must be one of {allowed}")
        return v


class GetRepoParams(BaseModel):
    """Parameters for getting a single repository."""

    owner: str = Field(..., min_length=1, description="Repository owner (user or org)")
    repo: str = Field(..., min_length=1, description="Repository name")


class ListIssuesParams(PaginationMixin):
    """Parameters for listing issues."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    state: str = Field(default="open", description="Filter by state: open, closed, all")
    labels: str = Field(default="", description="Comma-separated list of label names")
    sort: str = Field(default="created", description="Sort by: created, updated, comments")
    direction: str = Field(default="desc", description="Sort direction: asc, desc")

    @field_validator("state")
    @classmethod
    def valid_state(cls, v: str) -> str:
        allowed = {"open", "closed", "all"}
        if v not in allowed:
            raise ValueError(f"state must be one of {allowed}")
        return v

    @field_validator("direction")
    @classmethod
    def valid_direction(cls, v: str) -> str:
        allowed = {"asc", "desc"}
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}")
        return v


class CreateIssueParams(BaseModel):
    """Parameters for creating an issue."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    title: str = Field(..., min_length=1, max_length=256, description="Issue title")
    body: str = Field(default="", description="Issue body (Markdown)")
    labels: list[str] = Field(default_factory=list, description="Label names to apply")
    assignees: list[str] = Field(default_factory=list, description="Usernames to assign")


class ListPullRequestsParams(PaginationMixin):
    """Parameters for listing pull requests."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    state: str = Field(default="open", description="Filter by state: open, closed, all")
    sort: str = Field(default="created", description="Sort by: created, updated, popularity, long-running")
    direction: str = Field(default="desc", description="Sort direction: asc, desc")
    head: str = Field(default="", description="Filter by head branch (user:branch or branch)")
    base: str = Field(default="", description="Filter by base branch")

    @field_validator("state")
    @classmethod
    def valid_state(cls, v: str) -> str:
        allowed = {"open", "closed", "all"}
        if v not in allowed:
            raise ValueError(f"state must be one of {allowed}")
        return v

    @field_validator("direction")
    @classmethod
    def valid_direction(cls, v: str) -> str:
        allowed = {"asc", "desc"}
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}")
        return v


class GetPullRequestParams(BaseModel):
    """Parameters for getting a single pull request."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    pull_number: int = Field(..., ge=1, description="Pull request number")


class CreatePullRequestParams(BaseModel):
    """Parameters for creating a pull request."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    title: str = Field(..., min_length=1, max_length=256, description="PR title")
    body: str = Field(default="", description="PR body (Markdown)")
    head: str = Field(..., min_length=1, description="Branch containing changes (user:branch or branch)")
    base: str = Field(..., min_length=1, description="Branch to merge into")
    draft: bool = Field(default=False, description="Create as draft PR")


class ListCommitsParams(PaginationMixin):
    """Parameters for listing commits."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    sha: str = Field(default="", description="SHA or branch name to start from")
    path: str = Field(default="", description="Only commits containing this file path")
    since: str = Field(default="", description="ISO 8601 date — only commits after this date")
    until: str = Field(default="", description="ISO 8601 date — only commits before this date")


class GetFileContentsParams(BaseModel):
    """Parameters for getting file contents."""

    owner: str = Field(..., min_length=1, description="Repository owner")
    repo: str = Field(..., min_length=1, description="Repository name")
    path: str = Field(..., min_length=1, description="File path within the repository")
    ref: str = Field(default="", description="Branch, tag, or commit SHA (defaults to default branch)")


class SearchCodeParams(BaseModel):
    """Parameters for searching code."""

    query: str = Field(..., min_length=1, description="Search query (GitHub code search syntax)")
    per_page: int = Field(default=30, ge=1, le=100, description="Results per page (max 100)")
    page: int = Field(default=1, ge=1, description="Page number")
