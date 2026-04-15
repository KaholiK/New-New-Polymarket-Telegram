"""User authorization — fail CLOSED on empty user list.

Bug-ledger regression: historical versions would accept all commands if the authorized
users list was empty. This implementation DOES NOT — an empty list rejects everyone.
"""

from __future__ import annotations

from apex.config import get_settings


def is_authorized(user_id: int | None) -> bool:
    """True iff user_id is in the authorized list AND the list is non-empty."""
    if user_id is None:
        return False
    s = get_settings()
    allowed = s.authorized_user_ids
    if not allowed:
        # Fail CLOSED — never accept anyone when the list is empty
        return False
    return int(user_id) in allowed
