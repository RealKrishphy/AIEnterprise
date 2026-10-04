import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lumen.config import get_settings
from lumen.db import get_session, set_tenant_context
from lumen.models import Membership, Role, User

password_hasher = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
settings = get_settings()


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be between 12 and 256 characters")
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str | None) -> bool:
    if encoded is None:
        return False
    try:
        return password_hasher.verify(encoded, password)
    except VerifyMismatchError:
        return False


def issue_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: Role) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "tid": str(tenant_id),
            "role": role.value,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "jti": secrets.token_urlsafe(16),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def new_refresh_token() -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    return raw, token_hash, expires


async def get_principal(
    token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_session)
) -> Principal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = uuid.UUID(claims["sub"])
        tenant_id = uuid.UUID(claims["tid"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise unauthorized from None

    await set_tenant_context(session, str(tenant_id))
    row = (
        await session.execute(
            select(Membership, User.is_active)
            .join(User, User.id == Membership.user_id)
            .where(Membership.user_id == user_id, Membership.tenant_id == tenant_id)
        )
    ).one_or_none()
    if row is None or not row[1]:
        raise unauthorized
    return Principal(user_id=user_id, tenant_id=tenant_id, role=row[0].role)


def require_role(*roles: Role):
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return principal

    return dependency
