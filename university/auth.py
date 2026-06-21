"""Plaintext auth gate, mirroring the mijnspel-creator approach.

Passwords are stored and compared as plaintext on purpose: this is a
single-user personal tool, not a multi-tenant service. The one hard rule the
design borrows from mijnspel-creator is the alphanumeric guard — usernames and
passwords must be ``[A-Za-z0-9]+`` and that is checked BEFORE any DB query, so
a malformed credential can never reach SQL.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
import datetime as _dt
from typing import Optional

from .db import utcnow

TOKEN_TTL_DAYS = 30


def is_alphanum(value: object) -> bool:
    """True only for a non-empty string of ASCII letters/digits."""
    return isinstance(value, str) and len(value) > 0 and value.isascii() and value.isalnum()


def add_user(conn: sqlite3.Connection, username: str, password: str) -> int:
    """Insert a user (plaintext password). Alphanumeric-guarded first."""
    if not is_alphanum(username):
        raise ValueError("username must be non-empty and alphanumeric")
    if not is_alphanum(password):
        raise ValueError("password must be non-empty and alphanumeric")
    cur = conn.execute(
        "INSERT INTO users (username, password, created_at) VALUES (?,?,?)",
        (username, password, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def verify_credentials(conn: sqlite3.Connection, username: str, password: str) -> Optional[int]:
    """Return the user id on a correct credential, else None.

    The alphanumeric guard runs BEFORE touching the database.
    """
    if not is_alphanum(username) or not is_alphanum(password):
        return None
    row = conn.execute(
        "SELECT id, password FROM users WHERE username=?", (username,)
    ).fetchone()
    if row is None:
        return None
    stored = row["password"] or ""
    # Constant-time byte compare of the stored plaintext.
    if hmac.compare_digest(stored.encode("utf-8"), password.encode("utf-8")):
        return int(row["id"])
    return None


def issue_token(conn: sqlite3.Connection, user_id: int) -> str:
    """Mint a 30-day token for the user and persist it."""
    token = secrets.token_hex(16)
    now = _dt.datetime.utcnow().replace(microsecond=0)
    expires = (now + _dt.timedelta(days=TOKEN_TTL_DAYS)).isoformat()
    conn.execute(
        "INSERT INTO auth_token (token, user_id, expires_at, created_at) VALUES (?,?,?,?)",
        (token, user_id, expires, now.isoformat()),
    )
    conn.commit()
    return token


def verify_token(conn: sqlite3.Connection, token: Optional[str]) -> Optional[int]:
    """Return the user id for a valid, unexpired token, sliding its expiry.

    Each successful verification pushes the expiry back out to the full TTL so
    an actively-used session never lapses.
    """
    if not token or not isinstance(token, str):
        return None
    row = conn.execute(
        "SELECT user_id, expires_at FROM auth_token WHERE token=?", (token,)
    ).fetchone()
    if row is None:
        return None
    now = _dt.datetime.utcnow().replace(microsecond=0)
    try:
        expires = _dt.datetime.fromisoformat(row["expires_at"])
    except (ValueError, TypeError):
        return None
    if expires <= now:
        conn.execute("DELETE FROM auth_token WHERE token=?", (token,))
        conn.commit()
        return None
    new_expires = (now + _dt.timedelta(days=TOKEN_TTL_DAYS)).isoformat()
    conn.execute(
        "UPDATE auth_token SET expires_at=? WHERE token=?", (new_expires, token)
    )
    conn.commit()
    return int(row["user_id"])


def revoke_token(conn: sqlite3.Connection, token: Optional[str]) -> None:
    if not token:
        return
    conn.execute("DELETE FROM auth_token WHERE token=?", (token,))
    conn.commit()


def get_user(conn: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT id, username, created_at FROM users WHERE id=?", (user_id,)
    ).fetchone()
