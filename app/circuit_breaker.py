"""Circuit breaker logic for step limits and loop detection."""

from __future__ import annotations

import asyncio
import logging
import httpx
from typing import Optional

from . import metrics
from .audit import audit
from .config import settings
from .db import get_db
from .exceptions import (
    CyclicPayloadLoop,
    RepeatedPayloadLoop,
    StepLimitExceeded,
)
from .state import session_store
from .state_backends import SessionSnapshot

logger = logging.getLogger("agenttrafficcop.breaker")


# ---------------------------------------------------------------------------
# Webhook Helpers (Feature 3)
# ---------------------------------------------------------------------------

def _get_webhook_url(fingerprint: str) -> Optional[str]:
    """Find the webhook URL associated with the API key making the request."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT u.webhook_url FROM users u "
                "JOIN api_keys k ON u.id = k.user_id "
                "WHERE k.fingerprint = ? AND k.revoked_at IS NULL",
                (fingerprint,)
            )
            row = cursor.fetchone()
            if row:
                return row["webhook_url"]
    except Exception as e:
        logger.error("webhook_lookup_failed error=%s", e)
    return None


async def _send_webhook_async(url: str, message: str) -> None:
    """Fire-and-forget HTTP POST to Slack or Discord."""
    try:
        # We send both 'text' (Slack) and 'content' (Discord) so it works for both.
        payload = {"text": message, "content": message}
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=5.0)
        logger.info("webhook_fired url=%s", url[:30])
    except Exception as e:
        logger.warning("webhook_failed url=%s error=%s", url, e)


def _fire_webhook(fingerprint: str, message: str) -> None:
    """Helper to run the webhook asynchronously without blocking the API."""
    url = _get_webhook_url(fingerprint)
    if url:
        try:
            # FastAPI runs in an event loop. create_task makes it non-blocking.
            asyncio.create_task(_send_webhook_async(url, message))
        except RuntimeError:
            # Fails gracefully if called outside an event loop (e.g., in tests)
            pass


# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------

def evaluate(
    snapshot: SessionSnapshot,
    payload_hash: str,
    *,
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    api_key_fingerprint: Optional[str] = None,
) -> SessionSnapshot:
    """Record the payload hash and enforce all governance thresholds."""

    # --- Check 1: hard step cap ------------------------------------------
    if snapshot.step >= settings.max_steps:
        logger.warning(
            "step_limit_exceeded session_id=%s step=%d max=%d",
            snapshot.session_id,
            snapshot.step,
            settings.max_steps,
        )
        try:
            metrics.inc_trip("step_limit")
        except Exception:
            pass
        try:
            audit.log_trip(
                session_id=snapshot.session_id,
                error_code="STEP_LIMIT_EXCEEDED",
                step=snapshot.step,
                sender=sender,
                recipient=recipient,
                diagnostics={
                    "step": snapshot.step,
                    "max_steps": settings.max_steps,
                },
                api_key_fingerprint=api_key_fingerprint,
            )
        except Exception:
            pass
            
        if api_key_fingerprint:
            msg = (
                f"🛑 **AgentTrafficCop Alert**\n"
                f"Your agent hit the **Step Limit** in session `{snapshot.session_id}` at step {snapshot.step}.\n"
                f"This runaway session was halted to save your budget."
            )
            _fire_webhook(api_key_fingerprint, msg)

        raise StepLimitExceeded(
            message=(
                f"Session '{snapshot.session_id}' exceeded the maximum of "
                f"{settings.max_steps} steps."
            ),
            session_id=snapshot.session_id,
            diagnostics={
                "step": snapshot.step,
                "max_steps": settings.max_steps,
                "recent_hashes": snapshot.hashes,
            },
        )

    new_hashes = snapshot.hashes + [payload_hash]
    temp_snapshot = SessionSnapshot(
        session_id=snapshot.session_id,
        step=snapshot.step + 1,
        hashes=new_hashes,
        created_at=snapshot.created_at,
        last_seen=snapshot.last_seen,
    )

    # --- Check 2: consecutive identical hashes ---------------------------
    repeats = temp_snapshot.consecutive_repeats()
    if repeats >= settings.max_repeated_hashes:
        logger.warning(
            "repeated_payload_loop session_id=%s step=%d repeats=%d",
            temp_snapshot.session_id,
            temp_snapshot.step,
            repeats,
        )
        try:
            metrics.inc_trip("repeated_payload")
        except Exception:
            pass
        try:
            audit.log_trip(
                session_id=temp_snapshot.session_id,
                error_code="REPEATED_PAYLOAD_LOOP",
                step=temp_snapshot.step,
                sender=sender,
                recipient=recipient,
                diagnostics={
                    "repeated_hash": payload_hash,
                    "consecutive_repeats": repeats,
                    "max_repeated_hashes": settings.max_repeated_hashes,
                },
                api_key_fingerprint=api_key_fingerprint,
            )
        except Exception:
            pass
            
        if api_key_fingerprint:
            msg = (
                f"🛑 **AgentTrafficCop Alert**\n"
                f"Your agent hit a **Repeated Payload Loop** in session `{temp_snapshot.session_id}` at step {temp_snapshot.step}.\n"
                f"This loop was halted to save your budget."
            )
            _fire_webhook(api_key_fingerprint, msg)

        raise RepeatedPayloadLoop(
            message=(
                f"Session '{temp_snapshot.session_id}' produced identical "
                f"payload hash {repeats} times consecutively."
            ),
            session_id=temp_snapshot.session_id,
            diagnostics={
                "step": temp_snapshot.step,
                "repeated_hash": payload_hash,
                "consecutive_repeats": repeats,
                "max_repeated_hashes": settings.max_repeated_hashes,
            },
        )

    # --- Check 3: cyclic (ping-pong) patterns ----------------------------
    for cycle_len in range(2, settings.max_cycle_length + 1):
        repeats = temp_snapshot.cycle_repeats(cycle_len)
        if repeats >= settings.max_cycle_repeats:
            logger.warning(
                "cyclic_payload_loop session_id=%s step=%d cycle_len=%d repeats=%d",
                temp_snapshot.session_id,
                temp_snapshot.step,
                cycle_len,
                repeats,
            )
            try:
                metrics.inc_trip("cyclic_payload")
            except Exception:
                pass
            try:
                audit.log_trip(
                    session_id=temp_snapshot.session_id,
                    error_code="CYCLIC_PAYLOAD_LOOP",
                    step=temp_snapshot.step,
                    sender=sender,
                    recipient=recipient,
                    diagnostics={
                        "cycle_length": cycle_len,
                        "cycle_repeats": repeats,
                        "max_cycle_repeats": settings.max_cycle_repeats,
                    },
                    api_key_fingerprint=api_key_fingerprint,
                )
            except Exception:
                pass
                
            if api_key_fingerprint:
                msg = (
                    f"🛑 **AgentTrafficCop Alert**\n"
                    f"Your agent hit a **Cyclic Payload Loop** (length {cycle_len}) in session `{temp_snapshot.session_id}` at step {temp_snapshot.step}.\n"
                    f"This loop was halted to save your budget."
                )
                _fire_webhook(api_key_fingerprint, msg)

            raise CyclicPayloadLoop(
                message=(
                    f"Session '{temp_snapshot.session_id}' entered a "
                    f"repeating cycle of length {cycle_len} ({repeats} times)."
                ),
                session_id=temp_snapshot.session_id,
                diagnostics={
                    "step": temp_snapshot.step,
                    "cycle_length": cycle_len,
                    "cycle_repeats": repeats,
                    "max_cycle_repeats": settings.max_cycle_repeats,
                    "recent_hashes": temp_snapshot.hashes,
                },
            )

    new_snapshot = session_store.record(snapshot.session_id, payload_hash)
    return new_snapshot