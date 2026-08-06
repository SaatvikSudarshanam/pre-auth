"""Decision phone calls delegated to an n8n workflow.

Instead of talking to Twilio directly, the backend POSTs the decision payload
to an n8n Webhook node; the workflow's Twilio node places the call. Keeps the
Twilio credentials in n8n and lets the call script / channel be changed
without a redeploy.

Falls back to services.twilio_voice when N8N_WEBHOOK_URL is unset.
"""
import httpx

from config import (
    N8N_WEBHOOK_URL,
    N8N_WEBHOOK_TOKEN,
    N8N_TIMEOUT_SECONDS,
    TWILIO_PHONE_NUMBER,
    TWILIO_TEST_PHONE_NUMBER,
    TWILIO_TRIAL_MODE,
)
from services.twilio_voice import ACTION_LABELS, build_call_script, normalize_phone, _E164


def is_n8n_configured() -> bool:
    return bool(N8N_WEBHOOK_URL)


def trigger_decision_call(
    *,
    to_phone: str,
    customer_name: str | None,
    claim_id: int,
    action: str,
    message: str,
    claim_type: str = "",
) -> dict:
    """POST the decision to the n8n webhook so it can place the call.

    Returns the parsed n8n response (or {} when the workflow replies with an
    empty body, which is what "Respond: Immediately" does).

    Raises:
        ValueError: phone number is not usable.
        httpx.HTTPError: n8n unreachable or returned a non-2xx status.
    """
    if not is_n8n_configured():
        raise RuntimeError("n8n webhook is not configured")

    if TWILIO_TRIAL_MODE:
        # A Twilio trial can only dial Verified Caller IDs, so every decision
        # call goes to the one verified number regardless of who the customer
        # is. The real destination still rides along as `intended_to`.
        normalized = normalize_phone(TWILIO_TEST_PHONE_NUMBER)
    else:
        normalized = normalize_phone(to_phone)
        if not _E164.match(normalized):
            raise ValueError(
                f"Invalid phone number: {to_phone!r}. Use E.164 format, e.g. +919876543210"
            )

    payload = {
        "to": normalized,
        "intended_to": normalize_phone(to_phone) or to_phone,
        "trial_mode": TWILIO_TRIAL_MODE,
        "from": TWILIO_PHONE_NUMBER,
        "claim_id": claim_id,
        "action": action,
        "decision": ACTION_LABELS.get(action, action),
        "customer_name": customer_name or "there",
        "claim_type": claim_type,
        "customer_message": message,
        # Pre-rendered so the n8n Twilio node can just use {{ $json.body.message }}.
        "message": build_call_script(
            customer_name=customer_name,
            claim_id=claim_id,
            action=action,
            message=message,
            claim_type=claim_type,
        ),
    }

    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {N8N_WEBHOOK_TOKEN}"

    resp = httpx.post(
        N8N_WEBHOOK_URL,
        json=payload,
        headers=headers,
        timeout=N8N_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()

    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {"result": body}
