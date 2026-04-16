"""Database reconnection and is_healthy probe."""

from __future__ import annotations

import os
import tempfile

import pytest

from apex.storage.db import Database


@pytest.mark.asyncio
async def test_healthy_probe_true_after_connect() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    try:
        db = Database(path=path)
        await db.connect()
        assert db.healthy is True
        assert await db.is_healthy() is True
    finally:
        await db.close()
        os.remove(path)


@pytest.mark.asyncio
async def test_healthy_false_before_connect() -> None:
    db = Database(path="nonexistent.db")
    assert db.healthy is False
    # is_healthy must not crash on an unconnected handle — just returns False.
    assert await db.is_healthy() is False


@pytest.mark.asyncio
async def test_ensure_connected_recovers_after_close() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name
    try:
        db = Database(path=path)
        await db.connect()
        assert db.healthy
        await db.close()
        assert not db.healthy
        ok = await db.ensure_connected()
        assert ok is True
        assert db.healthy is True
    finally:
        await db.close()
        os.remove(path)


@pytest.mark.asyncio
async def test_connect_retries_and_surfaces_last_error() -> None:
    # Passing an invalid path (a directory, not a file) triggers an exception.
    # Use base_delay=0 so the test is fast.
    db = Database(path="/this/definitely/does/not/exist/apex.db")
    with pytest.raises(Exception):  # noqa: B017  # any exception proves retry-exhausted
        await db.connect(attempts=2, base_delay=0.0, max_delay=0.0)
    assert db.healthy is False
    assert db.last_error  # populated
