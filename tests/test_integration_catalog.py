import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SG_DB_PATH", str(Path(__import__("tempfile").gettempdir()) / "sg_test.db"))

from lib import catalog, crypto
from lib.database import init_database, connection, transaction


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SG_DB_PATH", str(db))
    init_database(seed_demo=True)
    yield db


def test_catalog_list_products_filters_by_company():
    df = catalog.list_products(company_id=1)
    assert not df.empty
    df2 = catalog.list_products(company_id=9999)
    assert df2.empty


def test_catalog_save_product_sets_company():
    pid = catalog.save_product(
        sku="TST-001",
        name="Produto Teste",
        category="Eletrônicos",
        description=None,
        price=10.0,
        cost=5.0,
        stock=3,
        min_stock=1,
        active=True,
        company_id=1,
    )
    p = catalog.get_product(pid)
    assert p["company_id"] == 1
    # cleanup
    with transaction() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (pid,))


def test_catalog_customer_email_encrypted():
    cid = catalog.save_customer(name="Cliente Teste", email="teste@x.com", phone=None, city=None, state=None, status="Ativo", notes=None)
    with connection() as conn:
        row = conn.execute("SELECT email, email_hash FROM customers WHERE id = ?", (cid,)).fetchone()
    assert row["email"].startswith("gAAAAA")
    assert crypto.hash_email("teste@x.com") == row["email_hash"]
    c = catalog.get_customer(cid)
    assert c["email"] == "teste@x.com"
    df = catalog.list_customers(search="teste@x.com")
    assert len(df) == 1
    with transaction() as conn:
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))


def test_catalog_list_customers_search_by_name():
    df = catalog.list_customers(search="Ana")
    assert not df.empty


def test_inventory_entity_document_encrypted():
    from lib import inventory
    eid = inventory.save_stock_entity(kind="Fornecedor", name="Ent Teste", document="12.345.678/0001-90", city="SP", state="SP", active=True)
    with connection() as conn:
        row = conn.execute("SELECT document, document_hash FROM stock_entities WHERE id = ?", (eid,)).fetchone()
    assert row["document"].startswith("gAAAAA")
    assert crypto.hash_document("12.345.678/0001-90") == row["document_hash"]
    ent = inventory.get_stock_entity(eid)
    assert ent["document"] == "12.345.678/0001-90"
    ents = inventory.list_stock_entities()
    assert ents[ents["id"] == eid]["document"].iloc[0] == "12.345.678/0001-90"
    with transaction() as conn:
        conn.execute("DELETE FROM stock_entities WHERE id = ?", (eid,))
