import hashlib
import secrets
from datetime import UTC, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import delete, select

from forget_lah.db import AuthSession, Principal, utcnow

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate(factory, email: str, password: str, hours: int):
    with factory.begin() as db:
        user = db.scalar(select(Principal).where(Principal.email == email.strip().casefold()))
        try:
            valid = hasher.verify(user.password_hash if user else DUMMY_HASH, password)
        except VerificationError:
            valid = False
        if not valid or not user or not user.active:
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
        db.add(
            AuthSession(
                token_hash=digest(token),
                principal_id=user.id,
                csrf_hash=digest(csrf),
                expires_at=utcnow() + timedelta(hours=hours),
            )
        )
        return token, csrf


def session_principal(db, cookie: str | None):
    if not cookie or len(cookie) > 100:
        return None
    session = db.get(AuthSession, digest(cookie))
    if not session:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite-only test representation.
        expires = expires.replace(tzinfo=UTC)
    user = db.get(Principal, session.principal_id)
    if expires <= utcnow() or not user or not user.active:
        return None
    return user, session
