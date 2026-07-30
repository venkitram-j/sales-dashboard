"""Authentication service.

There is no self-service sign-up: accounts are provisioned/managed via
scripts/manage_users.py. This service handles authentication, the
'remember me' persistent session tokens, and the data operations that
manage_users.py needs.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_session import UserSession
from app.utils.security import generate_session_token, hash_password, hash_session_token, verify_password

logger = logging.getLogger(__name__)


class UserAlreadyExistsError(ValueError):
    pass


class UserNotFoundError(ValueError):
    pass


class AuthService:
    def __init__(self, session: Session):
        self.session = session

    # -- login -------------------------------------------------------------
    def authenticate(self, username: str, password: str) -> User | None:
        """Returns the User on success, None on any failure (bad username,
        bad password, or inactive account). Never reveals which reason."""
        username = (username or "").strip()
        if not username or not password:
            return None

        user = self.session.scalar(select(User).where(User.username == username))
        if user is None or not user.is_active:
            logger.info("Login failed for username=%s (not found or inactive)", username)
            return None

        if not verify_password(password, user.password_hash):
            logger.info("Login failed for username=%s (bad password)", username)
            return None

        user.last_login_at = dt.datetime.now(dt.timezone.utc)
        self.session.flush()
        logger.info("Login succeeded for username=%s", username)
        return user

    # -- 'remember me' persistent sessions -----------------------------------
    def create_session(self, user: User, ttl_days: int) -> str:
        """Creates a persistent session for `user` and returns the raw
        token to store in the browser's cookie. Only its hash is persisted."""
        raw_token, token_hash = generate_session_token()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=ttl_days)
        self.session.add(
            UserSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
        )
        self.session.flush()
        logger.info("Created remember-me session for username=%s (ttl_days=%d)", user.username, ttl_days)
        return raw_token

    def validate_session(self, raw_token: str) -> User | None:
        """Looks up a session by its (hashed) token. Returns the User if the
        token is valid, unexpired, and the account is still active; expired
        or orphaned sessions are cleaned up as they're encountered."""
        if not raw_token:
            return None

        token_hash = hash_session_token(raw_token)
        record = self.session.scalar(
            select(UserSession).where(UserSession.token_hash == token_hash)
        )
        if record is None:
            return None

        now = dt.datetime.now(dt.timezone.utc)
        if record.expires_at < now:
            self.session.delete(record)
            self.session.flush()
            return None

        user = self.session.get(User, record.user_id)
        if user is None or not user.is_active:
            self.session.delete(record)
            self.session.flush()
            return None

        record.last_used_at = now
        self.session.flush()
        return user

    def revoke_session(self, raw_token: str) -> None:
        """Deletes one session by its raw token (used on logout)."""
        if not raw_token:
            return
        token_hash = hash_session_token(raw_token)
        self.session.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
        self.session.flush()

    def revoke_all_sessions_for_user(self, user_id: int) -> None:
        """Deletes every persistent session for a user (used when their
        password changes or their account is deactivated, so an old
        'remember me' cookie can't keep working)."""
        self.session.execute(delete(UserSession).where(UserSession.user_id == user_id))
        self.session.flush()

    def purge_expired_sessions(self) -> int:
        """Deletes every expired session row. Returns the count removed.
        Safe to run periodically (see scripts/manage_users.py purge-sessions)."""
        now = dt.datetime.now(dt.timezone.utc)
        result = self.session.execute(delete(UserSession).where(UserSession.expires_at < now))
        self.session.flush()
        return result.rowcount or 0

    # -- user management (used by scripts/manage_users.py) -------------------
    def get_by_username(self, username: str) -> User | None:
        return self.session.scalar(select(User).where(User.username == username))

    def create_user(self, username: str, password: str, is_active: bool = True) -> User:
        username = username.strip()
        if not username:
            raise ValueError("username must not be empty")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        if self.get_by_username(username) is not None:
            raise UserAlreadyExistsError(f"user '{username}' already exists")

        user = User(username=username, password_hash=hash_password(password), is_active=is_active)
        self.session.add(user)
        self.session.flush()
        logger.info("Created user username=%s", username)
        return user

    def set_password(self, username: str, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("password must be at least 8 characters")
        user = self.get_by_username(username)
        if user is None:
            raise UserNotFoundError(f"user '{username}' not found")
        user.password_hash = hash_password(new_password)
        self.session.flush()
        self.revoke_all_sessions_for_user(user.id)
        logger.info("Password updated for username=%s (existing sessions revoked)", username)

    def set_active(self, username: str, is_active: bool) -> None:
        user = self.get_by_username(username)
        if user is None:
            raise UserNotFoundError(f"user '{username}' not found")
        user.is_active = is_active
        self.session.flush()
        if not is_active:
            self.revoke_all_sessions_for_user(user.id)
        logger.info("Set is_active=%s for username=%s", is_active, username)

    def list_users(self) -> list[User]:
        return list(self.session.scalars(select(User).order_by(User.username)).all())
