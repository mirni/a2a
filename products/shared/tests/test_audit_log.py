"""Tests for audit logging."""

from src.audit_log import AuditEntry, _sanitize_params, log_operation, set_request_id


class TestSanitizeParams:
    def test_redacts_api_key(self):
        result = _sanitize_params({"api_key": "sk-1234", "name": "test"})
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_redacts_password(self):
        result = _sanitize_params({"password": "hunter2"})
        assert result["password"] == "[REDACTED]"

    def test_redacts_nested(self):
        result = _sanitize_params({"config": {"secret": "abc", "host": "localhost"}})
        assert result["config"]["secret"] == "[REDACTED]"
        assert result["config"]["host"] == "localhost"

    def test_case_insensitive_keys(self):
        result = _sanitize_params({"API_KEY": "sk-1234"})
        assert result["API_KEY"] == "[REDACTED]"

    def test_empty_params(self):
        assert _sanitize_params({}) == {}

    def test_preserves_safe_values(self):
        params = {"customer_id": "cus_123", "amount": 1000, "currency": "usd"}
        result = _sanitize_params(params)
        assert result == params


class TestAuditEntry:
    def test_to_dict_minimal(self):
        entry = AuditEntry(operation="get_balance", connector="stripe")
        d = entry.to_dict()
        assert d["op"] == "get_balance"
        assert d["connector"] == "stripe"
        assert "ts" in d

    def test_to_dict_with_error(self):
        entry = AuditEntry(
            operation="create_payment",
            connector="stripe",
            error="insufficient_funds",
            duration_ms=123.456,
        )
        d = entry.to_dict()
        assert d["error"] == "insufficient_funds"
        assert d["duration_ms"] == 123.46

    def test_request_id_correlation(self):
        set_request_id("req-abc-123")
        entry = AuditEntry(operation="query", connector="postgres")
        d = entry.to_dict()
        assert d["request_id"] == "req-abc-123"
        set_request_id(None)


class TestLogOperation:
    def test_returns_audit_entry(self):
        entry = log_operation(
            operation="list_charges",
            connector="stripe",
            params={"limit": 10},
            result_summary="returned 10 charges",
            duration_ms=45.2,
        )
        assert isinstance(entry, AuditEntry)
        assert entry.operation == "list_charges"

    def test_sanitizes_params(self):
        entry = log_operation(
            operation="create_customer",
            connector="stripe",
            params={"email": "test@test.com", "api_key": "sk-secret"},
        )
        assert entry.params["api_key"] == "[REDACTED]"
        assert entry.params["email"] == "test@test.com"


class TestSanitizeParamsEdgeCases:
    """Tests for improved sanitization: substring matching, mixed case, deep nesting."""

    def test_redacts_camelcase_apikey(self):
        result = _sanitize_params({"ApiKey": "sk-1234"})
        assert result["ApiKey"] == "[REDACTED]"

    def test_redacts_prefixed_key(self):
        result = _sanitize_params({"stripe_secret_key": "sk-1234"})
        assert result["stripe_secret_key"] == "[REDACTED]"

    def test_redacts_suffixed_key(self):
        result = _sanitize_params({"api_token_v2": "tok-xyz"})
        assert result["api_token_v2"] == "[REDACTED]"

    def test_redacts_deeply_nested(self):
        params = {
            "config": {
                "auth": {
                    "api_key": "sk-deep",
                    "host": "localhost",
                }
            }
        }
        result = _sanitize_params(params)
        assert result["config"]["auth"]["api_key"] == "[REDACTED]"
        assert result["config"]["auth"]["host"] == "localhost"

    def test_redacts_mixed_case_password(self):
        result = _sanitize_params({"DB_PASSWORD": "hunter2"})
        assert result["DB_PASSWORD"] == "[REDACTED]"

    def test_preserves_keys_without_sensitive_substring(self):
        result = _sanitize_params({"customer_id": "cus_123", "amount": 100})
        assert result["customer_id"] == "cus_123"
        assert result["amount"] == 100

    def test_redacts_authorization_header(self):
        result = _sanitize_params({"Authorization": "Bearer tok123"})
        assert result["Authorization"] == "[REDACTED]"

    def test_handles_list_values(self):
        """Lists should pass through without error."""
        result = _sanitize_params({"tags": ["a", "b"], "secret": "x"})
        assert result["tags"] == ["a", "b"]
        assert result["secret"] == "[REDACTED]"
