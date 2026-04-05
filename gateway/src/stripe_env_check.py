"""Boot-time assertion: Stripe keys must match the A2A_ENV environment.

Audit C1: prevent accidental use of sk_live_* keys in sandbox/staging, or
sk_test_* keys in production. Raise RuntimeError at boot so the service
refuses to start in a dangerous configuration.
"""

from __future__ import annotations

# Environments that must use sk_test_* keys only.
_TEST_ONLY_ENVS = frozenset({"sandbox", "staging"})

# Environments that must use sk_live_* keys only.
_LIVE_ONLY_ENVS = frozenset({"prod", "production"})


def assert_stripe_key_matches_env(env: str | None, stripe_key: str) -> None:
    """Raise RuntimeError if Stripe key prefix does not match A2A_ENV.

    Rules:
      * sandbox / staging MUST use sk_test_* keys
      * prod / production MUST use sk_live_* keys
      * empty key or unset env → no-op (Stripe disabled / dev mode)
      * dev / test / other envs → no-op (unrestricted)

    Args:
        env: A2A_ENV value (e.g. "sandbox", "prod"). None or "" skips check.
        stripe_key: Raw Stripe API key. Empty string skips check.

    Raises:
        RuntimeError: If env requires a specific key prefix and key does not match.
    """
    if not env or not stripe_key:
        return

    env_normalized = env.strip().lower()

    if env_normalized in _TEST_ONLY_ENVS and stripe_key.startswith("sk_live_"):
        raise RuntimeError(
            f"REFUSING TO BOOT: A2A_ENV={env_normalized!r} must use sk_test_* Stripe key, "
            f"but STRIPE_API_KEY starts with 'sk_live_'. Using a live key in {env_normalized} "
            "would cause real charges. Set STRIPE_API_KEY to a sk_test_* key, or unset it."
        )

    if env_normalized in _LIVE_ONLY_ENVS and stripe_key.startswith("sk_test_"):
        raise RuntimeError(
            f"REFUSING TO BOOT: A2A_ENV={env_normalized!r} must use sk_live_* Stripe key, "
            f"but STRIPE_API_KEY starts with 'sk_test_'. Test keys in production would "
            "silently drop real payments. Set STRIPE_API_KEY to a sk_live_* key, or unset it."
        )
