import hashlib
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lumen.auth import (
    Principal,
    get_principal,
    hash_password,
    issue_access_token,
    new_refresh_token,
    require_role,
    verify_password,
)
from lumen.db import get_session, set_tenant_context
from lumen.models import AuditEvent, Membership, RefreshToken, Role, Tenant, User
from lumen.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

router = APIRouter()


def _token_response(user_id: uuid.UUID, tenant_id: uuid.UUID, role: Role) -> TokenResponse:
    return TokenResponse(
        access_token=issue_access_token(user_id, tenant_id, role),
        refresh_token="",
        tenant_id=tenant_id,
        role=role.value,
    )


async def _persist_refresh(session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    raw, token_hash, expires = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id, tenant_id=tenant_id, token_hash=token_hash, expires_at=expires
        )
    )
    return raw


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    tenant_id = uuid.uuid4()
    slug_base = re.sub(r"[^a-z0-9]+", "-", body.tenant_name.lower()).strip("-")[:60] or "tenant"
    slug = f"{slug_base}-{uuid.uuid4().hex[:8]}"
    user = User(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    tenant = Tenant(id=tenant_id, name=body.tenant_name, slug=slug)
    session.add_all([tenant, user])
    await session.flush()
    await set_tenant_context(session, str(tenant_id))
    membership = Membership(tenant_id=tenant_id, user_id=user.id, role=Role.owner)
    session.add(membership)
    await session.flush()
    refresh = await _persist_refresh(session, user.id, tenant_id)
    session.add(AuditEvent(tenant_id=tenant_id, actor_id=user.id, action="auth.register"))
    await session.commit()
    response = _token_response(user.id, tenant_id, Role.owner)
    response.refresh_token = refresh
    return response


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == str(body.email).lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == body.tenant_slug))
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    await set_tenant_context(session, str(tenant.id))
    membership = await session.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant.id)
    )
    if membership is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    await set_tenant_context(session, str(membership.tenant_id))
    refresh = await _persist_refresh(session, user.id, membership.tenant_id)
    session.add(AuditEvent(tenant_id=membership.tenant_id, actor_id=user.id, action="auth.login"))
    await session.commit()
    response = _token_response(user.id, membership.tenant_id, membership.role)
    response.refresh_token = refresh
    return response


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh_tokens(body: RefreshRequest, session: AsyncSession = Depends(get_session)):
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    old = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )
    now = datetime.now(UTC)
    if old is None or old.revoked_at is not None or old.expires_at <= now:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    await set_tenant_context(session, str(old.tenant_id))
    membership = await session.scalar(
        select(Membership).where(
            Membership.user_id == old.user_id, Membership.tenant_id == old.tenant_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = await session.get(User, old.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    replacement = await _persist_refresh(session, user.id, membership.tenant_id)
    await session.flush()
    old.revoked_at = now
    session.add(AuditEvent(tenant_id=membership.tenant_id, actor_id=user.id, action="auth.refresh"))
    await session.commit()
    response = _token_response(user.id, membership.tenant_id, membership.role)
    response.refresh_token = replacement
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    token = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash, RefreshToken.user_id == principal.user_id
        )
    )
    if token is not None and token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                action="auth.logout",
            )
        )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me")
async def me(principal: Principal = Depends(get_principal)):
    return {"user_id": principal.user_id, "tenant_id": principal.tenant_id, "role": principal.role}


@router.get("/admin/ping")
async def admin_ping(
    principal: Principal = Depends(require_role(Role.owner, Role.admin)),
):
    return {"tenant_id": principal.tenant_id, "status": "ok"}
