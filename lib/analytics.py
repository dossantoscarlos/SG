"""Consultas analíticas do painel e dos relatórios."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from lib.database import REVENUE_STATUSES, connection

_STATUSES_SQL = "(" + ", ".join(f"'{status}'" for status in REVENUE_STATUSES) + ")"


def _summary_for_range(conn, start: date, end: date) -> dict:
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS orders_count,
            COALESCE(SUM(CASE WHEN status IN {_STATUSES_SQL} THEN 1 ELSE 0 END), 0) AS paid_orders,
            COALESCE(SUM(CASE WHEN status IN {_STATUSES_SQL} THEN total ELSE 0 END), 0) AS revenue
        FROM orders
        WHERE date(created_at) BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    customers = conn.execute(
        """
        SELECT COUNT(*) FROM customers
        WHERE date(created_at) BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    units = conn.execute(
        f"""
        SELECT COALESCE(SUM(oi.quantity), 0)
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status IN {_STATUSES_SQL}
          AND date(o.created_at) BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()[0]

    revenue = float(row["revenue"] or 0)
    paid_orders = int(row["paid_orders"] or 0)
    return {
        "orders_count": int(row["orders_count"] or 0),
        "paid_orders": paid_orders,
        "revenue": revenue,
        "new_customers": int(customers or 0),
        "units_sold": int(units or 0),
        "avg_ticket": revenue / paid_orders if paid_orders else 0.0,
    }


def _daily_series(conn, start: date, end: date) -> pd.DataFrame:
    dates = pd.DataFrame({"data": pd.date_range(start, end, freq="D")})

    orders = pd.read_sql_query(
        f"""
        SELECT date(created_at) AS data,
               COUNT(*) AS pedidos,
               SUM(CASE WHEN status IN {_STATUSES_SQL} THEN 1 ELSE 0 END) AS pedidos_pagos,
               SUM(CASE WHEN status IN {_STATUSES_SQL} THEN total ELSE 0 END) AS receita
        FROM orders
        WHERE date(created_at) BETWEEN ? AND ?
        GROUP BY date(created_at)
        """,
        conn,
        params=[start.isoformat(), end.isoformat()],
    )
    customers = pd.read_sql_query(
        """
        SELECT date(created_at) AS data, COUNT(*) AS novos_clientes
        FROM customers
        WHERE date(created_at) BETWEEN ? AND ?
        GROUP BY date(created_at)
        """,
        conn,
        params=[start.isoformat(), end.isoformat()],
    )
    units = pd.read_sql_query(
        f"""
        SELECT date(o.created_at) AS data, SUM(oi.quantity) AS unidades
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status IN {_STATUSES_SQL}
          AND date(o.created_at) BETWEEN ? AND ?
        GROUP BY date(o.created_at)
        """,
        conn,
        params=[start.isoformat(), end.isoformat()],
    )

    for frame in (orders, customers, units):
        if not frame.empty:
            frame["data"] = pd.to_datetime(frame["data"])

    daily = dates.merge(orders, on="data", how="left")
    daily = daily.merge(customers, on="data", how="left")
    daily = daily.merge(units, on="data", how="left")
    numeric = ["pedidos", "pedidos_pagos", "receita", "novos_clientes", "unidades"]
    daily[numeric] = daily[numeric].fillna(0)
    for column in ["pedidos", "pedidos_pagos", "novos_clientes", "unidades"]:
        daily[column] = daily[column].astype(int)
    daily["receita"] = daily["receita"].astype(float)
    return daily


def get_dashboard(start: date, end: date) -> dict:
    period_days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)

    with connection() as conn:
        summary = _summary_for_range(conn, start, end)
        previous = _summary_for_range(conn, previous_start, previous_end)
        daily = _daily_series(conn, start, end)

        status_counts = pd.read_sql_query(
            """
            SELECT status, COUNT(*) AS pedidos, COALESCE(SUM(total), 0) AS valor
            FROM orders
            WHERE date(created_at) BETWEEN ? AND ?
            GROUP BY status
            ORDER BY pedidos DESC
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        top_products = pd.read_sql_query(
            f"""
            SELECT p.name AS produto, p.category AS categoria,
                   SUM(oi.quantity) AS unidades,
                   ROUND(SUM(oi.quantity * oi.unit_price), 2) AS receita
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            GROUP BY p.id
            ORDER BY receita DESC
            LIMIT 6
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        low_stock = pd.read_sql_query(
            """
            SELECT id, sku, name, category, stock, min_stock
            FROM products
            WHERE active = 1 AND stock <= min_stock
            ORDER BY (CAST(stock AS REAL) / CASE WHEN min_stock = 0 THEN 1 ELSE min_stock END),
                     stock ASC
            LIMIT 7
            """,
            conn,
        )

        recent_orders = pd.read_sql_query(
            """
            SELECT o.id, o.number, c.name AS customer_name, o.status,
                   o.total, o.created_at, COUNT(oi.id) AS item_count
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            LEFT JOIN order_items oi ON oi.order_id = o.id
            GROUP BY o.id
            ORDER BY datetime(o.created_at) DESC, o.id DESC
            LIMIT 6
            """,
            conn,
        )

    return {
        "start": start,
        "end": end,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "summary": summary,
        "previous": previous,
        "daily": daily,
        "status_counts": status_counts,
        "top_products": top_products,
        "low_stock": low_stock,
        "recent_orders": recent_orders,
    }


def get_report(start: date, end: date) -> dict:
    with connection() as conn:
        summary_row = conn.execute(
            f"""
            SELECT COUNT(*) AS orders_count,
                   COALESCE(SUM(total), 0) AS revenue,
                   COALESCE(SUM(discount), 0) AS discount
            FROM orders
            WHERE status IN {_STATUSES_SQL}
              AND date(created_at) BETWEEN ? AND ?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()

        item_row = conn.execute(
            f"""
            SELECT COALESCE(SUM(oi.quantity), 0) AS units,
                   COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS item_revenue,
                   COALESCE(SUM(oi.quantity * oi.cost_at_sale), 0) AS cogs
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()

        daily = _daily_series(conn, start, end)

        by_category = pd.read_sql_query(
            f"""
            SELECT p.category AS categoria,
                   SUM(oi.quantity) AS unidades,
                   ROUND(SUM(oi.quantity * oi.unit_price), 2) AS receita
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            GROUP BY p.category
            ORDER BY receita DESC
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        top_products = pd.read_sql_query(
            f"""
            SELECT p.name AS produto, p.category AS categoria,
                   SUM(oi.quantity) AS unidades,
                   ROUND(SUM(oi.quantity * oi.unit_price), 2) AS receita,
                   ROUND(SUM(oi.quantity * (oi.unit_price - oi.cost_at_sale)), 2) AS lucro_bruto
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            GROUP BY p.id
            ORDER BY receita DESC
            LIMIT 10
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        top_customers = pd.read_sql_query(
            f"""
            SELECT c.name AS cliente, c.email, c.city AS cidade, c.state AS uf,
                   COUNT(o.id) AS pedidos,
                   ROUND(SUM(o.total), 2) AS receita,
                   MAX(o.created_at) AS ultimo_pedido
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            GROUP BY c.id
            ORDER BY receita DESC
            LIMIT 10
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        payment_methods = pd.read_sql_query(
            f"""
            SELECT payment_method AS forma_pagamento,
                   COUNT(*) AS pedidos,
                   ROUND(SUM(total), 2) AS receita
            FROM orders
            WHERE status IN {_STATUSES_SQL}
              AND date(created_at) BETWEEN ? AND ?
            GROUP BY payment_method
            ORDER BY receita DESC
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        orders_detail = pd.read_sql_query(
            f"""
            SELECT o.number AS pedido, date(o.created_at) AS data,
                   c.name AS cliente, o.status, o.payment_method AS pagamento,
                   o.channel AS canal, COUNT(oi.id) AS itens,
                   ROUND(o.discount, 2) AS desconto, ROUND(o.shipping, 2) AS frete,
                   ROUND(o.total, 2) AS total
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            LEFT JOIN order_items oi ON oi.order_id = o.id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            GROUP BY o.id
            ORDER BY datetime(o.created_at) DESC
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

        items_detail = pd.read_sql_query(
            f"""
            SELECT o.number AS pedido, date(o.created_at) AS data,
                   c.name AS cliente, p.sku, p.name AS produto,
                   p.category AS categoria, oi.quantity AS quantidade,
                   ROUND(oi.unit_price, 2) AS valor_unitario,
                   ROUND(oi.quantity * oi.unit_price, 2) AS total_item
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN customers c ON c.id = o.customer_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status IN {_STATUSES_SQL}
              AND date(o.created_at) BETWEEN ? AND ?
            ORDER BY datetime(o.created_at) DESC, o.id DESC
            """,
            conn,
            params=[start.isoformat(), end.isoformat()],
        )

    revenue = float(summary_row["revenue"] or 0)
    orders_count = int(summary_row["orders_count"] or 0)
    units = int(item_row["units"] or 0)
    item_revenue = float(item_row["item_revenue"] or 0)
    cogs = float(item_row["cogs"] or 0)
    discounts = float(summary_row["discount"] or 0)
    gross_profit = item_revenue - cogs - discounts
    net_product_revenue = item_revenue - discounts
    gross_margin = gross_profit / net_product_revenue if net_product_revenue > 0 else 0.0

    summary = {
        "revenue": revenue,
        "orders_count": orders_count,
        "avg_ticket": revenue / orders_count if orders_count else 0.0,
        "units_sold": units,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "discounts": discounts,
    }

    return {
        "start": start,
        "end": end,
        "summary": summary,
        "daily": daily,
        "by_category": by_category,
        "top_products": top_products,
        "top_customers": top_customers,
        "payment_methods": payment_methods,
        "orders_detail": orders_detail,
        "items_detail": items_detail,
    }
