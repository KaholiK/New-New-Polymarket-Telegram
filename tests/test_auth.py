"""Tests for Telegram auth — fail-closed on empty list."""

from __future__ import annotations

from apex.telegram.auth import is_authorized


def test_fail_closed_on_empty_list(monkeypatch):
    """CRITICAL: empty authorized list must REJECT everyone, not accept all."""
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "")
    assert is_authorized(12345) is False
    assert is_authorized(0) is False


def test_fail_closed_on_none(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "12345")
    assert is_authorized(None) is False


def test_authorized_user_passes(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "12345")
    assert is_authorized(12345) is True


def test_unauthorized_user_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "12345")
    assert is_authorized(99999) is False


def test_multiple_users(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "1, 2, 3")
    assert is_authorized(1) is True
    assert is_authorized(2) is True
    assert is_authorized(4) is False


def test_ignores_bad_tokens(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "1, not_a_number, 2")
    assert is_authorized(1) is True
    assert is_authorized(2) is True


def test_whitespace_only_rejects_all(monkeypatch):
    monkeypatch.setenv("TELEGRAM_AUTHORIZED_USERS", "   ")
    assert is_authorized(1) is False
