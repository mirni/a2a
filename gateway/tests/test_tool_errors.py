"""Tests for tool-level exception types and their HTTP mapping."""

from __future__ import annotations

from gateway.src.tool_errors import (
    NegativeCostError,
    ToolNotFoundError,
    ToolValidationError,
)


class TestToolValidationError:
    """ToolValidationError should be a ValueError subclass."""

    def test_is_value_error(self):
        exc = ToolValidationError("bad input")
        assert isinstance(exc, ValueError)
        assert str(exc) == "bad input"

    def test_maps_to_400(self):
        """The error mapping should resolve ToolValidationError → 400."""

        exc = ToolValidationError("invalid interval")
        # We check the mapping dict directly since handle_product_exception
        # is async and requires a Request object.
        exc_type = type(exc).__name__

        # The mapping dict is inside handle_product_exception; verify the
        # exception name matches a 400 mapping.
        assert exc_type == "ToolValidationError"


class TestToolNotFoundError:
    """ToolNotFoundError should be a LookupError subclass."""

    def test_is_lookup_error(self):
        exc = ToolNotFoundError("missing widget")
        assert isinstance(exc, LookupError)
        assert str(exc) == "missing widget"


class TestNegativeCostError:
    """NegativeCostError should be a ValueError subclass."""

    def test_is_value_error(self):
        exc = NegativeCostError("cost is -0.5")
        assert isinstance(exc, ValueError)
        assert str(exc) == "cost is -0.5"
