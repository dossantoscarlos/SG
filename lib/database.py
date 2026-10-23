"""Conexão, esquema e dados iniciais do banco SQLite."""

from __future__ import annotations

import os
import random
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterator

from lib.security import hash_password

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "sg.db"

ORDER_STATUSES = ("Pendente", "Pago", "Enviado", "Entregue", "Cancelado")
REVENUE_STATUSES = ("Pago", "Enviado", "Entregue")
OPEN_STATUSES = ("Pendente", "Pago", "Enviado")
PAYMENT_METHODS = ("Pix", "Cartão de crédito", "Boleto", "Dinheiro")
CHANNELS = ("Site", "WhatsApp", "Loja física", "Marketplace")
CUSTOMER_STATUSES = ("Ativo", "Inativo")
CATEGORIES = ("Acessórios", "Casa", "Eletrônicos", "Papelaria", "Vestuário")

BRAZIL_STATES = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'Administrador',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    is_superuser INTEGER NOT NULL DEFAULT 0 CHECK (is_superuser IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    description TEXT,
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_permissions (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    codename TEXT NOT NULL,
    PRIMARY KEY (profile_id, codename)
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, profile_id)
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    codename TEXT NOT NULL,
    PRIMARY KEY (user_id, codename)
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL CHECK (price >= 0),
    cost REAL NOT NULL DEFAULT 0 CHECK (cost >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT COLLATE NOCASE,
    phone TEXT,
    city TEXT,
    state TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo' CHECK (status IN ('Ativo', 'Inativo')),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'Pendente'
        CHECK (status IN ('Pendente', 'Pago', 'Enviado', 'Entregue', 'Cancelado')),
    payment_method TEXT NOT NULL,
    channel TEXT NOT NULL,
    discount REAL NOT NULL DEFAULT 0 CHECK (discount >= 0),
    shipping REAL NOT NULL DEFAULT 0 CHECK (shipping >= 0),
    total REAL NOT NULL CHECK (total >= 0),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    cost_at_sale REAL NOT NULL DEFAULT 0 CHECK (cost_at_sale >= 0)
);

CREATE TABLE IF NOT EXISTS carriers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    tracking_url TEXT,
    phone TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    carrier_id INTEGER REFERENCES carriers(id) ON DELETE SET NULL,
    service TEXT,
    tracking_code TEXT,
    shipped_at TEXT,
    expected_delivery TEXT,
    delivered_at TEXT,
    cost REAL NOT NULL DEFAULT 0 CHECK (cost >= 0),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    document TEXT,
    city TEXT,
    state TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (kind, name)
);

CREATE TABLE IF NOT EXISTS stock_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT,
    series TEXT,
    access_key TEXT,
    issued_at TEXT,
    issuer_name TEXT,
    recipient_name TEXT,
    total_value REAL,
    xml TEXT NOT NULL,
    file_name TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS stock_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Concluído',
    source_kind TEXT NOT NULL DEFAULT 'Estoque interno',
    source_id INTEGER,
    source_name TEXT NOT NULL DEFAULT 'Estoque interno',
    source_location TEXT,
    destination_kind TEXT NOT NULL DEFAULT 'Estoque interno',
    destination_id INTEGER,
    destination_name TEXT NOT NULL DEFAULT 'Estoque interno',
    destination_location TEXT,
    reason TEXT,
    notes TEXT,
    order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    invoice_id INTEGER REFERENCES stock_invoices(id) ON DELETE SET NULL,
    parent_document_id INTEGER REFERENCES stock_documents(id) ON DELETE SET NULL,
    reversal_of_document_id INTEGER REFERENCES stock_documents(id) ON DELETE SET NULL,
    reversed_by_document_id INTEGER REFERENCES stock_documents(id) ON DELETE SET NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT,
    received_at TEXT
);

CREATE TABLE IF NOT EXISTS stock_document_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES stock_documents(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    unit_cost REAL NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    total_cost REAL NOT NULL DEFAULT 0 CHECK (total_cost >= 0),
    received_quantity INTEGER NOT NULL DEFAULT 0 CHECK (received_quantity >= 0),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS stock_transits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES stock_documents(id) ON DELETE CASCADE,
    document_item_id INTEGER NOT NULL UNIQUE
        REFERENCES stock_document_items(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    received_quantity INTEGER NOT NULL DEFAULT 0 CHECK (received_quantity >= 0),
    source_kind TEXT NOT NULL DEFAULT 'Estoque interno',
    source_id INTEGER,
    source_name TEXT NOT NULL DEFAULT 'Estoque interno',
    source_location TEXT,
    destination_kind TEXT NOT NULL DEFAULT 'Estoque interno',
    destination_id INTEGER,
    destination_name TEXT NOT NULL DEFAULT 'Estoque interno',
    destination_location TEXT,
    status TEXT NOT NULL DEFAULT 'Em trânsito',
    shipped_at TEXT NOT NULL,
    received_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER REFERENCES stock_documents(id) ON DELETE CASCADE,
    movement_id INTEGER REFERENCES stock_movements(id) ON DELETE CASCADE,
    transit_id INTEGER REFERENCES stock_transits(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT,
    actor TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    document_id INTEGER REFERENCES stock_documents(id) ON DELETE SET NULL,
    document_item_id INTEGER REFERENCES stock_document_items(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    balance_before INTEGER,
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    unit_cost REAL,
    total_cost REAL,
    entity_kind TEXT NOT NULL DEFAULT 'Estoque interno',
    entity_id INTEGER,
    entity_name TEXT NOT NULL DEFAULT 'Estoque interno',
    entity_location TEXT,
    status TEXT NOT NULL DEFAULT 'Concluído',
    invoice_id INTEGER,
    reversal_of_id INTEGER REFERENCES stock_movements(id) ON DELETE SET NULL,
    transit_id INTEGER REFERENCES stock_transits(id) ON DELETE SET NULL,
    reason TEXT,
    actor TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_active ON products(active);
CREATE INDEX IF NOT EXISTS idx_customers_status ON customers(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email_unique
    ON customers(email COLLATE NOCASE)
    WHERE email IS NOT NULL AND email <> '';
CREATE INDEX IF NOT EXISTS idx_user_profiles_profile ON user_profiles(profile_id);
CREATE INDEX IF NOT EXISTS idx_profile_permissions_profile ON profile_permissions(profile_id);
CREATE INDEX IF NOT EXISTS idx_carriers_active ON carriers(active);
CREATE INDEX IF NOT EXISTS idx_shipments_carrier ON shipments(carrier_id);
CREATE INDEX IF NOT EXISTS idx_shipments_expected ON shipments(expected_delivery);
CREATE INDEX IF NOT EXISTS idx_shipments_delivered ON shipments(delivered_at);
CREATE INDEX IF NOT EXISTS idx_stock_entities_kind ON stock_entities(kind);
CREATE INDEX IF NOT EXISTS idx_stock_entities_active ON stock_entities(active);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_order ON stock_movements(order_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_created ON stock_movements(created_at);
CREATE INDEX IF NOT EXISTS idx_stock_documents_status ON stock_documents(status);
CREATE INDEX IF NOT EXISTS idx_stock_documents_kind ON stock_documents(kind);
CREATE INDEX IF NOT EXISTS idx_stock_documents_order ON stock_documents(order_id);
CREATE INDEX IF NOT EXISTS idx_stock_documents_created ON stock_documents(created_at);
CREATE INDEX IF NOT EXISTS idx_stock_document_items_document
    ON stock_document_items(document_id);
CREATE INDEX IF NOT EXISTS idx_stock_document_items_product
    ON stock_document_items(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_transits_status ON stock_transits(status);
CREATE INDEX IF NOT EXISTS idx_stock_transits_document ON stock_transits(document_id);
CREATE INDEX IF NOT EXISTS idx_stock_status_history_document
    ON stock_status_history(document_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_invoices_access_key
    ON stock_invoices(access_key)
    WHERE access_key IS NOT NULL AND access_key <> '';
CREATE INDEX IF NOT EXISTS idx_stock_invoices_number ON stock_invoices(number);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('matriz', 'filial')),
    parent_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    address TEXT,
    city TEXT,
    state TEXT,
    zip_code TEXT,
    document TEXT,
    phone TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    allow_branch_stock_view INTEGER NOT NULL DEFAULT 0
        CHECK (allow_branch_stock_view IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_companies (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_user_companies_user ON user_companies(user_id);
CREATE INDEX IF NOT EXISTS idx_user_companies_company ON user_companies(company_id);
"""


def get_database_path() -> Path:
    """Permite usar outro banco em testes ou implantações."""
    configured = os.environ.get("SG_DB_PATH")
    path = Path(configured).expanduser() if configured else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_database_path(), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Conexão de leitura, fechada automaticamente."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Transação com bloqueio de escrita, com rollback em caso de erro."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_user_columns(conn: sqlite3.Connection) -> None:
    """Aplica pequenas migrações em bancos criados por versões anteriores."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "is_superuser" not in columns:
        conn.execute(
            """
            ALTER TABLE users
            ADD COLUMN is_superuser INTEGER NOT NULL DEFAULT 0
                CHECK (is_superuser IN (0, 1))
            """
        )


def _ensure_user_companies(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_companies ("
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE, "
        "is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)), "
        "created_at TEXT NOT NULL, "
        "PRIMARY KEY (user_id, company_id))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_companies_user ON user_companies(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_companies_company ON user_companies(company_id)")


def _ensure_crypto_columns(conn: sqlite3.Connection) -> None:
    """Adiciona colunas de hash para busca de e-mails e documentos criptografados."""
    specs = (
        ("users", "email_hash", "TEXT"),
        ("customers", "email_hash", "TEXT"),
        ("stock_entities", "document_hash", "TEXT"),
        ("companies", "document_hash", "TEXT"),
    )
    for table, column, definition in specs:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_email_hash ON customers(email_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_entities_document_hash ON stock_entities(document_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_document_hash ON companies(document_hash)")


def _ensure_company_columns(conn: sqlite3.Connection) -> None:
    """Adiciona company_id a products e cria tabelas de empresa se faltarem."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    if "company_id" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN company_id INTEGER REFERENCES companies(id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_company ON products(company_id)"
    )


def _ensure_stock_movement_columns(conn: sqlite3.Connection) -> None:
    """Adiciona campos de entidade, status e nota fiscal a bancos anteriores."""
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(stock_movements)")
    }
    additions = (
        ("entity_kind", "TEXT NOT NULL DEFAULT 'Estoque interno'"),
        ("entity_id", "INTEGER"),
        ("entity_name", "TEXT NOT NULL DEFAULT 'Estoque interno'"),
        ("entity_location", "TEXT"),
        ("status", "TEXT NOT NULL DEFAULT 'Concluído'"),
        ("invoice_id", "INTEGER"),
        ("document_id", "INTEGER REFERENCES stock_documents(id) ON DELETE SET NULL"),
        (
            "document_item_id",
            "INTEGER REFERENCES stock_document_items(id) ON DELETE SET NULL",
        ),
        ("balance_before", "INTEGER"),
        ("unit_cost", "REAL"),
        ("total_cost", "REAL"),
        (
            "reversal_of_id",
            "INTEGER REFERENCES stock_movements(id) ON DELETE SET NULL",
        ),
        ("transit_id", "INTEGER REFERENCES stock_transits(id) ON DELETE SET NULL"),
    )
    for name, definition in additions:
        if name not in columns:
            conn.execute(
                f"ALTER TABLE stock_movements ADD COLUMN {name} {definition}"
            )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_entity
        ON stock_movements(entity_kind, entity_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_status
        ON stock_movements(status)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_invoice
        ON stock_movements(invoice_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_document
        ON stock_movements(document_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_movements_document_item
        ON stock_movements(document_item_id)
        """
    )


def init_database(seed_demo: bool = True) -> None:
    """Cria o esquema e, na primeira execução, popula dados de demonstração."""
    with connection() as conn:
        conn.executescript(SCHEMA)
        _ensure_user_columns(conn)
        _ensure_company_columns(conn)
        _ensure_crypto_columns(conn)
        _ensure_user_companies(conn)
        _ensure_stock_movement_columns(conn)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.commit()

    if seed_demo:
        _seed_admin_if_needed()

    # A ACL é inicializada depois do administrador para que a conta inicial já
    # receba o perfil de acesso total. A migração preserva o acesso de bancos
    # criados antes da existência de perfis.
    from lib import acl

    acl.bootstrap()
    acl.migrate_legacy_access()

    if seed_demo:
        _seed_demo_if_needed()

    _sync_logistics_data()


def _sync_logistics_data() -> None:
    """Cria a base logística e migra pedidos existentes de forma idempotente."""
    now_dt = datetime.now()
    now = now_dt.isoformat(sep=" ", timespec="seconds")

    with transaction() as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        _seed_carriers(conn, now)
        _backfill_shipments(conn, now_dt, now)
        _seed_stock_snapshots(conn, now)
        if version < 3:
            _backfill_stock_movement_entities(conn)
        if version < 4:
            _backfill_stock_movement_status(conn)
        if version < 5:
            _backfill_stock_documents(conn)
        if version < 6:
            _backfill_companies(conn, now)
        if version < 7:
            _backfill_crypto(conn, now)
        if version < 8:
            _backfill_user_companies(conn, now)
        conn.execute("PRAGMA user_version = 8")


def _backfill_companies(conn: sqlite3.Connection, now: str) -> None:
    '''Cria a empresa matriz padrão e associa produtos existentes a ela.'''
    row = conn.execute("SELECT id FROM companies WHERE type = 'matriz' LIMIT 1").fetchone()
    if row is None:
        cur = conn.execute(
            """
            INSERT INTO companies
                (name, type, parent_id, address, city, state, zip_code,
                 document, phone, active, allow_branch_stock_view, created_at, updated_at)
            VALUES (?, 'matriz', NULL, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            ("SG Gestão", "Endereço principal", "São Paulo", "SP", "00000-000",
             None, None, now, now),
        )
        company_id = cur.lastrowid
    else:
        company_id = row["id"]

    # Associa produtos sem empresa à matriz padrão.
    conn.execute(
        "UPDATE products SET company_id = ? WHERE company_id IS NULL",
        (company_id,),
    )

    # Configuração inicial da empresa.
    config = {
        "company_name": "SG Gestão",
        "company_address": "Endereço principal",
        "company_city": "São Paulo",
        "company_state": "SP",
        "company_zip": "00000-000",
    }
    for key, value in config.items():
        exists = conn.execute(
            "SELECT 1 FROM company_config WHERE key = ?", (key,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO company_config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )


def _seed_carriers(conn: sqlite3.Connection, now: str) -> None:
    if conn.execute("SELECT COUNT(*) FROM carriers").fetchone()[0] > 0:
        return

    carriers = (
        (
            "Correios",
            "https://rastreamento.correios.com.br/app/index.php?objeto={tracking}",
            "0800 725 0100",
        ),
        (
            "Jadlog",
            "https://www.jadlog.com.br/tracking?codigo={tracking}",
            "0800 701 2000",
        ),
        (
            "Loggi",
            "https://www.loggi.com/rastreio/?tracking={tracking}",
            None,
        ),
        (
            "Mercado Envios",
            "https://www.mercadolivre.com.br/envios/rastreio/{tracking}",
            None,
        ),
        ("Retirada no local", None, None),
    )
    conn.executemany(
        """
        INSERT INTO carriers
            (name, tracking_url, phone, active, created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        [(name, url, phone, now, now) for name, url, phone in carriers],
    )


def _backfill_shipments(
    conn: sqlite3.Connection, now_dt: datetime, now: str
) -> None:
    orders = conn.execute(
        """
        SELECT o.id, o.status, o.created_at, o.shipping
        FROM orders o
        LEFT JOIN shipments s ON s.order_id = o.id
        WHERE s.id IS NULL AND o.status IN ('Enviado', 'Entregue')
        ORDER BY o.id
        """
    ).fetchall()
    if not orders:
        return

    carriers = conn.execute(
        """
        SELECT id FROM carriers
        WHERE active = 1 AND name <> 'Retirada no local'
        ORDER BY id
        """
    ).fetchall()
    carrier_ids = [int(row["id"]) for row in carriers]

    for order in orders:
        order_id = int(order["id"])
        try:
            created = datetime.fromisoformat(order["created_at"])
        except (TypeError, ValueError):
            created = now_dt - timedelta(days=7)

        shipped = created + timedelta(
            days=1 + order_id % 2,
            hours=2 + order_id % 6,
        )
        if shipped > now_dt:
            shipped = now_dt - timedelta(hours=2)

        expected = (shipped + timedelta(days=3 + order_id % 6)).date()
        delivered: datetime | None = None
        if order["status"] == "Entregue":
            variance = (-1, 0, 0, 1, 2)[(order_id * 3) % 5]
            delivered = datetime.combine(
                expected + timedelta(days=variance),
                time(hour=9 + order_id % 9, minute=(order_id * 7) % 60),
            )
            if delivered > now_dt:
                delivered = now_dt - timedelta(hours=1)
            if delivered < shipped:
                delivered = shipped + timedelta(hours=6)

        carrier_id = (
            carrier_ids[(order_id // 3) % len(carrier_ids)]
            if carrier_ids
            else None
        )
        conn.execute(
            """
            INSERT INTO shipments
                (order_id, carrier_id, service, tracking_code, shipped_at,
                 expected_delivery, delivered_at, cost, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                order_id,
                carrier_id,
                "Expresso" if order_id % 3 == 0 else "Econômico",
                f"SG{order_id:09d}BR",
                shipped.isoformat(sep=" ", timespec="seconds"),
                expected.isoformat(),
                delivered.isoformat(sep=" ", timespec="seconds") if delivered else None,
                round(float(order["shipping"] or 0), 2),
                now,
                now,
            ),
        )


def _seed_stock_snapshots(conn: sqlite3.Connection, now: str) -> None:
    products = conn.execute(
        """
        SELECT p.id, p.sku, p.name, p.stock
        FROM products p
        WHERE p.stock > 0
          AND NOT EXISTS (
            SELECT 1 FROM stock_movements sm WHERE sm.product_id = p.id
        )
        ORDER BY p.id
        """
    ).fetchall()
    if not products:
        return

    conn.executemany(
        """
        INSERT INTO stock_movements
            (product_id, product_sku, product_name, order_id, kind, quantity,
             balance_after, entity_kind, entity_id, entity_name,
             entity_location, status, reason, actor, created_at)
        VALUES (?, ?, ?, NULL, 'Saldo inicial', ?, ?, 'Estoque interno', NULL,
                'Estoque interno', 'Almoxarifado', 'Concluído', ?, 'Migração', ?)
        """,
        [
            (
                int(product["id"]),
                product["sku"],
                product["name"],
                int(product["stock"]),
                int(product["stock"]),
                "Saldo inicial ao ativar o controle de movimentações",
                now,
            )
            for product in products
        ],
    )


def _backfill_stock_movement_entities(conn: sqlite3.Connection) -> None:
    """Associa movimentações antigas de pedidos ao cliente de destino."""
    conn.execute(
        """
        UPDATE stock_movements
        SET entity_location = 'Almoxarifado'
        WHERE entity_kind = 'Estoque interno'
          AND (entity_location IS NULL OR TRIM(entity_location) = '')
        """
    )
    conn.execute(
        """
        UPDATE stock_movements
        SET entity_kind = 'Cliente',
            entity_id = (
                SELECT o.customer_id
                FROM orders o
                WHERE o.id = stock_movements.order_id
            ),
            entity_name = (
                SELECT c.name
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.id = stock_movements.order_id
            ),
            entity_location = NULLIF(
                TRIM(
                    (
                        SELECT CASE
                            WHEN TRIM(COALESCE(c.city, '')) <> ''
                                 AND TRIM(COALESCE(c.state, '')) <> ''
                            THEN c.city || '/' || c.state
                            ELSE COALESCE(
                                NULLIF(TRIM(c.city), ''),
                                NULLIF(TRIM(c.state), '')
                            )
                        END
                        FROM orders o
                        JOIN customers c ON c.id = o.customer_id
                        WHERE o.id = stock_movements.order_id
                    )
                ),
                ''
            )
        WHERE order_id IS NOT NULL
          AND kind IN ('Venda', 'Cancelamento', 'Reativação', 'Exclusão')
          AND entity_kind = 'Estoque interno'
        """
    )


def _backfill_stock_movement_status(conn: sqlite3.Connection) -> None:
    """Define o status inicial de movimentações criadas antes da versão 4.

    O status é derivado do pedido para vendas e reativações. Movimentos
    internos, entradas, cancelamentos e exclusões já estão concluídos.
    """
    conn.execute(
        """
        UPDATE stock_movements
        SET status = CASE
            WHEN order_id IS NOT NULL
             AND kind IN ('Venda', 'Reativação')
            THEN COALESCE(
                (
                    SELECT CASE o.status
                        WHEN 'Enviado' THEN 'Em trânsito'
                        WHEN 'Pendente' THEN 'A separar'
                        WHEN 'Pago' THEN 'A separar'
                        ELSE 'Concluído'
                    END
                    FROM orders o
                    WHERE o.id = stock_movements.order_id
                ),
                'Concluído'
            )
            ELSE 'Concluído'
        END
        """
    )


def _backfill_stock_documents(conn: sqlite3.Connection) -> None:
    """Transforma o histórico anterior em documentos de movimentação.

    Movimentos de um mesmo pedido, tipo e horário são agrupados em um único
    documento com vários itens. Movimentos avulsos viram documentos de um item.
    O processo é executado apenas na migração para a versão 5.
    """
    movements = conn.execute(
        """
        SELECT sm.*, p.cost AS product_cost
        FROM stock_movements sm
        LEFT JOIN products p ON p.id = sm.product_id
        WHERE sm.document_id IS NULL
        ORDER BY COALESCE(sm.order_id, -sm.id), sm.created_at, sm.id
        """
    ).fetchall()
    if not movements:
        return

    grouped: dict[tuple, list[sqlite3.Row]] = {}
    for movement in movements:
        if movement["order_id"] is not None:
            key = (
                "order",
                int(movement["order_id"]),
                movement["kind"],
                movement["created_at"],
            )
        else:
            key = ("movement", int(movement["id"]))
        grouped.setdefault(key, []).append(movement)

    for group in grouped.values():
        first = group[0]
        quantity = int(first["quantity"])
        if quantity < 0:
            source_kind, source_id, source_name, source_location = (
                "Estoque interno",
                None,
                "Estoque interno",
                "Almoxarifado",
            )
            destination_kind = first["entity_kind"]
            destination_id = first["entity_id"]
            destination_name = first["entity_name"]
            destination_location = first["entity_location"]
        else:
            source_kind = first["entity_kind"]
            source_id = first["entity_id"]
            source_name = first["entity_name"]
            source_location = first["entity_location"]
            destination_kind, destination_id, destination_name, destination_location = (
                "Estoque interno",
                None,
                "Estoque interno",
                "Almoxarifado",
            )

        created_at = first["created_at"]
        try:
            year = datetime.fromisoformat(created_at).year
        except (TypeError, ValueError):
            year = datetime.now().year
        status = first["status"]
        cursor = conn.execute(
            """
            INSERT INTO stock_documents
                (number, kind, status, source_kind, source_id, source_name,
                 source_location, destination_kind, destination_id,
                 destination_name, destination_location, reason, notes, order_id,
                 invoice_id, created_by, created_at, updated_at, confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"MOV-{year}-LEG-{int(first['id']):04d}",
                first["kind"],
                status,
                source_kind,
                source_id,
                source_name,
                source_location,
                destination_kind,
                destination_id,
                destination_name,
                destination_location,
                first["reason"],
                first["order_id"],
                first["invoice_id"],
                first["actor"] or "Migração",
                created_at,
                created_at,
                created_at
                if status in ("Concluído", "Recebido", "Divergente")
                else None,
            ),
        )
        document_id = int(cursor.lastrowid)
        conn.execute(
            "UPDATE stock_documents SET number = ? WHERE id = ?",
            (f"MOV-{year}-{document_id:04d}", document_id),
        )

        for movement in group:
            unit_cost = movement["unit_cost"]
            if unit_cost is None:
                unit_cost = float(movement["product_cost"] or 0)
            total_cost = round(abs(int(movement["quantity"])) * float(unit_cost), 2)
            item_cursor = conn.execute(
                """
                INSERT INTO stock_document_items
                    (document_id, product_id, product_sku, product_name, quantity,
                     unit_cost, total_cost, received_quantity, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                (
                    document_id,
                    movement["product_id"],
                    movement["product_sku"],
                    movement["product_name"],
                    abs(int(movement["quantity"])),
                    round(float(unit_cost), 2),
                    total_cost,
                ),
            )
            item_id = int(item_cursor.lastrowid)
            conn.execute(
                """
                UPDATE stock_movements
                SET document_id = ?, document_item_id = ?,
                    balance_before = ?, unit_cost = ?, total_cost = ?
                WHERE id = ?
                """,
                (
                    document_id,
                    item_id,
                    int(movement["balance_after"]) - int(movement["quantity"]),
                    round(float(unit_cost), 2),
                    total_cost,
                    int(movement["id"]),
                ),
            )

        conn.execute(
            """
            INSERT INTO stock_status_history
                (document_id, from_status, to_status, note, actor, created_at)
            VALUES (?, NULL, ?, ?, ?, ?)
            """,
            (
                document_id,
                status,
                "Documento criado pela migração v5",
                first["actor"] or "Migração",
                created_at,
            ),
        )


def _seed_admin_if_needed() -> None:
    with transaction() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing:
            return

        initial_password = os.environ.get("SG_ADMIN_PASSWORD", "admin123")
        name = os.environ.get("SG_ADMIN_NAME", "Administrador")
        email = os.environ.get("SG_ADMIN_EMAIL", "admin@sg.com.br")
        used_default = "SG_ADMIN_PASSWORD" not in os.environ
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute(
            """
            INSERT INTO users
                (name, email, password_hash, role, active, is_superuser,
                 must_change_password, created_at)
            VALUES (?, ?, ?, 'Administrador', 1, 1, ?, ?)
            """,
            (name, email, hash_password(initial_password), int(used_default), now),
        )


def _seed_demo_if_needed() -> None:
    with transaction() as conn:
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
            return
        _insert_demo_products(conn)
        _insert_demo_customers(conn)
        _insert_demo_orders(conn)


def _insert_demo_products(conn: sqlite3.Connection) -> None:
    now = datetime.now()
    created_at = (now - timedelta(days=210)).isoformat(sep=" ", timespec="seconds")
    products = [
        # sku, nome, categoria, descrição, preço, custo, estoque, mínimo, ativo
        ("SG-001", "Fone Bluetooth Pulse", "Eletrônicos", "Fone over-ear com cancelamento de ruído e bateria de 30 horas.", 249.90, 128.00, 42, 10, 1),
        ("SG-002", "Caixa de som Mini Boom", "Eletrônicos", "Caixa portátil resistente a respingos, com 12 horas de bateria.", 199.90, 104.00, 28, 8, 1),
        ("SG-003", "Teclado mecânico K2", "Eletrônicos", "Teclado compacto 75%, switches táteis e conexão sem fio.", 349.90, 208.00, 16, 6, 1),
        ("SG-004", "Mouse sem fio Aero", "Eletrônicos", "Mouse ergonômico silencioso com sensor de alta precisão.", 149.90, 71.00, 55, 12, 1),
        ("SG-005", "Carregador USB-C 65 W", "Acessórios", "Carregador compacto com três saídas e proteção térmica.", 129.90, 61.00, 9, 15, 1),
        ("SG-006", "Suporte de notebook Eleva", "Acessórios", "Suporte em alumínio com altura ajustável para notebooks.", 89.90, 36.00, 31, 10, 1),
        ("SG-007", "Cabo USB-C trançado", "Acessórios", "Cabo reforçado de 2 metros para carga e transferência de dados.", 49.90, 17.00, 120, 30, 1),
        ("SG-008", "Mochila urbana Trekk", "Acessórios", "Mochila impermeável com compartimento para notebook de 15,6”.", 289.90, 143.00, 12, 6, 1),
        ("SG-009", "Luminária de mesa Lume", "Casa", "Luminária articulável com três temperaturas de luz e timer.", 159.90, 77.00, 7, 10, 1),
        ("SG-010", "Garrafa térmica 500 ml", "Casa", "Aço inoxidável com parede dupla e tampa antivazamento.", 119.90, 51.00, 24, 8, 1),
        ("SG-011", "Organizador de mesa", "Casa", "Bandeja modular para acessórios, em madeira e metal.", 79.90, 31.00, 3, 8, 1),
        ("SG-012", "Difusor de ambiente", "Casa", "Difusor ultrassônico silencioso com luz âmbar regulável.", 139.90, 64.00, 0, 6, 1),
        ("SG-013", "Caderno executivo A5", "Papelaria", "Caderno com capa em couro ecológico, 160 páginas pautadas.", 44.90, 16.00, 85, 20, 1),
        ("SG-014", "Caneta gel — kit 3", "Papelaria", "Kit com três canetas de escrita macia nas cores preta, azul e verde.", 29.90, 8.50, 63, 20, 1),
        ("SG-015", "Planner semanal", "Papelaria", "Planner sem data, formato A5, com páginas de metas e hábitos.", 59.90, 21.00, 4, 8, 1),
        ("SG-016", "Webcam Full HD", "Eletrônicos", "Webcam 1080p com microfone duplo e correção automática de luz.", 269.90, 159.00, 18, 5, 1),
        ("SG-017", "Hub USB-C 6 em 1", "Acessórios", "Hub com HDMI, leitor de cartões e três portas USB.", 219.90, 109.00, 6, 10, 1),
        ("SG-018", "Camiseta básica SG", "Vestuário", "Camiseta 100% algodão com caimento confortável.", 79.90, 32.00, 40, 12, 1),
        ("SG-019", "Boné urbano", "Vestuário", "Boné ajustável com aba curva e tecido respirável.", 69.90, 26.00, 22, 8, 1),
        ("SG-020", "Meia esportiva — par", "Vestuário", "Meia de algodão com amortecimento leve na sola.", 34.90, 11.00, 2, 10, 1),
        ("SG-021", "Fone com fio Clássico", "Eletrônicos", "Fone de entrada com microfone, fora de linha.", 79.90, 38.00, 7, 5, 0),
    ]
    for sku, name, category, description, price, cost, stock, min_stock, active in products:
        conn.execute(
            """
            INSERT INTO products
                (sku, name, category, description, price, cost, stock, min_stock, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sku, name, category, description, price, cost, stock, min_stock, active, created_at, created_at),
        )


def _insert_demo_customers(conn: sqlite3.Connection) -> None:
    now = datetime.now()
    customers = [
        ("Ana Souza", "ana.souza@email.com", "(11) 98812-4471", "São Paulo", "SP", "Ativo", "Prefere receber contato por WhatsApp.", 420),
        ("Bruno Lima", "bruno.lima@email.com", "(21) 99741-2204", "Rio de Janeiro", "RJ", "Ativo", None, 390),
        ("Carla Mendes", "carla.mendes@email.com", "(31) 98353-9070", "Belo Horizonte", "MG", "Ativo", "Cliente do programa de fidelidade.", 350),
        ("Daniel Rocha", "daniel.rocha@email.com", "(41) 99611-8312", "Curitiba", "PR", "Ativo", None, 320),
        ("Eduarda Alves", "eduarda.alves@email.com", "(51) 98446-7719", "Porto Alegre", "RS", "Ativo", None, 300),
        ("Felipe Carvalho", "felipe.carvalho@email.com", "(71) 99185-3124", "Salvador", "BA", "Ativo", None, 280),
        ("Gabriela Nunes", "gabriela.nunes@email.com", "(81) 98752-6940", "Recife", "PE", "Ativo", None, 260),
        ("Henrique Barbosa", "henrique.barbosa@email.com", "(85) 99218-4425", "Fortaleza", "CE", "Inativo", "Última compra há mais de seis meses.", 240),
        ("Isabela Martins", "isabela.martins@email.com", "(61) 98849-6372", "Brasília", "DF", "Ativo", None, 220),
        ("João Pedro Ramos", "joao.ramos@email.com", "(19) 99634-2851", "Campinas", "SP", "Ativo", None, 200),
        ("Luiza Ribeiro", "luiza.ribeiro@email.com", "(48) 98472-9954", "Florianópolis", "SC", "Ativo", "Indicada por cliente.", 180),
        ("Marcos Vieira", "marcos.vieira@email.com", "(62) 99515-7086", "Goiânia", "GO", "Ativo", None, 160),
        ("Natália Costa", "natalia.costa@email.com", "(91) 98640-1887", "Belém", "PA", "Inativo", None, 140),
        ("Otávio Freitas", "otavio.freitas@email.com", "(92) 99471-3470", "Manaus", "AM", "Ativo", None, 120),
        ("Paula Moreira", "paula.moreira@email.com", "(27) 98923-6815", "Vitória", "ES", "Ativo", None, 90),
        ("Rafael Teixeira", "rafael.teixeira@email.com", "(15) 99177-4082", "Sorocaba", "SP", "Ativo", None, 55),
        ("Sofia Almeida", "sofia.almeida@email.com", "(21) 98362-2580", "Niterói", "RJ", "Ativo", "Gosta de novidades de papelaria.", 22),
        ("Thiago Fonseca", "thiago.fonseca@email.com", "(43) 99682-1934", "Londrina", "PR", "Ativo", None, 8),
        ("Larissa Pires", "larissa.pires@email.com", "(83) 98725-9013", "Campina Grande", "PB", "Ativo", "Cadastro novo.", 3),
    ]
    for name, email, phone, city, state, status, notes, days_ago in customers:
        created = (now - timedelta(days=days_ago, hours=random.randint(0, 8))).isoformat(
            sep=" ", timespec="seconds"
        )
        conn.execute(
            """
            INSERT INTO customers
                (name, email, phone, city, state, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, phone, city, state, status, notes, created, created),
        )


def _choose_status(days_ago: int) -> str:
    if days_ago >= 30:
        return random.choices(
            ["Entregue", "Enviado", "Cancelado"], weights=[84, 8, 8], k=1
        )[0]
    if days_ago >= 10:
        return random.choices(
            ["Entregue", "Enviado", "Pago", "Cancelado"], weights=[50, 28, 14, 8], k=1
        )[0]
    if days_ago >= 3:
        return random.choices(
            ["Enviado", "Pago", "Pendente", "Entregue"], weights=[32, 36, 20, 12], k=1
        )[0]
    return random.choices(["Pago", "Pendente", "Enviado"], weights=[42, 38, 20], k=1)[0]


def _insert_demo_orders(conn: sqlite3.Connection) -> None:
    random.seed(20261020)
    now = datetime.now()
    customers = conn.execute(
        "SELECT id, created_at FROM customers ORDER BY id"
    ).fetchall()
    products = conn.execute(
        "SELECT id, price, cost FROM products WHERE active = 1 ORDER BY id"
    ).fetchall()
    if not customers or not products:
        return

    total_orders = 118
    for _ in range(total_orders):
        days_ago = int(random.triangular(0, 150, 25))
        order_dt = datetime.combine(
            now.date() - timedelta(days=days_ago),
            time(hour=random.randint(9, 19), minute=random.randint(0, 59)),
        )
        eligible = [
            row
            for row in customers
            if datetime.fromisoformat(row["created_at"]).date() <= order_dt.date()
        ]
        customer = random.choice(eligible or customers)

        item_count = random.choices([1, 2, 3, 4], weights=[30, 40, 22, 8], k=1)[0]
        chosen_products = random.sample(products, k=min(item_count, len(products)))
        items: list[tuple[sqlite3.Row, int]] = []
        subtotal = 0.0
        for product in chosen_products:
            quantity = random.choices([1, 2, 3], weights=[60, 30, 10], k=1)[0]
            items.append((product, quantity))
            subtotal += float(product["price"]) * quantity

        discount = 0.0
        discount_roll = random.random()
        if discount_roll < 0.10:
            discount = round(subtotal * 0.05, 2)
        elif discount_roll < 0.16:
            discount = round(subtotal * 0.10, 2)
        shipping = 0.0 if subtotal >= 199 or random.random() < 0.25 else 24.90
        total = round(subtotal - discount + shipping, 2)

        status = _choose_status(days_ago)
        payment_method = random.choices(
            ["Pix", "Cartão de crédito", "Boleto", "Dinheiro"],
            weights=[38, 42, 12, 8],
            k=1,
        )[0]
        channel = random.choices(
            ["Site", "WhatsApp", "Loja física", "Marketplace"],
            weights=[44, 28, 16, 12],
            k=1,
        )[0]
        notes = None
        if random.random() < 0.12:
            notes = random.choice(
                [
                    "Entregar no período da tarde.",
                    "Presente — não incluir nota fiscal.",
                    "Cliente pediu embalagem reforçada.",
                    "Combinar a entrega pelo WhatsApp.",
                ]
            )

        created_at = order_dt.replace(second=0, microsecond=0).isoformat(sep=" ")
        cursor = conn.execute(
            """
            INSERT INTO orders
                (number, customer_id, status, payment_method, channel, discount,
                 shipping, total, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"TMP-{uuid.uuid4().hex[:16].upper()}",
                customer["id"],
                status,
                payment_method,
                channel,
                discount,
                shipping,
                total,
                notes,
                created_at,
                created_at,
            ),
        )
        order_id = int(cursor.lastrowid)
        number = f"PED-{order_dt.year}-{order_id:04d}"
        conn.execute("UPDATE orders SET number = ? WHERE id = ?", (number, order_id))

        for product, quantity in items:
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


def reset_demo_database() -> None:
    """Recria o banco a partir do zero.

    Use apenas em ambiente de demonstração. O arquivo SQLite atual é removido.
    """
    path = get_database_path()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    init_database(seed_demo=True)


def _backfill_crypto(conn, now: str) -> None:
    """Criptografa e-mails/documentos existentes e preenche as colunas de hash."""
    from lib import crypto

    for row in conn.execute("SELECT id, email FROM users").fetchall():
        val = row["email"]
        if not val:
            continue
        plain = crypto.decrypt(val) if str(val).startswith("gAAAAA") else val
        conn.execute(
            "UPDATE users SET email = ?, email_hash = ? WHERE id = ?",
            (crypto.encrypt(plain), crypto.hash_email(plain), row["id"]),
        )

    for row in conn.execute("SELECT id, email FROM customers").fetchall():
        val = row["email"]
        if not val:
            continue
        plain = crypto.decrypt(val) if str(val).startswith("gAAAAA") else val
        conn.execute(
            "UPDATE customers SET email = ?, email_hash = ? WHERE id = ?",
            (crypto.encrypt(plain), crypto.hash_email(plain), row["id"]),
        )

    for row in conn.execute("SELECT id, document FROM stock_entities").fetchall():
        val = row["document"]
        if not val:
            continue
        plain = crypto.decrypt(val) if str(val).startswith("gAAAAA") else val
        conn.execute(
            "UPDATE stock_entities SET document = ?, document_hash = ? WHERE id = ?",
            (crypto.encrypt(plain), crypto.hash_document(plain), row["id"]),
        )

    for row in conn.execute("SELECT id, document FROM companies").fetchall():
        val = row["document"]
        if not val:
            continue
        plain = crypto.decrypt(val) if str(val).startswith("gAAAAA") else val
        conn.execute(
            "UPDATE companies SET document = ?, document_hash = ? WHERE id = ?",
            (crypto.encrypt(plain), crypto.hash_document(plain), row["id"]),
        )


def _backfill_user_companies(conn, now: str) -> None:
    company_row = conn.execute(
        "SELECT id FROM companies WHERE type = 'matriz' ORDER BY id LIMIT 1"
    ).fetchone()
    if company_row is None:
        return
    company_id = company_row["id"]
    for row in conn.execute("SELECT id FROM users").fetchall():
        exists = conn.execute(
            "SELECT 1 FROM user_companies WHERE user_id = ? AND company_id = ?",
            (row["id"], company_id),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO user_companies (user_id, company_id, is_default, created_at) VALUES (?, ?, 1, ?)",
                (row["id"], company_id, now),
            )
