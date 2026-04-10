"""High-level verifier helpers for the A2A Formal Gatekeeper.

Exposes a one-liner that submits a JSON policy, polls the job to
terminal state, and returns a :class:`ProofResult`. Lower-level access
is available via :class:`A2AClient` methods (``submit_verification``,
``get_verification_status``, ``verify_proof``, ``get_proof``).

Example::

    from a2a_client import A2AClient
    from a2a_client.verifier import prove_policy

    async with A2AClient(api_key="a2a_pro_...") as client:
        result = await prove_policy(
            client,
            "my-agent",
            {
                "name": "balance_positive",
                "variables": [{"name": "balance", "type": "int", "value": 5}],
                "assertions": [{"op": ">", "args": ["balance", 0]}],
            },
        )
        print(result.satisfied, result.proof_hash)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import A2AClient

# Structural alias for the JSON policy dict. A proper TypedDict would
# require Python 3.11+; dict[str, Any] keeps the SDK compatible with 3.10.
JsonPolicySpec = dict[str, Any]


@dataclass
class ProofResult:
    """Outcome of a :func:`prove_policy` call.

    Attributes:
        satisfied: ``True`` if Z3 found a model (SAT); ``False`` if the
            assertions are contradictory (UNSAT) or the solver errored.
        job_id: The underlying verification job identifier.
        status: Final job status (``completed``, ``failed``, ``timeout``).
        proof_hash: SHA3-256 hash of the proof artifact (empty on failure).
        counterexample: For UNSAT, the solver's reason; for SAT, the model;
            ``None`` when neither is available.
        raw: The raw gatekeeper ``get_verification_status`` response dict.
    """

    satisfied: bool
    job_id: str
    status: str
    proof_hash: str = ""
    counterexample: str | None = None
    raw: dict[str, Any] | None = None


async def prove_policy(
    client: A2AClient,
    agent_id: str,
    policy: JsonPolicySpec,
    *,
    timeout_seconds: int = 300,
    poll_interval: float = 0.5,
    poll_max_wait: float = 60.0,
    idempotency_key: str | None = None,
) -> ProofResult:
    """Submit a JSON policy, wait for the job to finish, return the result.

    This is a convenience wrapper over
    :meth:`A2AClient.submit_verification` +
    :meth:`A2AClient.get_verification_status`. It polls every
    ``poll_interval`` seconds and gives up after ``poll_max_wait`` seconds
    of wall-clock, raising :class:`TimeoutError`.

    ``policy`` is a dict matching the gatekeeper ``json_policy`` schema
    (see ``docs/infra/GATEKEEPER_JSON_POLICY.md``). The dict is
    serialised to JSON and submitted as a single property with
    ``language="json_policy"``.

    Args:
        client: A constructed :class:`A2AClient` with a pro-tier API key.
        agent_id: The agent this proof is being submitted for.
        policy: The JSON policy spec.
        timeout_seconds: Per-proof solver timeout passed to the gatekeeper.
        poll_interval: How often to re-check the job status, in seconds.
        poll_max_wait: Max wall-clock seconds to poll before raising.
        idempotency_key: Optional dedupe key; repeated calls return the
            same job. Defaults to ``None`` (one submission per call).

    Returns:
        :class:`ProofResult` with ``satisfied`` set based on the final
        verifier outcome.

    Raises:
        TimeoutError: If the job does not reach a terminal state within
            ``poll_max_wait`` seconds.
    """
    expression = json.dumps(policy)
    properties = [
        {
            "name": policy.get("name", "policy"),
            "language": "json_policy",
            "expression": expression,
        }
    ]

    submit_resp = await client.submit_verification(
        agent_id=agent_id,
        properties=properties,
        timeout_seconds=timeout_seconds,
        idempotency_key=idempotency_key,
    )
    job_id = submit_resp.job_id

    # The submit endpoint does not include the ``result`` field, so we
    # always fetch the job status to get the full terminal payload
    # (result, proof_artifact_id, etc.). The mock verifier used in CI
    # runs synchronously, so the first status call is usually terminal.
    terminal = {"completed", "failed", "timeout", "cancelled"}
    loop = asyncio.get_event_loop()
    deadline = loop.time() + poll_max_wait
    while True:
        status_resp = await client.get_verification_status(job_id)
        if status_resp.status in terminal:
            return _build_result(job_id, status_resp.to_raw_dict())
        if loop.time() >= deadline:
            raise TimeoutError(
                f"prove_policy timed out after {poll_max_wait}s (job {job_id} still {status_resp.status})"
            )
        await asyncio.sleep(poll_interval)


def _build_result(job_id: str, raw: dict[str, Any]) -> ProofResult:
    """Fold the raw gatekeeper response into a :class:`ProofResult`."""
    status = raw.get("status", "unknown")
    result_str = raw.get("result") or ""
    # Gatekeeper's "satisfied" result corresponds to SAT (model exists);
    # "violated" corresponds to UNSAT. Anything else (error/unknown) is
    # treated as not-satisfied so callers have a binary contract.
    satisfied = result_str == "satisfied"
    property_results = raw.get("property_results") or []
    counterexample: str | None = None
    if property_results and isinstance(property_results, list):
        first = property_results[0]
        if isinstance(first, dict):
            counterexample = first.get("model") or first.get("reason")
    return ProofResult(
        satisfied=satisfied,
        job_id=job_id,
        status=status,
        proof_hash=raw.get("proof_hash", "") or "",
        counterexample=counterexample,
        raw=raw,
    )
