"""Cadastro e consultas de produtos e clientes."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

import pandas as pd

from lib.database import (
    CATEGORIES,
    CUSTOMER_STATUSES,
    REVENUE_STATUSES,
    connection,
    transaction,
)
from lib.errors import DomainError
from lib.inventory import record_stock_movement

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------

def list_products(search: str = "", category: str = "Todas", status: str = "Todos") -> pd.DataFrame:
    clauses = ["1 = 1"]
    params: list[object] = []

    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(p.name) LIKE ? OR lower(p.sku) LIKE ? OR lower(p.category) LIKE ?)"
        )
        params.extend([term, term, term])
    if category and category != "Todas":
        clauses.append("p.category = ?")
        params.append(category)
    if status == "Ativos":
        clauses.append("p.active = 1")
    elif status == "Inativos":
        clauses.append("p.active = 0")

    sql = f"""
        SELECT p.id, p.sku, p.name, p.category, p.description, p.price, p.cost,
               p.stock, p.min_stock, p.active, p.created_at, p.updated_at
        FROM products p
        WHERE {' AND '.join(clauses)}
        ORDER BY p.active DESC, p.name COLLATE NOCASE
    """
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_product(product_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def next_sku_suggestion() -> str:
    with connection() as conn:
        next_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM products"
        ).fetchone()[0]
    return f"SG-{int(next_id):03d}"


def list_categories() -> list[str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products WHERE trim(category) <> ''"
        ).fetchall()
    values = {row["category"] for row in rows}
    values.update(CATEGORIES)
    return sorted(values, key=str.casefold)


def save_product(
    *,
    sku: str,
    name: str,
    category: str,
    description: str | None,
    price: float,
    cost: float,
    stock: int,
    min_stock: int,
    active: bool,
    product_id: int | None = None,
    actor: str = "Sistema",
) -> int:
    sku = sku.strip().upper()
    name = name.strip()
    category = category.strip()
    description = (description or "").strip() or None

    if len(sku) < 2:
        raise DomainError("Informe um SKU com pelo menos 2 caracteres.")
    if len(name) < 2:
        raise DomainError("Informe o nome do produto.")
    if not category:
        raise DomainError("Informe a categoria do produto.")
    if price < 0 or cost < 0:
        raise DomainError("Preço e custo não podem ser negativos.")
    if cost > price:
        raise DomainError("O custo não pode ser maior que o preço de venda.")
    if stock < 0 or min_stock < 0:
        raise DomainError("Os valores de estoque não podem ser negativos.")

    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    try:
        with transaction() as conn:
            if product_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO products
                        (sku, name, category, description, price, cost, stock,
                         min_stock, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sku,
                        name,
                        category,
                        description,
                        round(float(price), 2),
                        round(float(cost), 2),
                        int(stock),
                        int(min_stock),
                        int(active),
                        now,
                        now,
                    ),
                )
                new_id = int(cursor.lastrowid)
                if int(stock) > 0:
                    record_stock_movement(
                        conn,
                        product_id=new_id,
                        quantity=int(stock),
                        kind="Saldo inicial",
                        balance_after=int(stock),
                        reason="Cadastro inicial do produto",
                        actor=actor,
                        created_at=now,
                    )
                return new_id

            old = conn.execute(
                "SELECT stock FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if old is None:
                raise DomainError("Produto não encontrado.")
            conn.execute(
                """
                UPDATE products
                SET sku = ?, name = ?, category = ?, description = ?, price = ?,
                    cost = ?, stock = ?, min_stock = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    sku,
                    name,
                    category,
                    description,
                    round(float(price), 2),
                    round(float(cost), 2),
                    int(stock),
                    int(min_stock),
                    int(active),
                    now,
                    product_id,
                ),
            )
            stock_delta = int(stock) - int(old["stock"])
            if stock_delta:
                record_stock_movement(
                    conn,
                    product_id=product_id,
                    quantity=stock_delta,
                    kind="Ajuste",
                    balance_after=int(stock),
                    reason="Edição manual do estoque no cadastro",
                    actor=actor,
                    created_at=now,
                )
            return product_id
    except sqlite3.IntegrityError as exc:
        raise DomainError("Já existe um produto cadastrado com este SKU.") from exc


def set_product_active(product_id: int, active: bool) -> None:
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE products SET active = ?, updated_at = ? WHERE id = ?",
            (int(active), now, product_id),
        )
        if cursor.rowcount == 0:
            raise DomainError("Produto não encontrado.")


def delete_product(product_id: int) -> None:
    with transaction() as conn:
        linked = conn.execute(
            "SELECT COUNT(*) FROM order_items WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
        if linked:
            raise DomainError(
                "Este produto possui pedidos vinculados. Desative-o em vez de excluir."
            )
        stock_history = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM stock_movements WHERE product_id = ?) +
                (SELECT COUNT(*) FROM stock_document_items WHERE product_id = ?)
            """,
            (product_id, product_id),
        ).fetchone()[0]
        if stock_history:
            raise DomainError(
                "Este produto possui histórico de estoque. Desative-o em vez de "
                "excluir para preservar o livro-razão."
            )
        stock = conn.execute(
            "SELECT stock FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if stock is not None and int(stock["stock"]) != 0:
            raise DomainError(
                "Zere o estoque antes de excluir o produto ou desative-o."
            )
        cursor = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        if cursor.rowcount == 0:
            raise DomainError("Produto não encontrado.")


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------

def list_customers(search: str = "", status: str = "Todos") -> pd.DataFrame:
    clauses = ["1 = 1"]
    params: list[object] = []

    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(c.name) LIKE ? OR lower(c.email) LIKE ? OR lower(c.phone) LIKE ? "
            "OR lower(c.city) LIKE ?)"
        )
        params.extend([term, term, term, term])
    if status in CUSTOMER_STATUSES:
        clauses.append("c.status = ?")
        params.append(status)

    sql = f"""
        SELECT c.id, c.name, c.email, c.phone, c.city, c.state, c.status,
               c.notes, c.created_at, c.updated_at,
               COUNT(o.id) AS orders_count,
               COALESCE(SUM(CASE WHEN o.status IN ('Pago', 'Enviado', 'Entregue')
                                 THEN o.total ELSE 0 END), 0) AS total_spent,
               MAX(o.created_at) AS last_order
        FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.id
        WHERE {' AND '.join(clauses)}
        GROUP BY c.id
        ORDER BY c.name COLLATE NOCASE
    """
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_customer(customer_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return dict(row) if row else None


def get_customer_stats(customer_id: int) -> dict:
    """Resumo de compras do cliente para a ficha de atendimento."""
    statuses = ", ".join(f"'{status}'" for status in REVENUE_STATUSES)
    with connection() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(o.id) AS orders_count,
                   COALESCE(SUM(CASE WHEN o.status IN ({statuses}) THEN 1 ELSE 0 END), 0)
                       AS paid_orders,
                   COALESCE(SUM(CASE WHEN o.status IN ({statuses}) THEN o.total ELSE 0 END), 0)
                       AS total_spent,
                   MIN(o.created_at) AS first_order,
                   MAX(o.created_at) AS last_order
            FROM orders o
            WHERE o.customer_id = ?
            """,
            (customer_id,),
        ).fetchone()
    data = dict(row)
    data["orders_count"] = int(data["orders_count"] or 0)
    data["paid_orders"] = int(data["paid_orders"] or 0)
    data["total_spent"] = float(data["total_spent"] or 0)
    data["avg_ticket"] = (
        data["total_spent"] / data["paid_orders"] if data["paid_orders"] else 0.0
    )
    return data


def save_customer(
    *,
    name: str,
    email: str | None,
    phone: str | None,
    city: str | None,
    state: str | None,
    status: str,
    notes: str | None,
    customer_id: int | None = None,
) -> int:
    name = name.strip()
    email = (email or "").strip().lower() or None
    phone = (phone or "").strip() or None
    city = (city or "").strip() or None
    state = (state or "").strip().upper() or None
    notes = (notes or "").strip() or None

    if len(name) < 3:
        raise DomainError("Informe o nome completo do cliente.")
    if email and not _EMAIL_RE.match(email):
        raise DomainError("Informe um e-mail válido.")
    if status not in CUSTOMER_STATUSES:
        raise DomainError("Situação do cliente inválida.")

    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    try:
        with transaction() as conn:
            if customer_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO customers
                        (name, email, phone, city, state, status, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, email, phone, city, state, status, notes, now, now),
                )
                return int(cursor.lastrowid)

            exists = conn.execute(
                "SELECT 1 FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            if not exists:
                raise DomainError("Cliente não encontrado.")
            conn.execute(
                """
                UPDATE customers
                SET name = ?, email = ?, phone = ?, city = ?, state = ?, status = ?,
                    notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, email, phone, city, state, status, notes, now, customer_id),
            )
            return customer_id
    except sqlite3.IntegrityError as exc:
        raise DomainError("Já existe um cliente cadastrado com este e-mail.") from exc


def set_customer_status(customer_id: int, status: str) -> None:
    if status not in CUSTOMER_STATUSES:
        raise DomainError("Situação do cliente inválida.")
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE customers SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, customer_id),
        )
        if cursor.rowcount == 0:
            raise DomainError("Cliente não encontrado.")


def delete_customer(customer_id: int) -> None:
    with transaction() as conn:
        linked = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_id = ?", (customer_id,)
        ).fetchone()[0]
        if linked:
            raise DomainError(
                "Este cliente possui pedidos vinculados. Desative-o em vez de excluir."
            )
        cursor = conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        if cursor.rowcount == 0:
            raise DomainError("Cliente não encontrado.")
