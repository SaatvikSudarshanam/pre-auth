"""Twilio webhook callbacks (public-facing endpoints)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from services.twilio_voice import _twiml_cache

router = APIRouter(prefix="/api/twilio", tags=["twilio"])


@router.get("/twiml/{call_id}")
def get_twiml(call_id: str):
    """Twilio calls this endpoint to get the TwiML for a call.
    
    This solves trial account limitation: instead of sending TwiML inline
    (which trial accounts don't support), we provide a URL for Twilio to fetch it.
    """
    twiml = _twiml_cache.get(call_id)
    if not twiml:
        raise HTTPException(status_code=404, detail="Call TwiML not found")
    
    # Delete after returning (one-time use)
    del _twiml_cache[call_id]
    
    return PlainTextResponse(content=twiml, media_type="application/xml")

