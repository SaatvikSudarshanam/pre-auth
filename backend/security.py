"""Password hashing and JWT issuing/verification.

Customer tokens carry role="customer" + sub=user_id.
Admin tokens carry role="admin" + sub="admin". Route guards check the role,
so a customer token can never reach an /api/admin/* handler.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from database import get_db
from models import User

# pbkdf2_sha256 is pure-Python — no native bcrypt build needed on Windows.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# tokenUrl is nominal; the frontend sends the header directly.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_token(subject: str, role: str, extra: Optional[dict] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )


def _require_token(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return decode_token(token)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = _require_token(token)
    if payload.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customer access required")
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def get_current_admin(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """Guard for /api/admin/* — rejects any non-admin (including customer) token."""
    payload = _require_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload
