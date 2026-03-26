"""Pydantic models for PostgreSQL connector input validation."""

from pydantic import BaseModel, Field, field_validator


class QueryParams(BaseModel):
    """Parameters for read-only SELECT queries."""

    sql: str = Field(..., description="SQL SELECT query with $1, $2, ... parameter placeholders")
    params: list = Field(default_factory=list, description="Query parameters (positional)")
    timeout_seconds: float = Field(default=30.0, gt=0, le=300, description="Query timeout")
    max_rows: int = Field(default=1000, gt=0, le=10000, description="Maximum rows to return")

    @field_validator("sql")
    @classmethod
    def must_be_select(cls, v: str) -> str:
        normalized = v.strip().upper()
        if not normalized.startswith("SELECT") and not normalized.startswith("WITH"):
            raise ValueError("Read-only mode: only SELECT and WITH (CTE) queries are allowed")
        return v

    @field_validator("sql")
    @classmethod
    def no_semicolon_injection(cls, v: str) -> str:
        # Strip trailing semicolons but reject multiple statements
        stripped = v.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("Multiple statements are not allowed")
        return stripped


class ExecuteParams(BaseModel):
    """Parameters for write operations (INSERT/UPDATE/DELETE)."""

    sql: str = Field(..., description="SQL statement with $1, $2, ... parameter placeholders")
    params: list = Field(default_factory=list, description="Query parameters (positional)")
    timeout_seconds: float = Field(default=30.0, gt=0, le=300, description="Statement timeout")

    @field_validator("sql")
    @classmethod
    def must_be_write(cls, v: str) -> str:
        normalized = v.strip().upper()
        allowed_prefixes = ("INSERT", "UPDATE", "DELETE", "WITH")
        if not any(normalized.startswith(p) for p in allowed_prefixes):
            raise ValueError(
                "Execute mode: only INSERT, UPDATE, DELETE, and WITH (CTE) statements are allowed. "
                "Use 'query' tool for SELECT."
            )
        return v

    @field_validator("sql")
    @classmethod
    def no_semicolon_injection(cls, v: str) -> str:
        stripped = v.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("Multiple statements are not allowed")
        return stripped


class ListTablesParams(BaseModel):
    """Parameters for listing tables."""

    schema_name: str = Field(default="public", description="Schema to list tables from")


class DescribeTableParams(BaseModel):
    """Parameters for describing a table."""

    table_name: str = Field(..., description="Table name")
    schema_name: str = Field(default="public", description="Schema name")

    @field_validator("table_name", "schema_name")
    @classmethod
    def must_be_identifier(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError(f"Invalid identifier: {v!r}. Only alphanumeric and underscore allowed.")
        return v


class ExplainQueryParams(BaseModel):
    """Parameters for EXPLAIN ANALYZE."""

    sql: str = Field(..., description="SQL query to explain")
    params: list = Field(default_factory=list, description="Query parameters")
    analyze: bool = Field(default=False, description="Run EXPLAIN ANALYZE (actually executes query)")


class ListSchemasParams(BaseModel):
    """Parameters for listing schemas (no params needed but keeping consistent)."""

    pass


class ConnectionConfig(BaseModel):
    """Database connection configuration."""

    host: str = Field(default="localhost")
    port: int = Field(default=5432, gt=0, le=65535)
    database: str = Field(...)
    user: str = Field(...)
    password: str = Field(default="")
    min_pool_size: int = Field(default=2, ge=1, le=20)
    max_pool_size: int = Field(default=10, ge=1, le=100)
    ssl: bool = Field(default=False)
    read_only: bool = Field(default=True, description="If True, only SELECT queries allowed")
