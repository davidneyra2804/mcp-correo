"""Confirmación de un solo uso y tope diario de envíos. Viven en memoria del proceso."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from mail.errors import MailError


@dataclass
class PendingAction:
    kind: str
    account: str
    public: dict[str, Any]
    secret: dict[str, Any]
    expires_at: float


class ConfirmationStore:
    """Token ligado a cuenta, tipo de operación y payload. Caduca y no se reutiliza."""

    def __init__(self, ttl_seconds: float = 600, clock: Callable[[], float] | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock or time.time
        self._pending: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    def issue(self, kind: str, account: str, public: dict[str, Any], secret: dict[str, Any]) -> str:
        now = self._clock()
        with self._lock:
            self._purge(now)
            token = secrets.token_urlsafe(24)
            while token in self._pending:
                token = secrets.token_urlsafe(24)
            self._pending[token] = PendingAction(
                kind=kind,
                account=account,
                public=public,
                secret=secret,
                expires_at=now + self.ttl_seconds,
            )
            return token

    def peek(self, token: str, kind: str, account: str) -> PendingAction:
        with self._lock:
            return self._lookup(token, kind, account, pop=False)

    def consume(self, token: str, kind: str, account: str) -> PendingAction:
        with self._lock:
            return self._lookup(token, kind, account, pop=True)

    def _lookup(self, token: str, kind: str, account: str, *, pop: bool) -> PendingAction:
        if not isinstance(token, str) or not token.strip():
            raise MailError(
                "Falta confirm_token. Prepara la operación y espera "
                "la orden explícita de quien opera el asistente."
            )
        pending = self._pending.get(token)
        if pending is None:
            raise MailError("confirm_token desconocido o ya usado.")
        if pending.expires_at <= self._clock():
            self._pending.pop(token, None)
            raise MailError("confirm_token caducado. Vuelve a preparar la operación.")
        if pending.kind != kind or pending.account != account:
            raise MailError("confirm_token no corresponde a esta cuenta o a esta operación.")
        if pop:
            self._pending.pop(token, None)
        return pending

    def _purge(self, now: float) -> None:
        expired = [key for key, item in self._pending.items() if item.expires_at <= now]
        for key in expired:
            del self._pending[key]


class SendQuota:
    """Contador diario por cuenta, en UTC. Solo cuenta un envío que el SMTP aceptó."""

    def __init__(self, daily_cap: int, clock: Callable[[], float] | None = None) -> None:
        self.daily_cap = daily_cap
        self._clock = clock or time.time
        self._counts: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def remaining(self, account: str) -> int:
        with self._lock:
            return max(0, self.daily_cap - self._count(account))

    def reserve(self, account: str) -> None:
        with self._lock:
            if self._count(account) >= self.daily_cap:
                raise MailError(f"Tope diario de envíos alcanzado ({self.daily_cap}).")
            key = self._key(account)
            self._counts[key] = self._counts.get(key, 0) + 1

    def release(self, account: str) -> None:
        with self._lock:
            key = self._key(account)
            current = self._counts.get(key, 0)
            if current > 0:
                self._counts[key] = current - 1

    def _count(self, account: str) -> int:
        return self._counts.get(self._key(account), 0)

    def _key(self, account: str) -> tuple[str, str]:
        day = datetime.fromtimestamp(self._clock(), UTC).date().isoformat()
        return account, day
