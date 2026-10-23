"""Controle de estoque, documentos, trânsito e trilha de movimentações."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

import pandas as pd

from lib.database import connection, transaction
from lib import crypto
from lib.errors import DomainError
from lib.invoices import InvoiceData, parse_nfe_xml

STOCK_MOVEMENT_KINDS = (
    "Entrada",
    "Saída",
    "Venda",
    "Cancelamento",
    "Reativação",
    "Exclusão",
    "Ajuste",
    "Saldo inicial",
    "Transferência",
    "Recebimento",
    "Estorno",
)
STOCK_MOVEMENT_STATUSES = ("A separar", "Em trânsito", "Concluído")
STOCK_PENDING_STATUSES = ("A separar", "Em trânsito")
STOCK_DOCUMENT_KINDS = (
    "Entrada",
    "Saída",
    "Transferência",
    "Venda",
    "Cancelamento",
    "Reativação",
    "Exclusão",
    "Ajuste",
    "Saldo inicial",
    "Recebimento",
    "Estorno",
)
STOCK_DOCUMENT_STATUSES = (
    "A separar",
    "Em trânsito",
    "Recebido",
    "Concluído",
    "Divergente",
    "Estornado",
    "Cancelado",
)
STOCK_TRANSIT_STATUSES = ("Em trânsito", "Parcial", "Recebido", "Divergente", "Cancelado")
STOCK_ENTITY_KINDS = ("Filial", "Fornecedor")
STOCK_PARTY_KINDS = ("Cliente", *STOCK_ENTITY_KINDS, "Estoque interno")
INTERNAL_STOCK = "Estoque interno"
INTERNAL_LOCATION = "Almoxarifado"


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def stock_status_for_order(order_status: str) -> str:
    """Status inicial da movimentação de estoque conforme o pedido."""
    if order_status == "Enviado":
        return "Em trânsito"
    if order_status in ("Pendente", "Pago"):
        return "A separar"
    return "Concluído"


def _movement_status_for_document(status: str) -> str:
    if status == "A separar":
        return "A separar"
    if status == "Em trânsito":
        return "Em trânsito"
    return "Concluído"


def _location(city: str | None, state: str | None) -> str | None:
    city = (city or "").strip()
    state = (state or "").strip()
    if city and state:
        return f"{city}/{state}"
    return city or state or None


def _resolve_stock_entity(
    conn: sqlite3.Connection,
    entity_kind: str | None,
    entity_id: int | None,
) -> tuple[str, int | None, str, str | None]:
    """Resolve a entidade e devolve os dados que ficam gravados no histórico."""
    kind = (entity_kind or INTERNAL_STOCK).strip() or INTERNAL_STOCK
    if kind == INTERNAL_STOCK:
        return kind, None, INTERNAL_STOCK, INTERNAL_LOCATION
    if kind not in STOCK_PARTY_KINDS:
        raise DomainError("Tipo de entidade de estoque inválido.")
    if entity_id is None:
        raise DomainError(f"Selecione a entidade do tipo {kind}.")

    if kind == "Cliente":
        row = conn.execute(
            "SELECT id, name, city, state FROM customers WHERE id = ?",
            (int(entity_id),),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, name, city, state, active
            FROM stock_entities
            WHERE id = ? AND kind = ?
            """,
            (int(entity_id), kind),
        ).fetchone()
        if row is not None and not row["active"]:
            raise DomainError(
                f"A entidade do tipo {kind} está inativa e não pode receber "
                "novos movimentos."
            )
    if row is None:
        raise DomainError(f"{kind} não encontrada para a movimentação de estoque.")
    return kind, int(row["id"]), row["name"], _location(row["city"], row["state"])


def _document_parties(
    conn: sqlite3.Connection,
    *,
    kind: str,
    entity_kind: str,
    entity_id: int | None,
) -> tuple[
    tuple[str, int | None, str, str | None],
    tuple[str, int | None, str, str | None],
]:
    """Devolve origem e destino de um documento manual."""
    party = _resolve_stock_entity(conn, entity_kind, entity_id)
    internal = (INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION)
    if kind == "Entrada":
        return party, internal
    if kind in ("Saída", "Transferência"):
        if kind == "Transferência" and party[0] == INTERNAL_STOCK:
            raise DomainError(
                "Selecione uma filial ou fornecedor como destino da transferência."
            )
        return internal, party
    raise DomainError("Tipo de documento de movimentação inválido.")


def _save_stock_invoice(
    conn: sqlite3.Connection,
    invoice: InvoiceData,
    actor: str,
    created_at: str,
) -> int:
    """Persiste a NF-e e reutiliza o registro quando a chave já existe."""
    if invoice.access_key:
        existing = conn.execute(
            "SELECT id FROM stock_invoices WHERE access_key = ?",
            (invoice.access_key,),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO stock_invoices
            (number, series, access_key, issued_at, issuer_name,
             recipient_name, total_value, xml, file_name, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice.number,
            invoice.series,
            invoice.access_key,
            invoice.issued_at,
            invoice.issuer_name,
            invoice.recipient_name,
            invoice.total_value,
            invoice.xml,
            invoice.file_name,
            created_at,
            (actor or "").strip() or "Sistema",
        ),
    )
    return int(cursor.lastrowid)


def _log_status(
    conn: sqlite3.Connection,
    *,
    document_id: int | None = None,
    movement_id: int | None = None,
    transit_id: int | None = None,
    from_status: str | None,
    to_status: str,
    actor: str,
    note: str | None = None,
    created_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO stock_status_history
            (document_id, movement_id, transit_id, from_status, to_status,
             note, actor, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            movement_id,
            transit_id,
            from_status,
            to_status,
            (note or "").strip() or None,
            (actor or "").strip() or "Sistema",
            created_at or _now(),
        ),
    )


def _insert_document_header(
    conn: sqlite3.Connection,
    *,
    kind: str,
    status: str,
    source: tuple[str, int | None, str, str | None],
    destination: tuple[str, int | None, str, str | None],
    reason: str | None,
    notes: str | None,
    actor: str,
    created_at: str,
    order_id: int | None = None,
    invoice_id: int | None = None,
    parent_document_id: int | None = None,
    reversal_of_document_id: int | None = None,
    log_initial: bool = True,
) -> int:
    if kind not in STOCK_DOCUMENT_KINDS:
        raise DomainError("Tipo de documento de movimentação inválido.")
    if status not in STOCK_DOCUMENT_STATUSES:
        raise DomainError("Status do documento de movimentação inválido.")
    source_kind, source_id, source_name, source_location = source
    destination_kind, destination_id, destination_name, destination_location = destination
    cursor = conn.execute(
        """
        INSERT INTO stock_documents
            (number, kind, status, source_kind, source_id, source_name,
             source_location, destination_kind, destination_id,
             destination_name, destination_location, reason, notes, order_id,
             invoice_id, parent_document_id, reversal_of_document_id,
             created_by, created_at, updated_at, confirmed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"TMP-{uuid.uuid4().hex}",
            kind,
            status,
            source_kind,
            source_id,
            source_name,
            source_location,
            destination_kind,
            destination_id,
            destination_name,
            destination_location,
            (reason or "").strip() or None,
            (notes or "").strip() or None,
            order_id,
            invoice_id,
            parent_document_id,
            reversal_of_document_id,
            (actor or "").strip() or "Sistema",
            created_at,
            created_at,
            created_at
            if status in ("Concluído", "Recebido", "Divergente")
            else None,
        ),
    )
    document_id = int(cursor.lastrowid)
    try:
        year = datetime.fromisoformat(created_at).year
    except (TypeError, ValueError):
        year = datetime.now().year
    conn.execute(
        "UPDATE stock_documents SET number = ? WHERE id = ?",
        (f"MOV-{year}-{document_id:04d}", document_id),
    )
    if log_initial:
        _log_status(
            conn,
            document_id=document_id,
            from_status=None,
            to_status=status,
            actor=actor,
            note="Documento criado",
            created_at=created_at,
        )
    return document_id


def _insert_document_item(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    product: dict | sqlite3.Row,
    quantity: int,
    unit_cost: float | None,
    notes: str | None = None,
) -> int:
    quantity = int(quantity)
    if quantity <= 0:
        raise DomainError("A quantidade dos itens deve ser maior que zero.")
    cost = round(float(unit_cost or 0), 2)
    total = round(quantity * cost, 2)
    cursor = conn.execute(
        """
        INSERT INTO stock_document_items
            (document_id, product_id, product_sku, product_name, quantity,
             unit_cost, total_cost, received_quantity, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            document_id,
            int(product["id"]),
            product["sku"],
            product["name"],
            quantity,
            cost,
            total,
            (notes or "").strip() or None,
        ),
    )
    return int(cursor.lastrowid)


def _create_transit(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    document_item_id: int,
    product: dict | sqlite3.Row,
    direction: str,
    quantity: int,
    source: tuple[str, int | None, str, str | None],
    destination: tuple[str, int | None, str, str | None],
    actor: str,
    created_at: str,
) -> int:
    if direction not in ("Entrada", "Transferência"):
        raise DomainError("Direção de trânsito inválida.")
    source_kind, source_id, source_name, source_location = source
    destination_kind, destination_id, destination_name, destination_location = destination
    cursor = conn.execute(
        """
        INSERT INTO stock_transits
            (document_id, document_item_id, product_id, product_sku, product_name,
             direction, quantity, received_quantity, source_kind, source_id,
             source_name, source_location, destination_kind, destination_id,
             destination_name, destination_location, status, shipped_at,
             received_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 'Em trânsito', ?,
                NULL, ?, ?)
        """,
        (
            document_id,
            document_item_id,
            int(product["id"]),
            product["sku"],
            product["name"],
            direction,
            int(quantity),
            source_kind,
            source_id,
            source_name,
            source_location,
            destination_kind,
            destination_id,
            destination_name,
            destination_location,
            created_at,
            created_at,
            created_at,
        ),
    )
    transit_id = int(cursor.lastrowid)
    _log_status(
        conn,
        transit_id=transit_id,
        from_status=None,
        to_status="Em trânsito",
        actor=actor,
        note="Material em trânsito",
        created_at=created_at,
    )
    return transit_id


def _set_document_status(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    new_status: str,
    actor: str,
    note: str | None = None,
    created_at: str | None = None,
    extra_sql: str = "",
    extra_params: tuple = (),
) -> bool:
    if new_status not in STOCK_DOCUMENT_STATUSES:
        raise DomainError("Status do documento de movimentação inválido.")
    current = conn.execute(
        "SELECT status FROM stock_documents WHERE id = ?", (document_id,)
    ).fetchone()
    if current is None:
        raise DomainError("Documento de movimentação não encontrado.")
    old_status = current["status"]
    if old_status == new_status:
        return False
    when = created_at or _now()
    conn.execute(
        f"""
        UPDATE stock_documents
        SET status = ?, updated_at = ?,
            confirmed_at = CASE
                WHEN ? IN ('Concluído', 'Recebido', 'Divergente')
                THEN COALESCE(confirmed_at, ?)
                ELSE confirmed_at
            END,
            received_at = CASE
                WHEN ? IN ('Recebido', 'Divergente')
                THEN COALESCE(received_at, ?)
                ELSE received_at
            END
            {extra_sql}
        WHERE id = ?
        """,
        (new_status, when, new_status, when, new_status, when, *extra_params, document_id),
    )
    conn.execute(
        "UPDATE stock_movements SET status = ? WHERE document_id = ?",
        (_movement_status_for_document(new_status), document_id),
    )
    _log_status(
        conn,
        document_id=document_id,
        from_status=old_status,
        to_status=new_status,
        actor=actor,
        note=note,
        created_at=when,
    )
    return True


def _record_movement_row(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    document_item_id: int,
    product: dict | sqlite3.Row,
    quantity: int,
    kind: str,
    balance_before: int,
    balance_after: int,
    unit_cost: float,
    entity: tuple[str, int | None, str, str | None],
    status: str,
    order_id: int | None,
    invoice_id: int | None,
    reason: str | None,
    actor: str,
    created_at: str,
    reversal_of_id: int | None = None,
    transit_id: int | None = None,
) -> int:
    entity_kind, entity_id, entity_name, entity_location = entity
    total_cost = round(abs(int(quantity)) * float(unit_cost or 0), 2)
    cursor = conn.execute(
        """
        INSERT INTO stock_movements
            (product_id, product_sku, product_name, order_id, document_id,
             document_item_id, kind, quantity, balance_before, balance_after,
             unit_cost, total_cost, entity_kind, entity_id, entity_name,
             entity_location, status, invoice_id, reversal_of_id, transit_id,
             reason, actor, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(product["id"]),
            product["sku"],
            product["name"],
            order_id,
            document_id,
            document_item_id,
            kind,
            int(quantity),
            int(balance_before),
            int(balance_after),
            round(float(unit_cost or 0), 2),
            total_cost,
            entity_kind,
            entity_id,
            entity_name,
            entity_location,
            status,
            invoice_id,
            reversal_of_id,
            transit_id,
            (reason or "").strip() or None,
            (actor or "").strip() or "Sistema",
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def record_stock_movement(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    quantity: int,
    kind: str,
    balance_after: int,
    reason: str | None = None,
    actor: str = "Sistema",
    order_id: int | None = None,
    entity_kind: str = INTERNAL_STOCK,
    entity_id: int | None = None,
    status: str = "Concluído",
    invoice_id: int | None = None,
    created_at: str | None = None,
    document_id: int | None = None,
    document_item_id: int | None = None,
    balance_before: int | None = None,
    unit_cost: float | None = None,
    total_cost: float | None = None,
    reversal_of_id: int | None = None,
    transit_id: int | None = None,
) -> int:
    """Registra uma alteração de estoque sem abrir uma nova transação.

    Quando nenhum documento é informado, um documento de um item é criado
    automaticamente. Isso garante que toda movimentação — inclusive ajustes
    feitos pelo cadastro de produtos — faça parte do mesmo livro-razão.
    """
    if kind not in STOCK_MOVEMENT_KINDS:
        raise DomainError("Tipo de movimentação de estoque inválido.")
    status = (status or "Concluído").strip()
    if status not in STOCK_MOVEMENT_STATUSES:
        raise DomainError("Status inicial da movimentação inválido.")

    product = conn.execute(
        "SELECT id, sku, name, cost FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if product is None:
        raise DomainError("Produto não encontrado para registrar a movimentação.")

    entity = _resolve_stock_entity(conn, entity_kind, entity_id)
    when = created_at or _now()
    quantity = int(quantity)
    balance_after = int(balance_after)
    before = (
        int(balance_before)
        if balance_before is not None
        else balance_after - quantity
    )
    cost = round(float(unit_cost if unit_cost is not None else (product["cost"] or 0)), 2)
    total = (
        round(float(total_cost), 2)
        if total_cost is not None
        else round(abs(quantity) * cost, 2)
    )

    if document_id is None:
        source, destination = (
            (entity, (INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION))
            if quantity >= 0
            else ((INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION), entity)
        )
        document_id = _insert_document_header(
            conn,
            kind=kind,
            status=status,
            source=source,
            destination=destination,
            reason=reason,
            notes=None,
            actor=actor,
            created_at=when,
            order_id=order_id,
            invoice_id=invoice_id,
        )
        document_item_id = _insert_document_item(
            conn,
            document_id=document_id,
            product=product,
            quantity=abs(quantity),
            unit_cost=cost,
        )
    elif document_item_id is None:
        document_item_id = _insert_document_item(
            conn,
            document_id=document_id,
            product=product,
            quantity=abs(quantity),
            unit_cost=cost,
        )

    movement_id = _record_movement_row(
        conn,
        document_id=document_id,
        document_item_id=int(document_item_id),
        product=product,
        quantity=quantity,
        kind=kind,
        balance_before=before,
        balance_after=balance_after,
        unit_cost=cost,
        entity=entity,
        status=status,
        order_id=order_id,
        invoice_id=invoice_id,
        reason=reason,
        actor=actor,
        created_at=when,
        reversal_of_id=reversal_of_id,
        transit_id=transit_id,
    )
    if total_cost is None:
        conn.execute(
            "UPDATE stock_movements SET total_cost = ? WHERE id = ?",
            (total, movement_id),
        )
    return movement_id


def _load_product(conn: sqlite3.Connection, product_id: int) -> sqlite3.Row:
    product = conn.execute(
        "SELECT id, sku, name, stock, cost, active FROM products WHERE id = ?",
        (int(product_id),),
    ).fetchone()
    if product is None:
        raise DomainError("Produto não encontrado.")
    return product


def _apply_stock_in(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    document_item_id: int,
    product: sqlite3.Row,
    quantity: int,
    unit_cost: float,
    source: tuple[str, int | None, str, str | None],
    status: str,
    order_id: int | None,
    invoice_id: int | None,
    reason: str | None,
    actor: str,
    created_at: str,
    movement_kind: str = "Entrada",
) -> int:
    old_stock = int(product["stock"])
    old_cost = float(product["cost"] or 0)
    new_stock = old_stock + int(quantity)
    new_cost = old_cost
    if unit_cost > 0 and new_stock > 0:
        new_cost = round(
            (old_stock * old_cost + int(quantity) * float(unit_cost)) / new_stock,
            2,
        )
    conn.execute(
        "UPDATE products SET stock = ?, cost = ?, updated_at = ? WHERE id = ?",
        (new_stock, new_cost, created_at, int(product["id"])),
    )
    return _record_movement_row(
        conn,
        document_id=document_id,
        document_item_id=document_item_id,
        product=product,
        quantity=int(quantity),
        kind=movement_kind,
        balance_before=old_stock,
        balance_after=new_stock,
        unit_cost=unit_cost,
        entity=source,
        status=_movement_status_for_document(status),
        order_id=order_id,
        invoice_id=invoice_id,
        reason=reason,
        actor=actor,
        created_at=created_at,
    )


def _apply_stock_out(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    document_item_id: int,
    product: sqlite3.Row,
    quantity: int,
    unit_cost: float,
    destination: tuple[str, int | None, str, str | None],
    status: str,
    order_id: int | None,
    invoice_id: int | None,
    reason: str | None,
    actor: str,
    created_at: str,
    movement_kind: str = "Saída",
) -> int:
    old_stock = int(product["stock"])
    quantity = int(quantity)
    if old_stock < quantity:
        raise DomainError(
            f"Estoque insuficiente para {product['name']}. "
            f"Disponível: {old_stock} un."
        )
    new_stock = old_stock - quantity
    conn.execute(
        "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
        (new_stock, created_at, int(product["id"])),
    )
    return _record_movement_row(
        conn,
        document_id=document_id,
        document_item_id=document_item_id,
        product=product,
        quantity=-quantity,
        kind=movement_kind,
        balance_before=old_stock,
        balance_after=new_stock,
        unit_cost=unit_cost,
        entity=destination,
        status=_movement_status_for_document(status),
        order_id=order_id,
        invoice_id=invoice_id,
        reason=reason,
        actor=actor,
        created_at=created_at,
    )


def create_stock_document(
    *,
    kind: str,
    items: list[dict],
    reason: str,
    actor: str,
    entity_kind: str = INTERNAL_STOCK,
    entity_id: int | None = None,
    status: str = "Concluído",
    invoice_xml: bytes | str | None = None,
    invoice_file_name: str | None = None,
    notes: str | None = None,
) -> int:
    """Cria uma movimentação manual com cabeçalho e múltiplos itens."""
    if kind not in ("Entrada", "Saída", "Transferência"):
        raise DomainError("Escolha entrada, saída ou transferência de estoque.")
    status = (status or "Concluído").strip()
    if status not in STOCK_DOCUMENT_STATUSES:
        raise DomainError("Status inicial do documento inválido.")
    if kind == "Entrada" and status not in ("Em trânsito", "Concluído"):
        raise DomainError("Entradas podem ficar em trânsito ou ser concluídas.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise DomainError("Informe o motivo da movimentação de estoque.")
    if not items:
        raise DomainError("Adicione pelo menos um item à movimentação.")

    normalized: list[dict] = []
    seen: set[int] = set()
    for raw in items:
        product_id = int(raw.get("product_id") or 0)
        quantity = int(raw.get("quantity") or 0)
        if product_id <= 0:
            raise DomainError("Selecione o produto de todos os itens.")
        if product_id in seen:
            raise DomainError("Não repita o mesmo produto no documento.")
        if quantity <= 0:
            raise DomainError("A quantidade dos itens deve ser maior que zero.")
        seen.add(product_id)
        normalized.append(
            {
                "product_id": product_id,
                "quantity": quantity,
                "unit_cost": raw.get("unit_cost"),
            }
        )

    invoice = (
        parse_nfe_xml(invoice_xml, invoice_file_name)
        if invoice_xml is not None
        else None
    )
    now = _now()

    with transaction() as conn:
        source, destination = _document_parties(
            conn, kind=kind, entity_kind=entity_kind, entity_id=entity_id
        )
        products: list[tuple[sqlite3.Row, dict]] = []
        for item in normalized:
            product = _load_product(conn, item["product_id"])
            if not product["active"]:
                raise DomainError(f"O produto {product['name']} está inativo.")
            products.append((product, item))

        stock_effect = not (kind == "Transferência" and status == "A separar")
        stock_effect = stock_effect and not (
            kind == "Entrada" and status == "Em trânsito"
        )
        if stock_effect and kind in ("Saída", "Transferência"):
            for product, item in products:
                if int(product["stock"]) < item["quantity"]:
                    raise DomainError(
                        f"Estoque insuficiente para {product['name']}. "
                        f"Disponível: {int(product['stock'])} un."
                    )

        invoice_id = (
            _save_stock_invoice(conn, invoice, actor, now)
            if invoice is not None
            else None
        )
        document_id = _insert_document_header(
            conn,
            kind=kind,
            status=status,
            source=source,
            destination=destination,
            reason=reason,
            notes=notes,
            actor=actor,
            created_at=now,
            invoice_id=invoice_id,
        )

        for product, item in products:
            quantity = int(item["quantity"])
            provided_cost = item.get("unit_cost")
            unit_cost = (
                round(float(provided_cost), 2)
                if kind == "Entrada" and provided_cost is not None
                else round(float(product["cost"] or 0), 2)
            )
            item_id = _insert_document_item(
                conn,
                document_id=document_id,
                product=product,
                quantity=quantity,
                unit_cost=unit_cost,
            )

            if kind == "Entrada":
                if status == "Em trânsito":
                    _create_transit(
                        conn,
                        document_id=document_id,
                        document_item_id=item_id,
                        product=product,
                        direction="Entrada",
                        quantity=quantity,
                        source=source,
                        destination=destination,
                        actor=actor,
                        created_at=now,
                    )
                else:
                    _apply_stock_in(
                        conn,
                        document_id=document_id,
                        document_item_id=item_id,
                        product=product,
                        quantity=quantity,
                        unit_cost=unit_cost,
                        source=source,
                        status=status,
                        order_id=None,
                        invoice_id=invoice_id,
                        reason=reason,
                        actor=actor,
                        created_at=now,
                    )
            elif kind == "Transferência":
                if status == "A separar":
                    continue
                _apply_stock_out(
                    conn,
                    document_id=document_id,
                    document_item_id=item_id,
                    product=product,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    destination=destination,
                    status=status,
                    order_id=None,
                    invoice_id=invoice_id,
                    reason=reason,
                    actor=actor,
                    created_at=now,
                    movement_kind="Transferência",
                )
                if status == "Em trânsito":
                    _create_transit(
                        conn,
                        document_id=document_id,
                        document_item_id=item_id,
                        product=product,
                        direction="Transferência",
                        quantity=quantity,
                        source=source,
                        destination=destination,
                        actor=actor,
                        created_at=now,
                    )
            else:
                _apply_stock_out(
                    conn,
                    document_id=document_id,
                    document_item_id=item_id,
                    product=product,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    destination=destination,
                    status=status,
                    order_id=None,
                    invoice_id=invoice_id,
                    reason=reason,
                    actor=actor,
                    created_at=now,
                )

        return document_id


def adjust_stock(
    *,
    product_id: int,
    direction: str,
    quantity: int,
    reason: str,
    actor: str,
    entity_kind: str = INTERNAL_STOCK,
    entity_id: int | None = None,
    status: str = "Concluído",
    invoice_xml: bytes | str | None = None,
    invoice_file_name: str | None = None,
    unit_cost: float | None = None,
) -> int:
    """Compatibilidade: cria um documento de um item e devolve o saldo."""
    if direction not in ("Entrada", "Saída"):
        raise DomainError("Escolha entrada ou saída de estoque.")
    if direction == "Entrada":
        status = "Concluído"
    document_id = create_stock_document(
        kind=direction,
        items=[
            {
                "product_id": product_id,
                "quantity": quantity,
                "unit_cost": unit_cost,
            }
        ],
        reason=reason,
        actor=actor,
        entity_kind=entity_kind,
        entity_id=entity_id,
        status=status,
        invoice_xml=invoice_xml,
        invoice_file_name=invoice_file_name,
    )
    with connection() as conn:
        row = conn.execute(
            "SELECT balance_after FROM stock_movements WHERE document_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    return int(row["balance_after"]) if row else 0


def ship_stock_document(document_id: int, actor: str = "Sistema") -> None:
    """Despacha uma transferência que estava aguardando separação."""
    now = _now()
    with transaction() as conn:
        document = conn.execute(
            "SELECT * FROM stock_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if document is None:
            raise DomainError("Documento de movimentação não encontrado.")
        if document["kind"] != "Transferência":
            raise DomainError("Somente transferências podem ser despachadas.")
        if document["status"] != "A separar":
            raise DomainError("Esta transferência não está aguardando despacho.")
        items = conn.execute(
            "SELECT * FROM stock_document_items WHERE document_id = ? ORDER BY id",
            (document_id,),
        ).fetchall()
        source = (
            document["source_kind"],
            document["source_id"],
            document["source_name"],
            document["source_location"],
        )
        destination = (
            document["destination_kind"],
            document["destination_id"],
            document["destination_name"],
            document["destination_location"],
        )
        for item in items:
            product = _load_product(conn, int(item["product_id"]))
            _apply_stock_out(
                conn,
                document_id=document_id,
                document_item_id=int(item["id"]),
                product=product,
                quantity=int(item["quantity"]),
                unit_cost=float(item["unit_cost"] or 0),
                destination=destination,
                status="Em trânsito",
                order_id=document["order_id"],
                invoice_id=document["invoice_id"],
                reason=document["reason"],
                actor=actor,
                created_at=now,
                movement_kind="Transferência",
            )
            _create_transit(
                conn,
                document_id=document_id,
                document_item_id=int(item["id"]),
                product=product,
                direction="Transferência",
                quantity=int(item["quantity"]),
                source=source,
                destination=destination,
                actor=actor,
                created_at=now,
            )
        _set_document_status(
            conn,
            document_id=document_id,
            new_status="Em trânsito",
            actor=actor,
            note="Transferência despachada",
            created_at=now,
        )


def advance_stock_document(
    document_id: int, new_status: str, actor: str = "Sistema"
) -> None:
    """Avança o status de documentos sem recebimento (vendas e saídas)."""
    now = _now()
    with transaction() as conn:
        document = conn.execute(
            "SELECT * FROM stock_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if document is None:
            raise DomainError("Documento de movimentação não encontrado.")
        if document["kind"] == "Transferência" and document["status"] == "A separar":
            if new_status == "Em trânsito":
                raise DomainError("Use a ação Despachar para esta transferência.")
            raise DomainError("Despache a transferência antes de alterar o status.")
        if document["kind"] in ("Entrada", "Transferência") and new_status == "Concluído":
            pending = conn.execute(
                "SELECT COUNT(*) FROM stock_transits "
                "WHERE document_id = ? AND status IN ('Em trânsito', 'Parcial')",
                (document_id,),
            ).fetchone()[0]
            if pending:
                raise DomainError(
                    "Use o recebimento no trânsito para concluir este documento."
                )
        _set_document_status(
            conn,
            document_id=document_id,
            new_status=new_status,
            actor=actor,
            note="Status atualizado manualmente",
            created_at=now,
        )


def receive_stock_transit(
    transit_id: int,
    *,
    received_quantity: int,
    actor: str = "Sistema",
    note: str | None = None,
    close_divergence: bool = False,
) -> None:
    """Confirma o recebimento de um item em trânsito.

    Em entradas, a quantidade recebida é somada ao estoque central. Em
    transferências, o recebimento é documental: o saldo já saiu da origem.
    """
    received_quantity = int(received_quantity)
    if received_quantity < 0:
        raise DomainError("A quantidade recebida não pode ser negativa.")
    now = _now()
    with transaction() as conn:
        transit = conn.execute(
            """
            SELECT st.*, sd.kind AS document_kind, sd.order_id,
                   sd.invoice_id, sd.reason AS document_reason
            FROM stock_transits st
            JOIN stock_documents sd ON sd.id = st.document_id
            WHERE st.id = ?
            """,
            (transit_id,),
        ).fetchone()
        if transit is None:
            raise DomainError("Item em trânsito não encontrado.")
        if transit["status"] not in ("Em trânsito", "Parcial"):
            raise DomainError("Este item não está mais em trânsito.")
        remaining = int(transit["quantity"]) - int(transit["received_quantity"])
        if received_quantity > remaining:
            raise DomainError(
                f"A quantidade recebida supera o saldo em trânsito ({remaining} un.)."
            )
        if received_quantity <= 0 and not close_divergence:
            raise DomainError("Informe uma quantidade recebida maior que zero.")
        if (
            close_divergence
            and received_quantity == 0
            and int(transit["received_quantity"]) == 0
        ):
            pass

        item = conn.execute(
            "SELECT * FROM stock_document_items WHERE id = ?",
            (int(transit["document_item_id"]),),
        ).fetchone()
        if item is None:
            raise DomainError("Item do documento não encontrado.")
        product = _load_product(conn, int(transit["product_id"]))
        source = (
            transit["source_kind"],
            transit["source_id"],
            transit["source_name"],
            transit["source_location"],
        )
        if transit["document_kind"] == "Entrada" and received_quantity > 0:
            _apply_stock_in(
                conn,
                document_id=int(transit["document_id"]),
                document_item_id=int(transit["document_item_id"]),
                product=product,
                quantity=received_quantity,
                unit_cost=float(item["unit_cost"] or 0),
                source=source,
                status="Concluído",
                order_id=transit["order_id"],
                invoice_id=transit["invoice_id"],
                reason=transit["document_reason"],
                actor=actor,
                created_at=now,
                movement_kind="Recebimento",
            )

        new_received = int(transit["received_quantity"]) + received_quantity
        if new_received >= int(transit["quantity"]):
            new_status = "Recebido"
        elif close_divergence:
            new_status = "Divergente"
        else:
            new_status = "Parcial"
        conn.execute(
            """
            UPDATE stock_transits
            SET received_quantity = ?, status = ?, received_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_received,
                new_status,
                now if new_status in ("Recebido", "Divergente") else None,
                now,
                transit_id,
            ),
        )
        conn.execute(
            "UPDATE stock_document_items SET received_quantity = ? WHERE id = ?",
            (new_received, int(transit["document_item_id"])),
        )
        _log_status(
            conn,
            transit_id=transit_id,
            from_status=transit["status"],
            to_status=new_status,
            actor=actor,
            note=note or f"Recebimento de {received_quantity} un.",
            created_at=now,
        )
        if new_received > 0:
            conn.execute(
                "UPDATE stock_movements SET status = 'Concluído' "
                "WHERE document_id = ? AND document_item_id = ? "
                "AND kind = 'Transferência'",
                (int(transit["document_id"]), int(transit["document_item_id"])),
            )

        statuses = [
            row["status"]
            for row in conn.execute(
                "SELECT status FROM stock_transits WHERE document_id = ?",
                (int(transit["document_id"]),),
            ).fetchall()
        ]
        if any(status == "Divergente" for status in statuses):
            document_status = "Divergente"
        elif statuses and all(status == "Recebido" for status in statuses):
            document_status = "Recebido"
        else:
            document_status = "Em trânsito"
        _set_document_status(
            conn,
            document_id=int(transit["document_id"]),
            new_status=document_status,
            actor=actor,
            note=note or "Recebimento confirmado",
            created_at=now,
        )


def reverse_stock_document(
    document_id: int, *, actor: str = "Sistema", reason: str | None = None
) -> int:
    """Estorna um documento por meio de outro documento, sem apagar o original."""
    now = _now()
    with transaction() as conn:
        document = conn.execute(
            "SELECT * FROM stock_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if document is None:
            raise DomainError("Documento de movimentação não encontrado.")
        if document["kind"] == "Estorno":
            raise DomainError("Um estorno não pode ser estornado.")
        if document["kind"] not in ("Entrada", "Saída", "Transferência", "Ajuste"):
            raise DomainError(
                "Este tipo de documento não pode ser estornado. "
                "Corrija o pedido ou registre um novo movimento."
            )
        if document["order_id"] is not None:
            raise DomainError(
                "Documentos de pedidos devem ser corrigidos pelo cancelamento do pedido."
            )
        if document["status"] in ("Estornado", "Cancelado"):
            raise DomainError("Este documento já foi encerrado.")
        if document["reversed_by_document_id"] is not None:
            raise DomainError("Este documento já possui um estorno.")

        items = conn.execute(
            "SELECT * FROM stock_document_items WHERE document_id = ? ORDER BY id",
            (document_id,),
        ).fetchall()
        if not items:
            raise DomainError("O documento não possui itens.")

        stock_changes: list[tuple[sqlite3.Row, int, float, sqlite3.Row | None]] = []
        for item in items:
            movement = conn.execute(
                "SELECT * FROM stock_movements WHERE document_item_id = ? "
                "ORDER BY id LIMIT 1",
                (int(item["id"]),),
            ).fetchone()
            if document["kind"] == "Ajuste" and movement is not None:
                delta = -int(movement["quantity"])
            elif document["kind"] == "Entrada":
                if document["status"] in ("Em trânsito", "A separar"):
                    delta = 0
                else:
                    received = int(item["received_quantity"] or 0)
                    delta = -(received if received > 0 else int(item["quantity"]))
            elif (
                document["kind"] == "Transferência"
                and document["status"] == "A separar"
            ):
                delta = 0
            else:
                delta = int(item["quantity"])
            stock_changes.append(
                (item, delta, float(item["unit_cost"] or 0), movement)
            )

        for item, delta, _, _ in stock_changes:
            if delta < 0:
                product = _load_product(conn, int(item["product_id"]))
                if int(product["stock"]) < abs(delta):
                    raise DomainError(
                        f"Estoque insuficiente para estornar {product['name']}. "
                        f"Disponível: {int(product['stock'])} un."
                    )

        source = (
            document["destination_kind"],
            document["destination_id"],
            document["destination_name"],
            document["destination_location"],
        )
        destination = (
            document["source_kind"],
            document["source_id"],
            document["source_name"],
            document["source_location"],
        )
        reversal_id = _insert_document_header(
            conn,
            kind="Estorno",
            status="Concluído",
            source=source,
            destination=destination,
            reason=reason or f"Estorno de {document['number']}",
            notes=f"Estorno do documento {document['number']}",
            actor=actor,
            created_at=now,
            order_id=None,
            invoice_id=document["invoice_id"],
            parent_document_id=document_id,
            reversal_of_document_id=document_id,
        )

        for item, delta, unit_cost, movement in stock_changes:
            reversal_item_id = _insert_document_item(
                conn,
                document_id=reversal_id,
                product={
                    "id": item["product_id"],
                    "sku": item["product_sku"],
                    "name": item["product_name"],
                },
                quantity=abs(delta) if delta != 0 else int(item["quantity"]),
                unit_cost=unit_cost,
            )
            if delta == 0:
                continue
            product = _load_product(conn, int(item["product_id"]))
            old_stock = int(product["stock"])
            new_stock = old_stock + delta
            conn.execute(
                "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
                (new_stock, now, int(product["id"])),
            )
            entity = (
                (
                    movement["entity_kind"],
                    movement["entity_id"],
                    movement["entity_name"],
                    movement["entity_location"],
                )
                if movement is not None
                else (INTERNAL_STOCK, None, INTERNAL_STOCK, INTERNAL_LOCATION)
            )
            _record_movement_row(
                conn,
                document_id=reversal_id,
                document_item_id=reversal_item_id,
                product=product,
                quantity=delta,
                kind="Estorno",
                balance_before=old_stock,
                balance_after=new_stock,
                unit_cost=unit_cost,
                entity=entity,
                status="Concluído",
                order_id=None,
                invoice_id=document["invoice_id"],
                reason=reason or f"Estorno de {document['number']}",
                actor=actor,
                created_at=now,
                reversal_of_id=int(movement["id"]) if movement is not None else None,
            )

        for transit in conn.execute(
            "SELECT id, status FROM stock_transits "
            "WHERE document_id = ? AND status IN ('Em trânsito', 'Parcial')",
            (document_id,),
        ).fetchall():
            conn.execute(
                "UPDATE stock_transits SET status = 'Cancelado', updated_at = ? "
                "WHERE id = ?",
                (now, int(transit["id"])),
            )
            _log_status(
                conn,
                transit_id=int(transit["id"]),
                from_status=transit["status"],
                to_status="Cancelado",
                actor=actor,
                note="Trânsito cancelado pelo estorno",
                created_at=now,
            )

        _set_document_status(
            conn,
            document_id=document_id,
            new_status="Estornado",
            actor=actor,
            note=reason or f"Estornado pelo documento {reversal_id}",
            created_at=now,
            extra_sql=", reversed_by_document_id = ?",
            extra_params=(reversal_id,),
        )
        return reversal_id


def open_stock_document(
    conn: sqlite3.Connection,
    *,
    kind: str,
    status: str,
    source: tuple[str, int | None, str, str | None],
    destination: tuple[str, int | None, str, str | None],
    reason: str | None,
    actor: str,
    created_at: str,
    order_id: int | None = None,
    invoice_id: int | None = None,
    notes: str | None = None,
) -> int:
    """Abre um documento para uso das rotinas de pedidos."""
    return _insert_document_header(
        conn,
        kind=kind,
        status=status,
        source=source,
        destination=destination,
        reason=reason,
        notes=notes,
        actor=actor,
        created_at=created_at,
        order_id=order_id,
        invoice_id=invoice_id,
    )


def add_stock_document_item(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    product: dict | sqlite3.Row,
    quantity: int,
    unit_cost: float | None = None,
) -> int:
    return _insert_document_item(
        conn,
        document_id=document_id,
        product=product,
        quantity=quantity,
        unit_cost=unit_cost,
    )


def sync_order_document_status(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    new_status: str,
    actor: str,
    now: str,
    reversal_document_id: int | None = None,
) -> None:
    """Mantém o documento de venda coerente com o status do pedido."""
    mapping = {
        "Pendente": "A separar",
        "Pago": "A separar",
        "Enviado": "Em trânsito",
        "Entregue": "Concluído",
        "Cancelado": "Estornado",
    }
    target = mapping.get(new_status)
    if target is None:
        return
    documents = conn.execute(
        "SELECT id, status FROM stock_documents "
        "WHERE order_id = ? AND kind IN ('Venda', 'Reativação')",
        (order_id,),
    ).fetchall()
    for document in documents:
        if document["status"] in ("Estornado", "Cancelado") and target != "Estornado":
            continue
        extra_sql = ", reversed_by_document_id = ?" if reversal_document_id else ""
        extra_params = (reversal_document_id,) if reversal_document_id else ()
        _set_document_status(
            conn,
            document_id=int(document["id"]),
            new_status=target,
            actor=actor,
            note=f"Status do pedido atualizado para {new_status}",
            created_at=now,
            extra_sql=extra_sql,
            extra_params=extra_params,
        )


def list_stock_entities(*, active_only: bool = False) -> pd.DataFrame:
    """Lista filiais e fornecedores usados como origem ou destino."""
    clause = "WHERE se.active = 1" if active_only else ""
    sql = f"""
        SELECT se.id, se.kind, se.name, se.document, se.document_hash, se.city, se.state,
               se.active, se.created_at, se.updated_at,
               COUNT(sm.id) AS movements_count
        FROM stock_entities se
        LEFT JOIN stock_movements sm
               ON sm.entity_kind = se.kind AND sm.entity_id = se.id
        {clause}
        GROUP BY se.id
        ORDER BY se.active DESC, se.kind, se.name COLLATE NOCASE
    """
    with connection() as conn:
        df = pd.read_sql_query(sql, conn)
    if not df.empty and "document" in df.columns:
        df["document"] = df["document"].map(crypto.decrypt)
    return df


def get_stock_entity(entity_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM stock_entities WHERE id = ?", (entity_id,)
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["document"] = crypto.decrypt(data.get("document"))
    return data


def save_stock_entity(
    *,
    kind: str,
    name: str,
    document: str | None,
    city: str | None,
    state: str | None,
    active: bool,
    entity_id: int | None = None,
) -> int:
    kind = (kind or "").strip()
    name = (name or "").strip()
    document = (document or "").strip() or None
    city = (city or "").strip() or None
    state = (state or "").strip().upper() or None
    if kind not in STOCK_ENTITY_KINDS:
        raise DomainError("Escolha filial ou fornecedor.")
    if len(name) < 2:
        raise DomainError("Informe o nome da entidade.")

    now = _now()
    try:
        with transaction() as conn:
            if entity_id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO stock_entities
                        (kind, name, document, document_hash, city, state, active,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (kind, name, crypto.encrypt(document), crypto.hash_document(document), city, state, int(active), now, now),
                )
                return int(cursor.lastrowid)

            exists = conn.execute(
                "SELECT 1 FROM stock_entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if exists is None:
                raise DomainError("Entidade de estoque não encontrada.")
            conn.execute(
                """
                UPDATE stock_entities
                SET kind = ?, name = ?, document = ?, document_hash = ?, city = ?, state = ?,
                    active = ?, updated_at = ?
                WHERE id = ?
                """,
                (kind, name, crypto.encrypt(document), crypto.hash_document(document), city, state, int(active), now, entity_id),
            )
            return entity_id
    except sqlite3.IntegrityError as exc:
        raise DomainError(
            "Já existe uma entidade deste tipo com este nome."
        ) from exc


def set_stock_entity_active(entity_id: int, active: bool) -> None:
    now = _now()
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE stock_entities SET active = ?, updated_at = ? WHERE id = ?",
            (int(active), now, entity_id),
        )
        if cursor.rowcount == 0:
            raise DomainError("Entidade de estoque não encontrada.")


def list_stock_parties(*, active_only: bool = True) -> pd.DataFrame:
    """Clientes, filiais e fornecedores disponíveis para uma movimentação."""
    customer_clause = "WHERE c.status = 'Ativo'" if active_only else ""
    entity_clause = "WHERE se.active = 1" if active_only else ""
    sql = f"""
        SELECT 'Cliente' AS kind, c.id, c.name, c.city, c.state,
               CASE WHEN c.status = 'Ativo' THEN 1 ELSE 0 END AS active
        FROM customers c
        {customer_clause}
        UNION ALL
        SELECT se.kind, se.id, se.name, se.city, se.state, se.active
        FROM stock_entities se
        {entity_clause}
        ORDER BY kind, name COLLATE NOCASE
    """
    with connection() as conn:
        return pd.read_sql_query(sql, conn)


def list_stock_movements(
    *,
    search: str = "",
    kind: str = "Todos",
    status: str = "Todos",
    product_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    clauses = ["1 = 1"]
    params: list[object] = []

    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(sm.product_name) LIKE ? OR lower(sm.product_sku) LIKE ? "
            "OR lower(o.number) LIKE ? OR lower(sm.entity_name) LIKE ? "
            "OR lower(sm.entity_location) LIKE ? OR lower(sm.status) LIKE ? "
            "OR lower(si.number) LIKE ? OR lower(si.access_key) LIKE ? "
            "OR lower(sd.number) LIKE ?)"
        )
        params.extend([term, term, term, term, term, term, term, term, term])
    if kind in STOCK_MOVEMENT_KINDS:
        clauses.append("sm.kind = ?")
        params.append(kind)
    if status in STOCK_MOVEMENT_STATUSES:
        clauses.append("sm.status = ?")
        params.append(status)
    if product_id is not None:
        clauses.append("sm.product_id = ?")
        params.append(int(product_id))
    if start_date:
        clauses.append("date(sm.created_at) >= date(?)")
        params.append(start_date)
    if end_date:
        clauses.append("date(sm.created_at) <= date(?)")
        params.append(end_date)

    sql = f"""
        SELECT sm.id, sm.product_id, sm.product_sku, sm.product_name,
               sm.order_id, o.number AS order_number, sm.kind, sm.quantity,
               sm.balance_before, sm.balance_after, sm.unit_cost, sm.total_cost,
               sm.entity_kind, sm.entity_id, sm.entity_name,
               sm.entity_location, sm.status, sm.invoice_id,
               sm.document_id, sd.number AS document_number,
               sd.kind AS document_kind, sd.status AS document_status,
               sm.reversal_of_id, sm.transit_id,
               si.number AS invoice_number, si.series AS invoice_series,
               si.access_key AS invoice_key, sm.reason, sm.actor,
               sm.created_at
        FROM stock_movements sm
        LEFT JOIN orders o ON o.id = sm.order_id
        LEFT JOIN stock_documents sd ON sd.id = sm.document_id
        LEFT JOIN stock_invoices si ON si.id = sm.invoice_id
        WHERE {' AND '.join(clauses)}
        ORDER BY datetime(sm.created_at) DESC, sm.id DESC
        LIMIT ?
    """
    params.append(int(limit))
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def list_stock_documents(
    *,
    search: str = "",
    kind: str = "Todos",
    status: str = "Todos",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 300,
) -> pd.DataFrame:
    clauses = ["1 = 1"]
    params: list[object] = []
    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(sd.number) LIKE ? OR lower(sd.reason) LIKE ? "
            "OR lower(sd.source_name) LIKE ? OR lower(sd.destination_name) LIKE ? "
            "OR lower(o.number) LIKE ? OR lower(si.number) LIKE ? "
            "OR lower(si.access_key) LIKE ? OR EXISTS ("
            "SELECT 1 FROM stock_document_items sdi2 "
            "WHERE sdi2.document_id = sd.id AND ("
            "lower(sdi2.product_name) LIKE ? OR lower(sdi2.product_sku) LIKE ?)))"
        )
        params.extend([term] * 9)
    if kind in STOCK_DOCUMENT_KINDS:
        clauses.append("sd.kind = ?")
        params.append(kind)
    if status in STOCK_DOCUMENT_STATUSES:
        clauses.append("sd.status = ?")
        params.append(status)
    if start_date:
        clauses.append("date(sd.created_at) >= date(?)")
        params.append(start_date)
    if end_date:
        clauses.append("date(sd.created_at) <= date(?)")
        params.append(end_date)

    sql = f"""
        SELECT sd.id, sd.number, sd.kind, sd.status, sd.source_kind,
               sd.source_id, sd.source_name, sd.source_location,
               sd.destination_kind, sd.destination_id, sd.destination_name,
               sd.destination_location, sd.reason, sd.notes, sd.order_id,
               o.number AS order_number, sd.invoice_id,
               si.number AS invoice_number, si.series AS invoice_series,
               si.access_key AS invoice_key, sd.parent_document_id,
               sd.reversal_of_document_id, sd.reversed_by_document_id,
               sd.created_by, sd.created_at, sd.updated_at, sd.confirmed_at,
               sd.received_at,
               COUNT(sdi.id) AS item_count,
               COALESCE(SUM(sdi.quantity), 0) AS units,
               COALESCE(SUM(sdi.total_cost), 0) AS total_cost
        FROM stock_documents sd
        LEFT JOIN stock_document_items sdi ON sdi.document_id = sd.id
        LEFT JOIN orders o ON o.id = sd.order_id
        LEFT JOIN stock_invoices si ON si.id = sd.invoice_id
        WHERE {' AND '.join(clauses)}
        GROUP BY sd.id
        ORDER BY datetime(sd.created_at) DESC, sd.id DESC
        LIMIT ?
    """
    params.append(int(limit))
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_stock_document(document_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT sd.*, o.number AS order_number, si.number AS invoice_number,
                   si.series AS invoice_series, si.access_key AS invoice_key,
                   si.file_name AS invoice_file_name
            FROM stock_documents sd
            LEFT JOIN orders o ON o.id = sd.order_id
            LEFT JOIN stock_invoices si ON si.id = sd.invoice_id
            WHERE sd.id = ?
            """,
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def list_stock_document_items(document_id: int) -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(
            """
            SELECT id, document_id, product_id, product_sku, product_name,
                   quantity, unit_cost, total_cost, received_quantity, notes
            FROM stock_document_items
            WHERE document_id = ?
            ORDER BY id
            """,
            conn,
            params=[int(document_id)],
        )


def list_document_status_history(document_id: int) -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(
            """
            SELECT from_status, to_status, note, actor, created_at
            FROM stock_status_history
            WHERE document_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            conn,
            params=[int(document_id)],
        )


def list_stock_transits(
    *, status: str = "Abertos", search: str = "", limit: int = 300
) -> pd.DataFrame:
    clauses = ["1 = 1"]
    params: list[object] = []
    if status == "Abertos":
        clauses.append("st.status IN ('Em trânsito', 'Parcial')")
    elif status in STOCK_TRANSIT_STATUSES:
        clauses.append("st.status = ?")
        params.append(status)
    search = search.strip()
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(lower(st.product_name) LIKE ? OR lower(st.product_sku) LIKE ? "
            "OR lower(sd.number) LIKE ? OR lower(st.destination_name) LIKE ? "
            "OR lower(st.source_name) LIKE ?)"
        )
        params.extend([term] * 5)

    sql = f"""
        SELECT st.id, st.document_id, st.document_item_id, st.product_id,
               st.product_sku, st.product_name, st.direction, st.quantity,
               st.received_quantity, st.source_kind, st.source_name,
               st.source_location, st.destination_kind, st.destination_name,
               st.destination_location, st.status, st.shipped_at, st.received_at,
               st.created_at, st.updated_at, sd.number AS document_number,
               sd.kind AS document_kind, sd.status AS document_status,
               sdi.unit_cost, sdi.total_cost
        FROM stock_transits st
        JOIN stock_documents sd ON sd.id = st.document_id
        JOIN stock_document_items sdi ON sdi.id = st.document_item_id
        WHERE {' AND '.join(clauses)}
        ORDER BY datetime(st.shipped_at) DESC, st.id DESC
        LIMIT ?
    """
    params.append(int(limit))
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_stock_transit(transit_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT st.*, sd.number AS document_number, sd.kind AS document_kind,
                   sd.status AS document_status, sdi.unit_cost,
                   sdi.total_cost
            FROM stock_transits st
            JOIN stock_documents sd ON sd.id = st.document_id
            JOIN stock_document_items sdi ON sdi.id = st.document_item_id
            WHERE st.id = ?
            """,
            (transit_id,),
        ).fetchone()
    return dict(row) if row else None


def stock_transit_summary() -> dict:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(st.quantity - st.received_quantity), 0) AS units,
                   COALESCE(SUM((st.quantity - st.received_quantity)
                                * sdi.unit_cost), 0) AS value,
                   COUNT(*) AS items
            FROM stock_transits st
            JOIN stock_document_items sdi ON sdi.id = st.document_item_id
            WHERE st.status IN ('Em trânsito', 'Parcial')
            """
        ).fetchone()
    return {
        "units": int(row["units"] or 0),
        "value": float(row["value"] or 0),
        "items": int(row["items"] or 0),
    }


def list_stock_invoices(limit: int = 100) -> pd.DataFrame:
    """Lista as notas fiscais importadas e quantos movimentos as usam."""
    sql = """
        SELECT si.id, si.number, si.series, si.access_key, si.issued_at,
               si.issuer_name, si.recipient_name, si.total_value, si.file_name,
               si.created_at, si.created_by, COUNT(sm.id) AS movements_count
        FROM stock_invoices si
        LEFT JOIN stock_movements sm ON sm.invoice_id = si.id
        GROUP BY si.id
        ORDER BY datetime(si.created_at) DESC, si.id DESC
        LIMIT ?
    """
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=[int(limit)])


def get_stock_invoice(invoice_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM stock_invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
    return dict(row) if row else None
