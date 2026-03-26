"""Tests for structured error types."""

from src.errors import (
    AuthenticationError,
    ConnectorError,
    RateLimitError,
    TimeoutError,
    UpstreamError,
    ValidationError,
)


class TestConnectorError:
    def test_to_dict(self):
        err = ConnectorError("something broke", code="TEST_ERROR", retryable=True)
        d = err.to_dict()
        assert d["error"] is True
        assert d["code"] == "TEST_ERROR"
        assert d["message"] == "something broke"
        assert d["retryable"] is True

    def test_with_details(self):
        err = ConnectorError("bad", code="X", details={"field": "email"})
        assert err.to_dict()["details"]["field"] == "email"


class TestValidationError:
    def test_code(self):
        err = ValidationError("invalid email")
        assert err.code == "VALIDATION_ERROR"
        assert err.retryable is False


class TestAuthenticationError:
    def test_defaults(self):
        err = AuthenticationError()
        assert err.code == "AUTH_ERROR"
        assert err.message == "Authentication failed"
        assert err.retryable is False


class TestRateLimitError:
    def test_with_retry_after(self):
        err = RateLimitError(retry_after=30.0)
        assert err.code == "RATE_LIMIT"
        assert err.retryable is True
        assert err.details["retry_after"] == 30.0

    def test_without_retry_after(self):
        err = RateLimitError()
        assert err.details == {}


class TestUpstreamError:
    def test_with_status_code(self):
        err = UpstreamError("bad gateway", status_code=502, retryable=True)
        assert err.details["status_code"] == 502
        assert err.retryable is True


class TestTimeoutError:
    def test_defaults(self):
        err = TimeoutError()
        assert err.code == "TIMEOUT"
        assert err.retryable is True
