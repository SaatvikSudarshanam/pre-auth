"""Google OAuth sign-in for customers.

Flow:
  1. Frontend calls GET /api/auth/google/login-url and redirects the browser to
     the returned Google consent URL.
  2. Google redirects back to GET /rbac/oauth/google/callback (this exact path is
     registered in the Google Cloud console).
  3. We exchange the code, fetch the user's profile, upsert the customer, mint a
     customer JWT, and redirect the browser to the frontend with the token.
"""
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from config import (
    FRONTEND_URL,
    GOOGLE_AUTH_URI,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GOOGLE_TOKEN_URI,
    GOOGLE_USERINFO_URI,
)
from database import SessionLocal
from models import User
from security import create_token, decode_token

router = APIRouter(tags=["oauth"])


def _configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


@router.get("/api/auth/google/login-url")
def google_login_url():
    if not _configured():
        raise HTTPException(status_code=501, detail="Google sign-in is not configured")
    state = create_token(subject="oauth", role="oauth_state")
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return {"url": f"{GOOGLE_AUTH_URI}?{urlencode(params)}"}


def _redirect_to_frontend(fragment: str) -> RedirectResponse:
    return RedirectResponse(url=f"{FRONTEND_URL}/app/oauth#{fragment}")


@router.get("/rbac/oauth/google/callback")
def google_callback(request: Request):
    params = request.query_params
    if params.get("error"):
        return _redirect_to_frontend(f"error={params.get('error')}")
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return _redirect_to_frontend("error=missing_code")

    # CSRF: state must be a token we issued.
    try:
        payload = decode_token(state)
        if payload.get("role") != "oauth_state":
            raise ValueError("bad state role")
    except Exception:
        return _redirect_to_frontend("error=bad_state")

    if not _configured():
        return _redirect_to_frontend("error=not_configured")

    # Exchange the authorization code for tokens.
    try:
        with httpx.Client(timeout=30) as client:
            token_resp = client.post(
                GOOGLE_TOKEN_URI,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code >= 400:
                return _redirect_to_frontend("error=token_exchange_failed")
            access_token = token_resp.json().get("access_token")
            if not access_token:
                return _redirect_to_frontend("error=no_access_token")

            info_resp = client.get(
                GOOGLE_USERINFO_URI,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_resp.status_code >= 400:
                return _redirect_to_frontend("error=userinfo_failed")
            info = info_resp.json()
    except httpx.HTTPError:
        return _redirect_to_frontend("error=network")

    sub = info.get("sub")
    email = (info.get("email") or "").lower()
    if not sub or not email:
        return _redirect_to_frontend("error=no_identity")

    # Upsert the customer (own DB session — not the request-scoped dependency).
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.google_sub == sub).first()
        if not user:
            user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, auth_provider="google", google_sub=sub)
            db.add(user)
        # Link / refresh Google profile fields.
        user.google_sub = sub
        if user.auth_provider != "google" and not user.password_hash:
            user.auth_provider = "google"
        if not user.full_name and info.get("name"):
            user.full_name = info.get("name")
        if info.get("picture"):
            user.avatar_url = info.get("picture")
        db.commit()
        db.refresh(user)
        token = create_token(subject=user.id, role="customer")
        complete = 1 if (user.full_name and user.plan_id and user.member_id) else 0
    finally:
        db.close()

    return _redirect_to_frontend(f"token={token}&complete={complete}")
