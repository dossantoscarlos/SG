import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SG_DB_PATH", str(Path(__import__("tempfile").gettempdir()) / "sg_test.db"))

from lib import auth, companies, crypto, inventory
from lib.database import init_database, connection, transaction


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SG_DB_PATH", str(db))
    init_database(seed_demo=True)
    yield db


def test_auth_rejects_wrong_password():
    assert auth.authenticate("admin@sg.com.br", "wrong") is None


def test_auth_rejects_unknown_email():
    assert auth.authenticate("nope@x.com", "admin123") is None


def test_auth_returns_decrypted_email():
    user = auth.authenticate("admin@sg.com.br", "admin123")
    assert user is not None
    assert user["email"] == "admin@sg.com.br"
    assert "@" in user["email"]


def test_company_isolation_list_products():
    # Products filtered by company_id
    from lib import catalog
    df1 = catalog.list_products(company_id=1)
    df2 = catalog.list_products(company_id=9999)
    assert not df1.empty
    assert df2.empty


def test_branch_stock_view_toggle():
    cid = companies.save_company(name="Filial Reg", type="filial", parent_id=1, allow_branch_stock_view=False)
    companies.set_branch_stock_view(cid, True, "admin")
    c = companies.get_company(cid)
    assert c["allow_branch_stock_view"] == 1
    companies.set_branch_stock_view(cid, False, "admin")
    c = companies.get_company(cid)
    assert c["allow_branch_stock_view"] == 0
    with transaction() as conn:
        conn.execute("DELETE FROM companies WHERE id = ?", (cid,))


def test_branch_stock_view_only_for_filial():
    try:
        companies.set_branch_stock_view(1, True, "admin")  # matriz
        assert False, "should raise"
    except Exception as e:
        assert "filial" in str(e).lower()


def test_user_company_link():
    from lib.database import transaction
    with transaction() as conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, active, is_superuser, must_change_password, created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("U", "u@x.com", "x", "Consulta", 1, 0, 0, "2026-01-01"),
        )
        uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    companies.assign_company(uid, 1, is_default=True)
    assert companies.user_has_company(uid, 1) is True
    assert companies.user_has_company(uid, 9999) is False
    assert companies.user_has_company(uid, 9999, is_superuser=True) is True
    linked = companies.list_user_companies(uid)
    assert len(linked) == 1
    companies.remove_company(uid, 1)
    assert not companies.user_has_company(uid, 1)
    with transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def test_inventory_reversal_restores_stock():
    with connection() as conn:
        p = conn.execute("SELECT * FROM products ORDER BY id LIMIT 1").fetchone()
    before = p["stock"]
    entity_id = inventory.save_stock_entity(kind="Fornecedor", name="Forn", document=None, city=None, state=None, active=True)
    doc = inventory.create_stock_document(
        kind="Entrada",
        items=[{"product_id": p["id"], "quantity": 5, "unit_cost": 3.0}],
        reason="teste",
        actor="Teste",
        entity_kind="Fornecedor",
        entity_id=entity_id,
        status="Concluído",
    )
    inventory.reverse_stock_document(doc, actor="Teste")
    with connection() as conn:
        after = conn.execute("SELECT stock FROM products WHERE id = ?", (p["id"],)).fetchone()[0]
    assert after == before
