import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SG_DB_PATH", str(Path(__import__("tempfile").gettempdir()) / "sg_test.db"))

from lib import auth, inventory, orders
from lib.database import init_database, connection, transaction


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SG_DB_PATH", str(db))
    init_database(seed_demo=True)
    yield db


def test_order_creation_decrements_stock():
    with connection() as conn:
        products = conn.execute("SELECT * FROM products ORDER BY id LIMIT 2").fetchall()
        customer = conn.execute("SELECT * FROM customers ORDER BY id LIMIT 1").fetchone()
    p1, p2 = products
    before = p1["stock"]
    order_id, number = orders.create_order(
        customer_id=int(customer["id"]),
        status="Pago",
        payment_method="Pix",
        channel="Site",
        discount=0,
        shipping=0,
        items=[(p1["id"], 2)],
        notes="teste",
    )
    with connection() as conn:
        after = conn.execute("SELECT stock FROM products WHERE id = ?", (p1["id"],)).fetchone()[0]
    assert after == before - 2


def test_cancel_order_restores_stock():
    with connection() as conn:
        products = conn.execute("SELECT * FROM products ORDER BY id LIMIT 1").fetchall()
        customer = conn.execute("SELECT * FROM customers ORDER BY id LIMIT 1").fetchone()
    p1 = products[0]
    before = p1["stock"]
    order_id, number = orders.create_order(
        customer_id=int(customer["id"]),
        status="Pago",
        payment_method="Pix",
        channel="Site",
        discount=0,
        shipping=0,
        items=[(p1["id"], 1)],
        notes=None,
    )
    orders.delete_order(order_id, actor="Teste")
    with connection() as conn:
        after = conn.execute("SELECT stock FROM products WHERE id = ?", (p1["id"],)).fetchone()[0]
    assert after == before


def test_inventory_entry_increments_stock():
    with connection() as conn:
        p = conn.execute("SELECT * FROM products ORDER BY id LIMIT 1").fetchone()
    before = p["stock"]
    entity_id = inventory.save_stock_entity(kind="Fornecedor", name="Forn Teste", document=None, city=None, state=None, active=True)
    doc = inventory.create_stock_document(
        kind="Entrada",
        items=[{"product_id": p["id"], "quantity": 5, "unit_cost": 3.0}],
        reason="teste",
        actor="Teste",
        entity_kind="Fornecedor",
        entity_id=entity_id,
        status="Concluído",
    )
    with connection() as conn:
        after = conn.execute("SELECT stock FROM products WHERE id = ?", (p["id"],)).fetchone()[0]
    assert after == before + 5


def test_inventory_reversal():
    with connection() as conn:
        p = conn.execute("SELECT * FROM products ORDER BY id LIMIT 1").fetchone()
    before = p["stock"]
    entity_id = inventory.save_stock_entity(kind="Fornecedor", name="Forn Teste", document=None, city=None, state=None, active=True)
    doc = inventory.create_stock_document(
        kind="Entrada",
        items=[{"product_id": p["id"], "quantity": 5, "unit_cost": 3.0}],
        reason="teste",
        actor="Teste",
        entity_kind="Fornecedor",
        entity_id=entity_id,
        status="Concluído",
    )
    # reverse
    inventory.reverse_stock_document(doc, actor="Teste")
    with connection() as conn:
        after = conn.execute("SELECT stock FROM products WHERE id = ?", (p["id"],)).fetchone()[0]
    assert after == before
