"""Admin notifier — throttled Telegram alerts for operational events.

Exposes a process-wide singleton ``AdminNotifier`` used by background jobs, the
engine, and data ingestors to surface critical failures and recoveries without
spamming the admin chat.

Throttle strategy: at most one alert per (severity, key) every
``throttle_seconds`` (default 30 min). Keys let the caller deduplicate by
subject, e.g. ``key="db"``, ``key="odds_api"``, ``key="coingecko"``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from apex.utils.logger import get_logger

logger = get_logger(__name__)

SEVERITY_EMOJI = {
    "critical": "🚨",
    "warning": "⚠️",
    "info": "ℹ️",
    "recovery": "✅",
}


class AdminNotifier:
    """Throttled Telegram alerter for operational events.

    The notifier is transport-agnostic; it hands messages to the configured
    Telegram application via the attached ``bot`` reference. If no bot is
    attached, alerts are logged and dropped (keeps the engine testable).
    """

    def __init__(
        self,
        admin_chat_id: int | None = None,
        throttle_seconds: float = 30 * 60,
    ) -> None:
        self.admin_chat_id = admin_chat_id
        self.throttle_seconds = throttle_seconds
        self._last_sent: dict[tuple[str, str], float] = {}
        self._bot: Any = None
        self._lock = asyncio.Lock()

    def attach_bot(self, bot: Any) -> None:
        """Attach a python-telegram-bot Bot instance (from Application.bot)."""
        self._bot = bot

    def _should_send(self, severity: str, key: str) -> bool:
        # Recoveries always bypass throttle so a DB recovery after 10 min still fires.
        if severity == "recovery":
            return True
        now = time.monotonic()
        last = self._last_sent.get((severity, key))
        if last is None:
            return True
        return (now - last) >= self.throttle_seconds

    def _mark_sent(self, severity: str, key: str) -> None:
        self._last_sent[(severity, key)] = time.monotonic()

    async def notify(
        self,
        message: str,
        severity: str = "warning",
        key: str | None = None,
    ) -> bool:
        """Send an admin alert if not throttled. Returns True if actually sent.

        ``key`` is used for throttling — successive calls with the same
        (severity, key) within ``throttle_seconds`` are coalesced. Omitting it
        means every call fires (use sparingly).
        """
        sev = severity.lower()
        throttle_key = key or f"msg:{hash(message) & 0xffff}"
        async with self._lock:
            if not self._should_send(sev, throttle_key):
                logger.debug(
                    "admin notify throttled: sev=%s key=%s msg=%s",
                    sev, throttle_key, message[:80],
                )
                return False
            self._mark_sent(sev, throttle_key)

        emoji = SEVERITY_EMOJI.get(sev, "ℹ️")
        body = f"{emoji} <b>APEX {sev.upper()}</b>\n{message}"
        logger.info("admin notify: sev=%s key=%s msg=%s", sev, throttle_key, message[:160])

        if self._bot is None or self.admin_chat_id is None:
            # No transport configured; logging already happened above.
            return False
        try:
            await self._bot.send_message(
                chat_id=self.admin_chat_id,
                text=body,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("admin notify transport failed: %s", exc)
            return False

    async def critical(self, message: str, key: str | None = None) -> bool:
        return await self.notify(message, severity="critical", key=key)

    async def warning(self, message: str, key: str | None = None) -> bool:
        return await self.notify(message, severity="warning", key=key)

    async def info(self, message: str, key: str | None = None) -> bool:
        return await self.notify(message, severity="info", key=key)

    async def recovery(self, message: str, key: str | None = None) -> bool:
        return await self.notify(message, severity="recovery", key=key)


_global_notifier: AdminNotifier | None = None


def get_notifier() -> AdminNotifier:
    """Return the process-wide AdminNotifier (lazy-initialised)."""
    global _global_notifier
    if _global_notifier is None:
        _global_notifier = AdminNotifier()
    return _global_notifier


def configure_notifier(admin_chat_id: int | None, throttle_seconds: float = 30 * 60) -> AdminNotifier:
    """Install a fresh notifier with the given config. Returns the new instance."""
    global _global_notifier
    _global_notifier = AdminNotifier(
        admin_chat_id=admin_chat_id,
        throttle_seconds=throttle_seconds,
    )
    return _global_notifier
