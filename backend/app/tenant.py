"""Request-local tenant context used to enforce per-user data isolation."""
from contextvars import ContextVar, Token
from typing import Optional


_tenant_user_id: ContextVar[Optional[int]] = ContextVar("tenant_user_id", default=None)


def get_tenant_user_id() -> Optional[int]:
    return _tenant_user_id.get()


def set_tenant_user_id(user_id: Optional[int]) -> Token:
    return _tenant_user_id.set(user_id)


def reset_tenant_user_id(token: Token) -> None:
    _tenant_user_id.reset(token)
