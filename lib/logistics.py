"""Expedição, transportadoras, rastreio e indicadores logísticos."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time
from urllib.parse import quote

import pandas as pd

from lib.database import connection, transaction
from lib.errors import DomainError
from lib.inventory import sync_order_document_status

FULFILLMENT_VIEWS = ("Todos", "A separar", "Em trânsito", "Atrasados", "Entregues")
DEFAULT_SERVICES = ("Econômico", "Expresso", "Sedex", "Retirada no local")


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def build_tracking_url(url: str | None, code: str | None) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    if code is None or (not isinstance(code, str) and pd.isna(code)):
        return None
    code = str(code).strip()
    if not code:
        return None
    template = url.strip()
    if "{tracking}" not in template:
        return template or None
    return template.replace("{tracking}", quote(code, safe=""))


def list_carriers(active_only: bool = False) -> pd.DataFrame:
    clause = "WHERE c.active = 1" if active_only else ""
    sql = f"""
        SELECT c.id, c.name, c.tracking_url, c.phone, c.active,
               c.created_at, c.updated_at,
               COUNT(s.id) AS shipments_count
        FROM carriers c
        LEFT JOIN shipments s ON s.carrier_id = c.id
        {clause}
        GROUP BY c.id
        ORDER BY c.active DESC, c.name COLLATE NOCASE
    """
    with connection() as conn:
        return pd.read_sql_query(sql, conn)


def get_carrier(carrier_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM carriers WHERE id = ?", (carrier_id,)
        ).fetchone()
    return dict(row) if row else None


def save_carrier(
    *,
    name: str,
    tracking_url: str | None,
    phone: str | None,
    active: bool,
    carrier_id: int | None = None,
) -> int:
    name = (name or "").strip()
    tracking_url = (tracking_url or "").strip() or None
    phone = (phone or "").strip() or None
    if len(name) < 2:
        raise DomainError("Informe o nome da transportadora.")
    if tracking_url and "{tracking}" not in tracking_url:
        raise DomainError(
            "O endereço de rastreio deve conter o marcador {tracking}, "
            "que será substituído pelo código do envio."
        )

    now = _now()
    try:
        with transaction() as conn:
            if carrier_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO carriers
                        (name, tracking_url, phone, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, tracking_url, phone, int(active), now, now),
                )
                return int(cursor.lastrowid)

            exists = conn.execute(
                "SELECT 1 FROM carriers WHERE id = ?", (carrier_id,)
            ).fetchone()
            if exists is None:
                raise DomainError("Transportadora não encontrada.")
            conn.execute(
                """
                UPDATE carriers
                SET name = ?, tracking_url = ?, phone = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, tracking_url, phone, int(active), now, carrier_id),
            )
            return carrier_id
    except sqlite3.IntegrityError as exc:
        raise DomainError("Já existe uma transportadora com este nome.") from exc


def set_carrier_active(carrier_id: int, active: bool) -> None:
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE carriers SET active = ?, updated_at = ? WHERE id = ?",
            (int(active), _now(), carrier_id),
        )
        if cursor.rowcount == 0:
            raise DomainError("Transportadora não encontrada.")


def get_shipment(order_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT s.*, c.name AS carrier_name, c.tracking_url
            FROM shipments s
            LEFT JOIN carriers c ON c.id = s.carrier_id
            WHERE s.order_id = ?
            """,
            (order_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["tracking_link"] = build_tracking_url(
        data.get("tracking_url"), data.get("tracking_code")
    )
    return data


def save_shipment(
    *,
    order_id: int,
    carrier_id: int | None,
    service: str | None,
    tracking_code: str | None,
    expected_delivery: date | None,
    cost: float,
    notes: str | None,
    mark_shipped: bool,
    actor: str,
) -> None:
    service = (service or "").strip() or None
    tracking_code = (tracking_code or "").strip().upper() or None
    notes = (notes or "").strip() or None
    cost = round(float(cost or 0), 2)
    if cost < 0:
        raise DomainError("O frete não pode ser negativo.")
    if tracking_code and len(tracking_code) < 4:
        raise DomainError("Informe um código de rastreio com pelo menos 4 caracteres.")
    if expected_delivery is not None and isinstance(expected_delivery, datetime):
        expected_delivery = expected_delivery.date()

    now = _now()
    with transaction() as conn:
        order = conn.execute(
            "SELECT id, status, number, shipping FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise DomainError("Pedido não encontrado.")
        if order["status"] == "Cancelado":
            raise DomainError("Não é possível preparar envio de um pedido cancelado.")
        if carrier_id is not None:
            carrier = conn.execute(
                "SELECT id, active FROM carriers WHERE id = ?", (carrier_id,)
            ).fetchone()
            if carrier is None:
                raise DomainError("Transportadora não encontrada.")

        shipment = conn.execute(
            "SELECT id, shipped_at, delivered_at FROM shipments WHERE order_id = ?",
            (order_id,),
        ).fetchone()

        shipped_at = shipment["shipped_at"] if shipment else None
        delivered_at = shipment["delivered_at"] if shipment else None
        if mark_shipped and not shipped_at:
            shipped_at = now

        new_order_status = order["status"]
        if order["status"] == "Pago" and mark_shipped:
            new_order_status = "Enviado"
            conn.execute(
                "UPDATE orders SET status = 'Enviado', updated_at = ? WHERE id = ?",
                (now, order_id),
            )
        elif order["status"] == "Entregue" and mark_shipped:
            delivered_at = delivered_at or now

        if shipment is None:
            conn.execute(
                """
                INSERT INTO shipments
                    (order_id, carrier_id, service, tracking_code, shipped_at,
                     expected_delivery, delivered_at, cost, notes, created_at,
                     updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    carrier_id,
                    service,
                    tracking_code,
                    shipped_at,
                    expected_delivery.isoformat() if expected_delivery else None,
                    delivered_at,
                    cost,
                    notes,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE shipments
                SET carrier_id = ?, service = ?, tracking_code = ?, shipped_at = ?,
                    expected_delivery = ?, delivered_at = ?, cost = ?, notes = ?,
                    updated_at = ?
                WHERE order_id = ?
                """,
                (
                    carrier_id,
                    service,
                    tracking_code,
                    shipped_at,
                    expected_delivery.isoformat() if expected_delivery else None,
                    delivered_at,
                    cost,
                    notes,
                    now,
                    order_id,
                ),
            )

        sync_order_document_status(
            conn,
            order_id=order_id,
            new_status=new_order_status,
            actor=actor,
            now=now,
        )


def mark_delivered(
    *, order_id: int, delivered_on: date, actor: str
) -> None:
    if isinstance(delivered_on, datetime):
        delivered_on = delivered_on.date()
    when = datetime.combine(delivered_on, time(hour=12)).isoformat(
        sep=" ", timespec="seconds"
    )
    now = _now()

    with transaction() as conn:
        order = conn.execute(
            "SELECT id, status, number FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise DomainError("Pedido não encontrado.")
        if order["status"] == "Entregue":
            return
        if order["status"] != "Enviado":
            raise DomainError(
                "Marque o pedido como Enviado antes de registrar a entrega."
            )

        shipment = conn.execute(
            "SELECT id, shipped_at FROM shipments WHERE order_id = ?", (order_id,)
        ).fetchone()
        if shipment is None:
            conn.execute(
                """
                INSERT INTO shipments
                    (order_id, carrier_id, service, tracking_code, shipped_at,
                     expected_delivery, delivered_at, cost, notes, created_at,
                     updated_at)
                VALUES (?, NULL, NULL, NULL, ?, NULL, ?, 0, NULL, ?, ?)
                """,
                (order_id, when, when, now, now),
            )
        else:
            conn.execute(
                """
                UPDATE shipments
                SET shipped_at = COALESCE(shipped_at, ?), delivered_at = ?,
                    updated_at = ?
                WHERE order_id = ?
                """,
                (when, when, now, order_id),
            )

        conn.execute(
            "UPDATE orders SET status = 'Entregue', updated_at = ? WHERE id = ?",
            (now, order_id),
        )
        sync_order_document_status(
            conn,
            order_id=order_id,
            new_status="Entregue",
            actor=actor,
            now=now,
        )


def sync_shipment_status(
    conn: sqlite3.Connection, order_id: int, new_status: str, now: str
) -> None:
    """Mantém o envio coerente quando o status muda pela tela de Pedidos."""
    if new_status not in ("Enviado", "Entregue"):
        return

    shipment = conn.execute(
        "SELECT id, shipped_at, delivered_at FROM shipments WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if shipment is None:
        cost = conn.execute(
            "SELECT shipping FROM orders WHERE id = ?", (order_id,)
        ).fetchone()["shipping"]
        conn.execute(
            """
            INSERT INTO shipments
                (order_id, carrier_id, service, tracking_code, shipped_at,
                 expected_delivery, delivered_at, cost, notes, created_at,
                 updated_at)
            VALUES (?, NULL, NULL, NULL, ?, NULL, ?, ?, NULL, ?, ?)
            """,
            (
                order_id,
                now,
                now if new_status == "Entregue" else None,
                round(float(cost or 0), 2),
                now,
                now,
            ),
        )
        return

    conn.execute(
        """
        UPDATE shipments
        SET shipped_at = COALESCE(shipped_at, ?),
            delivered_at = CASE
                WHEN ? = 'Entregue' THEN COALESCE(delivered_at, ?)
                ELSE delivered_at
            END,
            updated_at = ?
        WHERE order_id = ?
        """,
        (now, new_status, now, now, order_id),
    )


def list_fulfillment_orders(
    *, search: str = "", view: str = "Todos", limit: int = 500
) -> pd.DataFrame:
    clauses = ["o.status IN ('Pago', 'Enviado', 'Entregue')"]
    params: list[object] = []

    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(o.number) LIKE ? OR lower(c.name) LIKE ? "
            "OR lower(s.tracking_code) LIKE ?)"
        )
        params.extend([term, term, term])

    if view == "A separar":
        clauses.append("o.status = 'Pago'")
    elif view == "Em trânsito":
        clauses.append("o.status = 'Enviado'")
    elif view == "Atrasados":
        clauses.append(
            "o.status = 'Enviado' AND s.expected_delivery IS NOT NULL "
            "AND date(s.expected_delivery) < date('now')"
        )
    elif view == "Entregues":
        clauses.append("o.status = 'Entregue'")

    sql = f"""
        SELECT o.id AS order_id, o.number, o.status AS order_status, o.total,
               o.shipping, o.created_at, o.updated_at,
               c.name AS customer_name, c.city AS customer_city,
               c.state AS customer_state,
               s.id AS shipment_id, s.carrier_id, s.service,
               s.tracking_code, s.shipped_at, s.expected_delivery,
               s.delivered_at, COALESCE(s.cost, o.shipping) AS shipping_cost,
               s.notes AS shipment_notes,
               cr.name AS carrier_name, cr.tracking_url
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        LEFT JOIN shipments s ON s.order_id = o.id
        LEFT JOIN carriers cr ON cr.id = s.carrier_id
        WHERE {' AND '.join(clauses)}
        ORDER BY
            CASE o.status WHEN 'Pago' THEN 0 WHEN 'Enviado' THEN 1 ELSE 2 END,
            datetime(o.created_at) DESC, o.id DESC
        LIMIT ?
    """
    params.append(int(limit))
    with connection() as conn:
        data = pd.read_sql_query(sql, conn, params=params)

    if data.empty:
        for column in (
            "logistics_status",
            "days_in_transit",
            "days_to_due",
            "on_time",
            "tracking_link",
        ):
            data[column] = None
        return data

    today = date.today()
    statuses: list[str] = []
    days_in_transit: list[int | None] = []
    days_to_due: list[int | None] = []
    on_time: list[bool | None] = []
    links: list[str | None] = []

    for row in data.itertuples():
        expected = pd.to_datetime(row.expected_delivery, errors="coerce")
        shipped = pd.to_datetime(row.shipped_at, errors="coerce")
        delivered = pd.to_datetime(row.delivered_at, errors="coerce")

        if row.order_status == "Entregue":
            status = "Entregue"
        elif (
            row.order_status == "Enviado"
            and not pd.isna(expected)
            and expected.date() < today
        ):
            status = "Atrasado"
        elif row.order_status == "Enviado":
            status = "Em trânsito"
        else:
            status = "A separar"

        statuses.append(status)
        days_in_transit.append(
            None if pd.isna(shipped) else max(0, (today - shipped.date()).days)
        )
        days_to_due.append(
            None if pd.isna(expected) else (expected.date() - today).days
        )
        on_time.append(
            None
            if pd.isna(expected) or pd.isna(delivered)
            else bool(delivered.date() <= expected.date())
        )
        links.append(build_tracking_url(row.tracking_url, row.tracking_code))

    data["logistics_status"] = statuses
    data["days_in_transit"] = days_in_transit
    data["days_to_due"] = days_to_due
    data["on_time"] = on_time
    data["tracking_link"] = links
    return data


def get_logistics_summary(start_date: date, end_date: date) -> dict:
    start = start_date.isoformat()
    end = end_date.isoformat()
    with connection() as conn:
        waiting = int(
            conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status = 'Pago'"
            ).fetchone()[0]
        )
        transit = int(
            conn.execute(
                "SELECT COUNT(*) FROM orders WHERE status = 'Enviado'"
            ).fetchone()[0]
        )
        late = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM orders o
                JOIN shipments s ON s.order_id = o.id
                WHERE o.status = 'Enviado'
                  AND s.expected_delivery IS NOT NULL
                  AND date(s.expected_delivery) < date('now')
                """
            ).fetchone()[0]
        )
        delivered_row = conn.execute(
            """
            SELECT COUNT(*) AS delivered,
                   SUM(CASE WHEN s.expected_delivery IS NOT NULL
                                  AND date(s.delivered_at) <= date(s.expected_delivery)
                            THEN 1 ELSE 0 END) AS on_time,
                   AVG(julianday(s.delivered_at) - julianday(s.shipped_at))
                       AS avg_delivery_days
            FROM shipments s
            JOIN orders o ON o.id = s.order_id
            WHERE o.status = 'Entregue'
              AND s.delivered_at IS NOT NULL
              AND date(s.delivered_at) BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()
        dispatch_row = conn.execute(
            """
            SELECT AVG((julianday(s.shipped_at) - julianday(o.created_at)) * 24)
                       AS avg_dispatch_hours,
                   SUM(COALESCE(s.cost, o.shipping)) AS freight_cost
            FROM shipments s
            JOIN orders o ON o.id = s.order_id
            WHERE s.shipped_at IS NOT NULL
              AND date(s.shipped_at) BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()

    delivered = int(delivered_row["delivered"] or 0)
    on_time = int(delivered_row["on_time"] or 0)
    return {
        "waiting": waiting,
        "transit": transit,
        "late": late,
        "delivered": delivered,
        "on_time": on_time,
        "on_time_rate": (on_time / delivered) if delivered else 0.0,
        "avg_delivery_days": float(delivered_row["avg_delivery_days"] or 0),
        "avg_dispatch_hours": float(dispatch_row["avg_dispatch_hours"] or 0),
        "freight_cost": float(dispatch_row["freight_cost"] or 0),
    }


def get_carrier_performance(start_date: date, end_date: date) -> pd.DataFrame:
    sql = """
        SELECT COALESCE(c.name, 'Sem transportadora') AS carrier_name,
               COUNT(s.id) AS delivered,
               SUM(CASE WHEN s.expected_delivery IS NOT NULL
                              AND date(s.delivered_at) <= date(s.expected_delivery)
                        THEN 1 ELSE 0 END) AS on_time,
               AVG(julianday(s.delivered_at) - julianday(s.shipped_at))
                   AS avg_delivery_days,
               AVG(s.cost) AS avg_freight,
               SUM(s.cost) AS total_freight
        FROM shipments s
        JOIN orders o ON o.id = s.order_id
        LEFT JOIN carriers c ON c.id = s.carrier_id
        WHERE o.status = 'Entregue'
          AND s.delivered_at IS NOT NULL
          AND date(s.delivered_at) BETWEEN ? AND ?
        GROUP BY c.id, c.name
        ORDER BY delivered DESC, carrier_name COLLATE NOCASE
    """
    with connection() as conn:
        data = pd.read_sql_query(sql, conn, params=[start_date.isoformat(), end_date.isoformat()])
    if data.empty:
        return data
    data["on_time_rate"] = data.apply(
        lambda row: (float(row["on_time"] or 0) / float(row["delivered"]))
        if row["delivered"]
        else 0.0,
        axis=1,
    )
    return data
