"""Empresas (matriz/filial), configuração e consulta de estoque por filial."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from lib.database import connection, transaction
from lib.errors import DomainError
from lib import crypto


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def list_companies(
    type: str | None = None,
    parent_id: int | None = None,
    active: bool | None = True,
) -> list[dict[str, Any]]:
    with connection() as conn:
        query = "SELECT * FROM companies WHERE 1=1"
        params: list[Any] = []
        if type is not None:
            query += " AND type = ?"
            params.append(type)
        if parent_id is not None:
            query += " AND parent_id = ?"
            params.append(parent_id)
        if active is not None:
            query += " AND active = ?"
            params.append(1 if active else 0)
        query += " ORDER BY name"
        rows = conn.execute(query, params).fetchall()
    result = [dict(r) for r in rows]
    for item in result:
        item["document"] = crypto.decrypt(item.get("document"))
    return result


def get_company(company_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["document"] = crypto.decrypt(data.get("document"))
    return data


def save_company(
    *,
    company_id: int | None = None,
    name: str,
    type: str,
    parent_id: int | None = None,
    address: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    document: str | None = None,
    phone: str | None = None,
    active: bool = True,
    allow_branch_stock_view: bool = False,
) -> int:
    name = name.strip()
    if not name:
        raise DomainError("Informe o nome da empresa.")
    if type not in ("matriz", "filial"):
        raise DomainError("Tipo de empresa inválido.")
    if type == "filial" and parent_id is None:
        raise DomainError("Filial precisa estar vinculada a uma matriz.")
    now = _now()
    with transaction() as conn:
        if company_id is None:
            cur = conn.execute(
                """
                INSERT INTO companies
                    (name, type, parent_id, address, city, state, zip_code,
                     document, document_hash, phone, active, allow_branch_stock_view,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, type, parent_id, address, city, state, zip_code,
                    crypto.encrypt(document), crypto.hash_document(document), phone, 1 if active else 0,
                    1 if allow_branch_stock_view else 0, now, now,
                ),
            )
            return int(cur.lastrowid)
        conn.execute(
            """
            UPDATE companies
               SET name = ?, type = ?, parent_id = ?, address = ?, city = ?,
                   state = ?, zip_code = ?, document = ?, document_hash = ?, phone = ?,
                   active = ?, allow_branch_stock_view = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                name, type, parent_id, address, city, state, zip_code,
                crypto.encrypt(document), crypto.hash_document(document), phone, 1 if active else 0,
                1 if allow_branch_stock_view else 0, now, company_id,
            ),
        )
        return company_id


def set_branch_stock_view(branch_id: int, enabled: bool, actor: str) -> None:
    """Habilita/desabilita a consulta de estoque da filial pela matriz."""
    with transaction() as conn:
        row = conn.execute(
            "SELECT type FROM companies WHERE id = ?", (branch_id,)
        ).fetchone()
        if row is None or row["type"] != "filial":
            raise DomainError("Empresa não é uma filial.")
        conn.execute(
            "UPDATE companies SET allow_branch_stock_view = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), branch_id),
        )


def list_branches_with_stock(matriz_id: int) -> list[dict[str, Any]]:
    """Lista filiais da matriz com o total de estoque, respeitando a permissão."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COALESCE(SUM(p.stock), 0) AS total_stock,
                   COUNT(p.id) AS product_count
              FROM companies c
              LEFT JOIN products p ON p.company_id = c.id
             WHERE c.type = 'filial' AND c.parent_id = ?
             GROUP BY c.id
             ORDER BY c.name
            """,
            (matriz_id,),
        ).fetchall()
    result = [dict(r) for r in rows]
    for item in result:
        item["document"] = crypto.decrypt(item.get("document"))
    return result


import streamlit as st


def current_company_id() -> int | None:
    company = st.session_state.get("auth_company")
    if isinstance(company, dict):
        return int(company.get("id")) if company.get("id") is not None else None
    if company is not None:
        try:
            return int(company)
        except (TypeError, ValueError):
            return None
    return get_default_company_id()


def get_default_company_id() -> int | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM companies WHERE type = 'matriz' ORDER BY id LIMIT 1"
        ).fetchone()
    return int(row["id"]) if row else None


def list_companies_for_user(user_id: int, *, is_superuser: bool = False) -> list[dict]:
    if is_superuser:
        return list_companies(active=True)
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT c.* FROM companies c
            JOIN user_companies uc ON uc.company_id = c.id
            WHERE uc.user_id = ? AND c.active = 1
            ORDER BY uc.is_default DESC, c.name
            """,
            (user_id,),
        ).fetchall()
    result = [dict(r) for r in rows]
    for item in result:
        item["document"] = crypto.decrypt(item.get("document"))
    return result


def user_has_company(user_id: int, company_id: int, *, is_superuser: bool = False) -> bool:
    if is_superuser:
        return True
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_companies WHERE user_id = ? AND company_id = ?",
            (user_id, company_id),
        ).fetchone()
    return row is not None


def assign_company(user_id: int, company_id: int, *, is_default: bool = False) -> None:
    now = _now()
    with transaction() as conn:
        exists = conn.execute(
            "SELECT 1 FROM user_companies WHERE user_id = ? AND company_id = ?",
            (user_id, company_id),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO user_companies (user_id, company_id, is_default, created_at) VALUES (?, ?, ?, ?)",
                (user_id, company_id, 1 if is_default else 0, now),
            )
        if is_default:
            conn.execute(
                "UPDATE user_companies SET is_default = 0 WHERE user_id = ? AND company_id <> ?",
                (user_id, company_id),
            )
            conn.execute(
                "UPDATE user_companies SET is_default = 1 WHERE user_id = ? AND company_id = ?",
                (user_id, company_id),
            )


def remove_company(user_id: int, company_id: int) -> None:
    with transaction() as conn:
        conn.execute(
            "DELETE FROM user_companies WHERE user_id = ? AND company_id = ?",
            (user_id, company_id),
        )


def list_user_companies(user_id: int) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT uc.*, c.name AS company_name, c.type AS company_type
            FROM user_companies uc
            JOIN companies c ON c.id = uc.company_id
            WHERE uc.user_id = ?
            ORDER BY uc.is_default DESC, c.name
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_company_config() -> dict[str, str]:
    with connection() as conn:
        rows = conn.execute("SELECT key, value FROM company_config").fetchall()
    return {r["key"]: (r["value"] or "") for r in rows}


def set_company_config(key: str, value: str) -> None:
    now = _now()
    with transaction() as conn:
        exists = conn.execute(
            "SELECT 1 FROM company_config WHERE key = ?", (key,)
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE company_config SET value = ?, updated_at = ? WHERE key = ?",
                (value, now, key),
            )
        else:
            conn.execute(
                "INSERT INTO company_config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
