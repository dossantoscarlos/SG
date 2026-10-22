"""Regras de pedidos, itens e movimentação de estoque."""

from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd

from lib.database import (
    CHANNELS,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    connection,
    transaction,
)
from lib.errors import DomainError
from lib.inventory import (
    INTERNAL_LOCATION,
    INTERNAL_STOCK,
    add_stock_document_item,
    open_stock_document,
    record_stock_movement,
    stock_status_for_order,
    sync_order_document_status,
)
from lib.logistics import sync_shipment_status


def list_orders(
    search: str = "",
    status: str = "Todos",
    customer_id: int | None = None,
    limit: int = 300,
) -> pd.DataFrame:
    clauses = ["1 = 1"]
    params: list[object] = []

    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(o.number) LIKE ? OR lower(c.name) LIKE ? OR lower(c.email) LIKE ?)"
        )
        params.extend([term, term, term])
    if status in ORDER_STATUSES:
        clauses.append("o.status = ?")
        params.append(status)
    if customer_id is not None:
        clauses.append("o.customer_id = ?")
        params.append(customer_id)

    sql = f"""
        SELECT o.id, o.number, o.customer_id, c.name AS customer_name,
               c.email AS customer_email, o.status, o.payment_method, o.channel,
               o.discount, o.shipping, o.total, o.notes, o.created_at, o.updated_at,
               COUNT(oi.id) AS item_count,
               COALESCE(SUM(oi.quantity), 0) AS item_units
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE {' AND '.join(clauses)}
        GROUP BY o.id
        ORDER BY datetime(o.created_at) DESC, o.id DESC
        LIMIT ?
    """
    params.append(int(limit))
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_order(order_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT o.*, c.name AS customer_name, c.email AS customer_email,
                   c.phone AS customer_phone, c.city AS customer_city,
                   c.state AS customer_state
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def get_order_items(order_id: int) -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(
            """
            SELECT oi.id, oi.product_id, p.sku, p.name AS product_name,
                   p.category, oi.quantity, oi.unit_price, oi.cost_at_sale,
                   ROUND(oi.quantity * oi.unit_price, 2) AS line_total
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ?
            ORDER BY oi.id
            """,
            conn,
            params=[order_id],
        )


def create_order(
    *,
    customer_id: int,
    status: str,
    payment_method: str,
    channel: str,
    discount: float,
    shipping: float,
    notes: str | None,
    items: list[tuple[int, int]],
    actor: str = "Sistema",
) -> tuple[int, str]:
    if status not in ("Pendente", "Pago"):
        raise DomainError("O status inicial do pedido deve ser Pendente ou Pago.")
    if payment_method not in PAYMENT_METHODS:
        raise DomainError("Forma de pagamento inválida.")
    if channel not in CHANNELS:
        raise DomainError("Canal de venda inválido.")
    if not items:
        raise DomainError("Adicione pelo menos um item ao pedido.")
    if discount < 0 or shipping < 0:
        raise DomainError("Desconto e frete não podem ser negativos.")

    merged: dict[int, int] = {}
    for product_id, quantity in items:
        if int(quantity) <= 0:
            raise DomainError("A quantidade dos itens deve ser maior que zero.")
        merged[int(product_id)] = merged.get(int(product_id), 0) + int(quantity)

    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with transaction() as conn:
        customer = conn.execute(
            "SELECT id, name, city, state FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        if customer is None:
            raise DomainError("Cliente não encontrado.")

        products: list[tuple[dict, int]] = []
        subtotal = 0.0
        for product_id, quantity in merged.items():
            product = conn.execute(
                """
                SELECT id, sku, name, price, cost, stock, active
                FROM products WHERE id = ?
                """,
                (product_id,),
            ).fetchone()
            if product is None:
                raise DomainError("Um dos produtos selecionados não foi encontrado.")
            if not product["active"]:
                raise DomainError(f"O produto {product['name']} está inativo.")
            if product["stock"] < quantity:
                raise DomainError(
                    f"Estoque insuficiente para {product['name']}. "
                    f"Disponível: {product['stock']} un."
                )
            products.append((dict(product), quantity))
            subtotal += float(product["price"]) * quantity

        subtotal = round(subtotal, 2)
        discount = round(float(discount), 2)
        shipping = round(float(shipping), 2)
        if discount > subtotal:
            raise DomainError("O desconto não pode ser maior que o subtotal.")
        total = round(subtotal - discount + shipping, 2)

        cursor = conn.execute(
            """
            INSERT INTO orders
                (number, customer_id, status, payment_method, channel, discount,
                 shipping, total, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"TMP-{uuid.uuid4().hex[:16].upper()}",
                customer_id,
                status,
                payment_method,
                channel,
                discount,
                shipping,
                total,
                (notes or "").strip() or None,
                now,
                now,
            ),
        )
        order_id = int(cursor.lastrowid)
        number = f"PED-{datetime.now().year}-{order_id:04d}"
        conn.execute("UPDATE orders SET number = ? WHERE id = ?", (number, order_id))

        customer_location = (
            f"{customer['city']}/{customer['state']}"
            if customer["city"] and customer["state"]
            else customer["city"] or customer["state"]
        )
        document_id = open_stock_document(
            conn,
            kind="Venda",
            status=stock_status_for_order(status),
            source=(INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION),
            destination=(
                "Cliente",
                int(customer["id"]),
                customer["name"],
                customer_location,
            ),
            reason=f"Venda do pedido {number}",
            actor=actor,
            created_at=now,
            order_id=order_id,
        )

        for product, quantity in products:
            conn.execute(
                """
                INSERT INTO order_items
                    (order_id, product_id, quantity, unit_price, cost_at_sale)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    product["id"],
                    quantity,
                    float(product["price"]),
                    float(product["cost"]),
                ),
            )
            document_item_id = add_stock_document_item(
                conn,
                document_id=document_id,
                product=product,
                quantity=quantity,
                unit_cost=float(product["cost"]),
            )
            stock_cursor = conn.execute(
                """
                UPDATE products
                SET stock = stock - ?, updated_at = ?
                WHERE id = ? AND stock >= ?
                """,
                (quantity, now, product["id"], quantity),
            )
            if stock_cursor.rowcount == 0:
                raise DomainError(
                    f"O estoque de {product['name']} mudou durante o pedido. "
                    "Revise os itens e tente novamente."
                )
            record_stock_movement(
                conn,
                product_id=product["id"],
                quantity=-quantity,
                kind="Venda",
                balance_before=int(product["stock"]),
                balance_after=int(product["stock"]) - quantity,
                reason=f"Venda do pedido {number}",
                actor=actor,
                order_id=order_id,
                entity_kind="Cliente",
                entity_id=int(customer["id"]),
                status=stock_status_for_order(status),
                created_at=now,
                document_id=document_id,
                document_item_id=document_item_id,
                unit_cost=float(product["cost"]),
            )

        return order_id, number


def update_order_status(
    order_id: int, new_status: str, actor: str = "Sistema"
) -> None:
    if new_status not in ORDER_STATUSES:
        raise DomainError("Status de pedido inválido.")
    now = datetime.now().isoformat(sep=" ", timespec="seconds")

    with transaction() as conn:
        order = conn.execute(
            """
            SELECT o.id, o.status, o.number, o.customer_id,
                   c.name AS customer_name, c.city AS customer_city,
                   c.state AS customer_state
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            raise DomainError("Pedido não encontrado.")

        old_status = order["status"]
        if old_status == new_status:
            return
        number = order["number"]
        customer_location = (
            f"{order['customer_city']}/{order['customer_state']}"
            if order["customer_city"] and order["customer_state"]
            else order["customer_city"] or order["customer_state"]
        )
        customer_party = (
            "Cliente",
            int(order["customer_id"]),
            order["customer_name"],
            customer_location,
        )
        internal_party = (INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION)

        items = conn.execute(
            """
            SELECT oi.product_id, oi.quantity, p.sku, p.name, p.cost
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ?
            ORDER BY oi.id
            """,
            (order_id,),
        ).fetchall()

        if new_status == "Cancelado":
            document_id = open_stock_document(
                conn,
                kind="Cancelamento",
                status="Concluído",
                source=customer_party,
                destination=internal_party,
                reason=f"Cancelamento do pedido {number}",
                actor=actor,
                created_at=now,
                order_id=order_id,
            )
            for item in items:
                product = conn.execute(
                    "SELECT id, sku, name, stock, cost FROM products WHERE id = ?",
                    (item["product_id"],),
                ).fetchone()
                if product is None:
                    raise DomainError("Produto do pedido não encontrado.")
                document_item_id = add_stock_document_item(
                    conn,
                    document_id=document_id,
                    product=product,
                    quantity=int(item["quantity"]),
                    unit_cost=float(item["cost"]),
                )
                old_stock = int(product["stock"])
                conn.execute(
                    "UPDATE products SET stock = stock + ?, updated_at = ? WHERE id = ?",
                    (item["quantity"], now, item["product_id"]),
                )
                record_stock_movement(
                    conn,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                    kind="Cancelamento",
                    balance_before=old_stock,
                    balance_after=old_stock + int(item["quantity"]),
                    reason=f"Cancelamento do pedido {number}",
                    actor=actor,
                    order_id=order_id,
                    entity_kind="Cliente",
                    entity_id=int(order["customer_id"]),
                    status="Concluído",
                    created_at=now,
                    document_id=document_id,
                    document_item_id=document_item_id,
                    unit_cost=float(item["cost"]),
                )
            sync_order_document_status(
                conn,
                order_id=order_id,
                new_status="Cancelado",
                actor=actor,
                now=now,
                reversal_document_id=document_id,
            )
        elif old_status == "Cancelado":
            for item in items:
                product = conn.execute(
                    "SELECT stock FROM products WHERE id = ?", (item["product_id"],)
                ).fetchone()
                if product is None or product["stock"] < item["quantity"]:
                    available = product["stock"] if product else 0
                    raise DomainError(
                        f"Não há estoque suficiente para reativar o pedido: "
                        f"{item['name']} (disponível: {available})."
                    )
            document_id = open_stock_document(
                conn,
                kind="Reativação",
                status=stock_status_for_order(new_status),
                source=internal_party,
                destination=customer_party,
                reason=f"Reativação do pedido {number}",
                actor=actor,
                created_at=now,
                order_id=order_id,
            )
            for item in items:
                product = conn.execute(
                    "SELECT id, sku, name, stock, cost FROM products WHERE id = ?",
                    (item["product_id"],),
                ).fetchone()
                if product is None:
                    raise DomainError("Produto do pedido não encontrado.")
                document_item_id = add_stock_document_item(
                    conn,
                    document_id=document_id,
                    product=product,
                    quantity=int(item["quantity"]),
                    unit_cost=float(item["cost"]),
                )
                old_stock = int(product["stock"])
                conn.execute(
                    "UPDATE products SET stock = stock - ?, updated_at = ? WHERE id = ?",
                    (item["quantity"], now, item["product_id"]),
                )
                record_stock_movement(
                    conn,
                    product_id=item["product_id"],
                    quantity=-item["quantity"],
                    kind="Reativação",
                    balance_before=old_stock,
                    balance_after=old_stock - int(item["quantity"]),
                    reason=f"Reativação do pedido {number}",
                    actor=actor,
                    order_id=order_id,
                    entity_kind="Cliente",
                    entity_id=int(order["customer_id"]),
                    status=stock_status_for_order(new_status),
                    created_at=now,
                    document_id=document_id,
                    document_item_id=document_item_id,
                    unit_cost=float(item["cost"]),
                )

        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, order_id),
        )
        sync_order_document_status(
            conn,
            order_id=order_id,
            new_status=new_status,
            actor=actor,
            now=now,
        )
        sync_shipment_status(conn, order_id, new_status, now)


def delete_order(order_id: int, actor: str = "Sistema") -> None:
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with transaction() as conn:
        order = conn.execute(
            """
            SELECT o.status, o.number, o.customer_id, c.name AS customer_name,
                   c.city AS customer_city, c.state AS customer_state
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            raise DomainError("Pedido não encontrado.")

        if order["status"] != "Cancelado":
            customer_location = (
                f"{order['customer_city']}/{order['customer_state']}"
                if order["customer_city"] and order["customer_state"]
                else order["customer_city"] or order["customer_state"]
            )
            document_id = open_stock_document(
                conn,
                kind="Exclusão",
                status="Concluído",
                source=(
                    "Cliente",
                    int(order["customer_id"]),
                    order["customer_name"],
                    customer_location,
                ),
                destination=(INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION),
                reason=f"Exclusão do pedido {order['number']}",
                actor=actor,
                created_at=now,
                order_id=order_id,
            )
            items = conn.execute(
                """
                SELECT oi.product_id, oi.quantity, p.sku, p.name, p.cost
                FROM order_items oi
                JOIN products p ON p.id = oi.product_id
                WHERE oi.order_id = ?
                ORDER BY oi.id
                """,
                (order_id,),
            ).fetchall()
            for item in items:
                product = conn.execute(
                    "SELECT id, sku, name, stock, cost FROM products WHERE id = ?",
                    (item["product_id"],),
                ).fetchone()
                if product is None:
                    raise DomainError("Produto do pedido não encontrado.")
                document_item_id = add_stock_document_item(
                    conn,
                    document_id=document_id,
                    product=product,
                    quantity=int(item["quantity"]),
                    unit_cost=float(item["cost"]),
                )
                old_stock = int(product["stock"])
                conn.execute(
                    "UPDATE products SET stock = stock + ?, updated_at = ? WHERE id = ?",
                    (item["quantity"], now, item["product_id"]),
                )
                record_stock_movement(
                    conn,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                    kind="Exclusão",
                    balance_before=old_stock,
                    balance_after=old_stock + int(item["quantity"]),
                    reason=f"Exclusão do pedido {order['number']}",
                    actor=actor,
                    order_id=order_id,
                    entity_kind="Cliente",
                    entity_id=int(order["customer_id"]),
                    status="Concluído",
                    created_at=now,
                    document_id=document_id,
                    document_item_id=document_item_id,
                    unit_cost=float(item["cost"]),
                )
            sync_order_document_status(
                conn,
                order_id=order_id,
                new_status="Cancelado",
                actor=actor,
                now=now,
                reversal_document_id=document_id,
            )

        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
