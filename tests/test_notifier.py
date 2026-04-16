"""Admin notifier throttling + severity + recovery bypass."""

from __future__ import annotations

from typing import Any

import pytest

from apex.core.notify import AdminNotifier, configure_notifier, get_notifier


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


@pytest.mark.asyncio
async def test_notifier_sends_once_per_throttle_window() -> None:
    n = AdminNotifier(admin_chat_id=1, throttle_seconds=999)
    bot = _FakeBot()
    n.attach_bot(bot)

    sent1 = await n.warning("odds down", key="odds")
    sent2 = await n.warning("odds down", key="odds")
    assert sent1 is True
    assert sent2 is False
    assert len(bot.messages) == 1


@pytest.mark.asyncio
async def test_notifier_different_keys_not_throttled() -> None:
    n = AdminNotifier(admin_chat_id=1, throttle_seconds=999)
    bot = _FakeBot()
    n.attach_bot(bot)

    assert await n.warning("a", key="alpha") is True
    assert await n.warning("b", key="beta") is True
    assert len(bot.messages) == 2


@pytest.mark.asyncio
async def test_recovery_bypasses_throttle() -> None:
    n = AdminNotifier(admin_chat_id=1, throttle_seconds=999)
    bot = _FakeBot()
    n.attach_bot(bot)

    await n.critical("db down", key="db")
    # Recovery fires even if a critical was sent moments ago.
    assert await n.recovery("db up", key="db") is True
    assert len(bot.messages) == 2
    # And another recovery right after still fires (no throttle on recovery).
    assert await n.recovery("still up", key="db") is True


@pytest.mark.asyncio
async def test_notifier_no_bot_does_not_error() -> None:
    n = AdminNotifier(admin_chat_id=1)
    # Without attach_bot, notify still "succeeds" at the throttle layer but
    # returns False since no transport delivered it.
    ok = await n.warning("hello", key="k")
    assert ok is False


@pytest.mark.asyncio
async def test_configure_notifier_replaces_singleton() -> None:
    n = configure_notifier(admin_chat_id=42, throttle_seconds=1)
    assert get_notifier() is n
    assert n.admin_chat_id == 42
