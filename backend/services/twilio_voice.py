"""Outbound voice notifications via Twilio (admin-side only)."""
import html
import re
import uuid

from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER

ACTION_LABELS = {
    "approved": "Approved",
    "rejected": "Rejected",
    "requested_info": "More Information Needed",
}

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")

# In-memory TwiML cache for trial accounts (short-lived, one-time use)
_twiml_cache = {}


def is_twilio_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER)


def normalize_phone(phone: str) -> str:
    """Best-effort E.164 normalization for India (+91) and generic + prefixes."""
    raw = (phone or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return raw.replace(" ", "").replace("-", "")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if len(digits) >= 11:
        return f"+{digits}"
    return ""


def _twiml_say(text: str) -> str:
    safe = html.escape(text, quote=False)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="Polly.Joanna">{safe}</Say></Response>'


def store_twiml_for_callback(call_id: str, twiml: str):
    """Store TwiML for Twilio to fetch via callback URL."""
    _twiml_cache[call_id] = twiml


def build_call_script(
    *,
    customer_name: str | None,
    claim_id: int,
    action: str,
    message: str,
    claim_type: str = "",
) -> str:
    """The spoken script for a decision call.

    Shared by the direct-Twilio path and the n8n path so both channels say
    exactly the same thing.
    """
    decision = ACTION_LABELS.get(action, action)
    name = customer_name or "there"
    claim_bit = f" for {claim_type}" if claim_type else ""
    return (
        f"Hello {name}. This is Pre Auth I Q with an update on your "
        f"pre-authorization claim number {claim_id}{claim_bit}. "
        f"The decision is {decision}. "
        f"{message[:400]}. "
        f"Thank you. Goodbye."
    )


def place_decision_call(
    *,
    to_phone: str,
    customer_name: str | None,
    claim_id: int,
    action: str,
    message: str,
    claim_type: str = "",
    callback_url: str = "",
) -> str:
    """Place a decision call via Twilio.
    
    For trial accounts: requires callback_url (e.g. https://your-domain/api/twilio/twiml/{call_id}).
    For paid accounts: can use inline TwiML.
    
    Args:
        to_phone: Destination phone in E.164 format
        customer_name: Customer's full name (for greeting)
        claim_id: Claim ID (included in the message)
        action: Decision action (approved/rejected/requested_info)
        message: Custom message from admin
        claim_type: Type of claim (for context in message)
        callback_url: Base URL for TwiML callback (e.g. https://ngrok.io/api/twilio/twiml)
                     Required for trial accounts. If provided, uses callback URL instead of inline TwiML.
    
    Returns:
        Call SID from Twilio
    """
    if not is_twilio_configured():
        raise RuntimeError("Twilio is not configured")

    normalized = normalize_phone(to_phone)
    if not _E164.match(normalized):
        raise ValueError(f"Invalid phone number: {to_phone!r}. Use E.164 format, e.g. +919876543210")

    script = build_call_script(
        customer_name=customer_name,
        claim_id=claim_id,
        action=action,
        message=message,
        claim_type=claim_type,
    )

    from twilio.rest import Client
    
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    
    if callback_url:
        # Trial account: use callback URL (Twilio fetches TwiML from your backend)
        call_id = str(uuid.uuid4())
        twiml = _twiml_say(script)
        store_twiml_for_callback(call_id, twiml)
        
        callback_twiml_url = f"{callback_url}/{call_id}"
        call = client.calls.create(
            to=normalized,
            from_=TWILIO_PHONE_NUMBER,
            url=callback_twiml_url,
        )
    else:
        # Paid account: use inline TwiML (default, backward compatible)
        call = client.calls.create(
            to=normalized,
            from_=TWILIO_PHONE_NUMBER,
            twiml=_twiml_say(script),
        )
    
    return call.sid


