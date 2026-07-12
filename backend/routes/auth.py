"""Authentication routes.

Customers authenticate with email + password. Admin authenticates with the
username/password from .env and receives a role=admin JWT. These are entirely
separate credential paths.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import ADMIN_PASSWORD, ADMIN_USERNAME
from database import get_db
from models import User
from schemas import AdminLoginIn, LoginIn, SignupIn, TokenOut
from security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _profile_complete(user: User) -> bool:
    return bool(user.full_name and user.plan_id and user.member_id)


@router.post("/signup", response_model=TokenOut)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(subject=user.id, role="customer")
    return TokenOut(access_token=token, role="customer", profile_complete=False)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(subject=user.id, role="customer")
    return TokenOut(
        access_token=token, role="customer", profile_complete=_profile_complete(user)
    )


@router.post("/admin/login", response_model=TokenOut)
def admin_login(body: AdminLoginIn):
    if body.username != ADMIN_USERNAME or body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    token = create_token(subject="admin", role="admin")
    return TokenOut(access_token=token, role="admin", profile_complete=True)
