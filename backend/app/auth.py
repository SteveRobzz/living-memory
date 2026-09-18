"""Demo authentication.

user_id is read ONLY from a signed token. It is never accepted from a request
body or query string, which is what makes cross-user access impossible even
if a client tries to forge it.
"""
from __future__ import annotations
from fastapi import Depends, Header, HTTPException
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session
from .config import get_settings
from .db import get_db
from .models import User

_serializer = URLSafeSerializer(get_settings().secret_key, salt="lm-session")


def issue_token(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Missing token")
    try:
        payload = _serializer.loads(token)
    except BadSignature:
        raise HTTPException(401, "Invalid token")
    user = db.get(User, payload["user_id"])
    if user is None:
        raise HTTPException(401, "Unknown user")
    return user
