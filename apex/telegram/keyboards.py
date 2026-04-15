"""Inline keyboard builders for confirmations + navigation."""

from __future__ import annotations

from typing import Any

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
except BaseException:  # pragma: no cover  # noqa: BLE001
    # Native cryptography deps can raise pyo3 PanicException (a BaseException) on
    # import in some sandboxes. Degrade gracefully so command-only code paths import.
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore


# Callback-data parsing uses rsplit with maxsplit because Polymarket condition IDs
# are hex strings that may contain ":". Use "|" as separator to avoid this entirely,
# and rsplit with limited splits just in case.
SEP = "|"


def confirm_keyboard(action: str, payload: str = "") -> Any:
    if InlineKeyboardButton is None:
        return None
    # YES / NO buttons with structured callback
    yes_cb = f"confirm{SEP}{action}{SEP}{payload}"
    no_cb = f"cancel{SEP}{action}{SEP}{payload}"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ YES", callback_data=yes_cb),
                InlineKeyboardButton("❌ NO", callback_data=no_cb),
            ]
        ]
    )


def parse_callback(cb_data: str) -> tuple[str, str, str]:
    """Parse callback_data. Uses rsplit-style logic to handle hex IDs safely.

    Our separator is '|' so condition-ID ':' won't collide. But we use rsplit with
    maxsplit=2 as a belt-and-suspenders in case a payload contains our separator.
    """
    if not cb_data:
        return "", "", ""
    parts = cb_data.split(SEP, 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]
