"""Adapter that bridges TrustAPI to the Marketplace trust_provider interface.

The Marketplace expects a callable with signature:

    async def provider(server_id: str) -> float | None

This module provides ``make_trust_provider`` which wraps a TrustAPI instance
into that signature, returning the composite_score from the TrustScore or
None if the server is not registered in the trust system.
"""

from __future__ import annotations

from typing import Callable, Awaitable

from trust_src.api import ServerNotFoundError, TrustAPI


def make_trust_provider(
    trust_api: TrustAPI,
) -> Callable[[str], Awaitable[float | None]]:
    """Create a trust_provider callable for use with Marketplace.

    Args:
        trust_api: An initialised TrustAPI instance.

    Returns:
        An async callable(server_id) -> float | None that returns the
        composite trust score, or None when the server is unknown.
    """

    async def _provider(server_id: str) -> float | None:
        try:
            score = await trust_api.get_score(server_id)
            return score.composite_score
        except ServerNotFoundError:
            return None

    return _provider
