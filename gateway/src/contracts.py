"""Protocol contracts for product interfaces.

The gateway depends on these Protocols rather than concrete implementations,
enabling easier testing (mocks) and future swappability of backends.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IdentityService(Protocol):
    """Contract for the identity/attestation service."""

    async def register_agent(
        self, agent_id: str, public_key: str | None = None
    ) -> Any: ...

    async def get_identity(self, agent_id: str) -> Any: ...

    async def verify_agent(
        self, agent_id: str, message: bytes, signature_hex: str
    ) -> bool: ...

    async def submit_metrics(
        self, agent_id: str, metrics: dict, data_source: str = "self_reported"
    ) -> Any: ...

    async def get_verified_claims(self, agent_id: str) -> list: ...

    async def get_reputation(self, agent_id: str) -> Any: ...

    async def search_agents_by_metrics(
        self,
        metric_name: str,
        min_value: float | None = None,
        max_value: float | None = None,
        limit: int = 50,
    ) -> list: ...

    async def build_claim_chain(self, agent_id: str) -> dict: ...


@runtime_checkable
class MessagingService(Protocol):
    """Contract for the messaging service."""

    async def send_message(
        self,
        sender: str,
        recipient: str,
        message_type: str,
        subject: str = "",
        body: str = "",
        metadata: dict | None = None,
        thread_id: str | None = None,
    ) -> Any: ...

    async def get_messages(
        self, agent_id: str, thread_id: str | None = None, limit: int = 50
    ) -> list: ...

    async def negotiate_price(
        self,
        initiator: str,
        responder: str,
        amount: float,
        service_id: str = "",
        expires_hours: int = 24,
    ) -> dict: ...


@runtime_checkable
class PaymentService(Protocol):
    """Contract for the payment engine."""

    async def create_intent(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        idempotency_key: str | None = None,
        metadata: dict | None = None,
    ) -> Any: ...

    async def capture(self, intent_id: str) -> Any: ...

    async def void(self, intent_id: str) -> Any: ...

    async def get_intent(self, intent_id: str) -> Any: ...

    async def create_escrow(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        timeout_hours: float | None = None,
        metadata: dict | None = None,
    ) -> Any: ...

    async def get_escrow(self, escrow_id: str) -> Any: ...

    async def release_escrow(self, escrow_id: str) -> Any: ...

    async def refund_escrow(self, escrow_id: str) -> Any: ...

    async def create_subscription(
        self,
        payer: str,
        payee: str,
        amount: float,
        interval: str,
        description: str = "",
        metadata: dict | None = None,
    ) -> Any: ...

    async def get_subscription(self, sub_id: str) -> Any: ...

    async def cancel_subscription(
        self, sub_id: str, cancelled_by: str | None = None
    ) -> Any: ...

    async def reactivate_subscription(self, sub_id: str) -> Any: ...

    async def get_payment_history(
        self, agent_id: str, limit: int = 100, offset: int = 0
    ) -> list: ...

    async def partial_capture(
        self, intent_id: str, amount: float
    ) -> tuple: ...


@runtime_checkable
class MarketplaceService(Protocol):
    """Contract for the marketplace."""

    async def search(self, params: Any = None, **kwargs: Any) -> list: ...

    async def best_match(
        self,
        query: str,
        budget: float | None = None,
        min_trust_score: float | None = None,
        prefer: Any = None,
        limit: int = 5,
    ) -> list: ...

    async def get_service(self, service_id: str) -> Any: ...

    async def register_service(self, spec: Any) -> Any: ...

    async def update_service(self, service_id: str, **kwargs: Any) -> Any: ...

    async def deactivate_service(self, service_id: str, **kwargs: Any) -> Any: ...


@runtime_checkable
class TrustService(Protocol):
    """Contract for the trust scoring service."""

    async def get_score(
        self,
        server_id: str,
        window: Any = None,
        recompute: bool = False,
    ) -> Any: ...

    async def search_servers(
        self,
        name_contains: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list: ...

    async def delete_server(self, server_id: str) -> None: ...

    async def update_server(
        self, server_id: str, name: str | None = None, url: str | None = None
    ) -> Any: ...


@runtime_checkable
class StorageService(Protocol):
    """Minimal contract for any storage backend."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...
