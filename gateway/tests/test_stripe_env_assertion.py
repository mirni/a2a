"""Tests for C1: Stripe key environment assertion.

Sandbox environments must NOT use live Stripe keys, and production
environments must NOT use test Stripe keys. Violation raises RuntimeError
at boot time to prevent accidental real charges in sandbox.
"""

from __future__ import annotations

import pytest

from gateway.src.stripe_env_check import assert_stripe_key_matches_env


class TestStripeKeyMatchesEnv:
    """Boot-time assertion that Stripe key matches A2A_ENV."""

    def test_sandbox_with_test_key_ok(self):
        """sandbox + sk_test_* key is allowed."""
        assert_stripe_key_matches_env(env="sandbox", stripe_key="sk_test_abc123")

    def test_sandbox_with_live_key_raises(self):
        """sandbox + sk_live_* key MUST raise RuntimeError."""
        with pytest.raises(RuntimeError, match="sandbox.*sk_live"):
            assert_stripe_key_matches_env(env="sandbox", stripe_key="sk_live_abc123")

    def test_prod_with_live_key_ok(self):
        """prod + sk_live_* key is allowed."""
        assert_stripe_key_matches_env(env="prod", stripe_key="sk_live_abc123")

    def test_production_with_live_key_ok(self):
        """production + sk_live_* key is allowed (alias)."""
        assert_stripe_key_matches_env(env="production", stripe_key="sk_live_abc123")

    def test_prod_with_test_key_raises(self):
        """prod + sk_test_* key MUST raise RuntimeError."""
        with pytest.raises(RuntimeError, match="prod.*sk_test"):
            assert_stripe_key_matches_env(env="prod", stripe_key="sk_test_abc123")

    def test_staging_with_test_key_ok(self):
        """staging + sk_test_* key is allowed."""
        assert_stripe_key_matches_env(env="staging", stripe_key="sk_test_abc123")

    def test_staging_with_live_key_raises(self):
        """staging + sk_live_* key MUST raise RuntimeError."""
        with pytest.raises(RuntimeError, match="staging.*sk_live"):
            assert_stripe_key_matches_env(env="staging", stripe_key="sk_live_abc123")

    def test_empty_key_noop(self):
        """Empty key is allowed (Stripe disabled)."""
        assert_stripe_key_matches_env(env="sandbox", stripe_key="")
        assert_stripe_key_matches_env(env="prod", stripe_key="")

    def test_unset_env_noop(self):
        """No A2A_ENV set is allowed (dev/local)."""
        assert_stripe_key_matches_env(env="", stripe_key="sk_live_abc123")
        assert_stripe_key_matches_env(env=None, stripe_key="sk_live_abc123")

    def test_dev_with_any_key_ok(self):
        """dev env is unrestricted."""
        assert_stripe_key_matches_env(env="dev", stripe_key="sk_test_abc")
        assert_stripe_key_matches_env(env="dev", stripe_key="sk_live_abc")

    def test_test_env_with_any_key_ok(self):
        """test env is unrestricted (for CI/unit tests)."""
        assert_stripe_key_matches_env(env="test", stripe_key="sk_test_abc")
        assert_stripe_key_matches_env(env="test", stripe_key="sk_live_abc")
