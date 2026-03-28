"""Messaging and negotiation tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext


async def _send_message(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    msg = await ctx.messaging_api.send_message(
        sender=params["sender"],
        recipient=params["recipient"],
        message_type=params["message_type"],
        subject=params.get("subject", ""),
        body=params.get("body", ""),
        metadata=params.get("metadata"),
        thread_id=params.get("thread_id"),
    )
    return {
        "id": msg.id,
        "sender": msg.sender,
        "recipient": msg.recipient,
        "message_type": msg.message_type.value,
        "thread_id": msg.thread_id,
        "created_at": msg.created_at,
    }


async def _get_messages(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    messages = await ctx.messaging_api.get_messages(
        agent_id=params["agent_id"],
        thread_id=params.get("thread_id"),
        limit=params.get("limit", 50),
    )
    return {"messages": messages}


async def _negotiate_price(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.messaging_api.negotiate_price(
        initiator=params["initiator"],
        responder=params["responder"],
        amount=params["amount"],
        service_id=params.get("service_id", ""),
        expires_hours=params.get("expires_hours", 24),
    )
    return result
