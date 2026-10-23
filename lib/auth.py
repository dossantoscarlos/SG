"""Autenticação de usuários e manutenção da conta."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from lib.database import transaction
from lib.errors import DomainError
from lib import crypto
from lib.security import hash_password, validate_password_strength, verify_password

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _user_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": crypto.decrypt(row["email"]),
        "active": bool(row["active"]),
        "is_superuser": bool(row["is_superuser"]),
        "must_change_password": bool(row["must_change_password"]),
        "last_login": row["last_login"],
    }


def authenticate(email: str, password: str) -> dict | None:
    """Confere as credenciais e devolve o usuário sem dados sensíveis."""
    normalized = email.strip().lower()
    if not normalized or not password:
        return None

    with transaction() as conn:
        email_hash = crypto.hash_email(normalized)
        row = conn.execute(
            """
            SELECT id, name, email, password_hash, active, is_superuser,
                   must_change_password, last_login
            FROM users
            WHERE email_hash = ?
            """,
            (email_hash,),
        ).fetchone()
        if row is None or not row["active"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None

        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, row["id"]))
        data = _user_to_dict(row)
        data["last_login"] = now
        return data


def get_user(user_id: int) -> dict | None:
    from lib.database import connection

    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, email, active, is_superuser,
                   must_change_password, last_login
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return _user_to_dict(row) if row else None


def update_profile(user_id: int, name: str, email: str) -> dict:
    name = name.strip()
    email = email.strip().lower()
    if len(name) < 3:
        raise DomainError("Informe o nome completo do usuário.")
    if not _EMAIL_RE.match(email):
        raise DomainError("Informe um e-mail válido.")

    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE users SET name = ?, email = ?, email_hash = ? WHERE id = ?",
                (name, crypto.encrypt(email), crypto.hash_email(email), user_id),
            )
            row = conn.execute(
                """
                SELECT id, name, email, active, is_superuser,
                       must_change_password, last_login
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise DomainError("Já existe uma conta com este e-mail.") from exc

    return _user_to_dict(row)


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    problems = validate_password_strength(new_password)
    if problems:
        raise DomainError(" ".join(problems))
    if current_password == new_password:
        raise DomainError("A nova senha precisa ser diferente da senha atual.")

    with transaction() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or not verify_password(current_password, row["password_hash"]):
            raise DomainError("A senha atual está incorreta.")
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 0
            WHERE id = ?
            """,
            (hash_password(new_password), user_id),
        )
