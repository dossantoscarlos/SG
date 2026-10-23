import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SG_DB_PATH", str(Path(tempfile := __import__("tempfile").gettempdir()) / "sg_test.db"))

from lib import auth, companies, crypto
from lib.database import init_database, connection, transaction


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SG_DB_PATH", str(db))
    init_database(seed_demo=True)
    yield db


def test_authenticate_valid():
    user = auth.authenticate("admin@sg.com.br", "admin123")
    assert user is not None
    assert user["email"] == "admin@sg.com.br"


def test_authenticate_invalid_password():
    user = auth.authenticate("admin@sg.com.br", "wrong")
    assert user is None


def test_authenticate_invalid_email():
    user = auth.authenticate("nope@x.com", "admin123")
    assert user is None


def test_authenticate_inactive_user():
    from lib.database import transaction
    with transaction() as conn:
        conn.execute("UPDATE users SET active = 0 WHERE email_hash = ?", (crypto.hash_email("admin@sg.com.br"),))
    user = auth.authenticate("admin@sg.com.br", "admin123")
    assert user is None


def test_get_user_decrypts_email():
    user = auth.get_user(1)
    assert user is not None
    assert user["email"] == "admin@sg.com.br"


def test_update_profile_encrypts_email():
    auth.update_profile(1, "Administrador", "admin@sg.com.br")
    from lib.database import connection
    with connection() as conn:
        row = conn.execute("SELECT email, email_hash FROM users WHERE id = 1").fetchone()
    assert row["email"].startswith("gAAAAA")
    assert crypto.hash_email("admin@sg.com.br") == row["email_hash"]


def test_companies_default_matriz():
    comps = companies.list_companies(type="matriz")
    assert len(comps) >= 1
    assert comps[0]["type"] == "matriz"


def test_save_company_filial_requires_parent():
    try:
        companies.save_company(name="Filial X", type="filial", parent_id=None)
        assert False, "should raise"
    except Exception as e:
        assert "matriz" in str(e).lower() or "vinculada" in str(e).lower()


def test_save_company_roundtrip():
    cid = companies.save_company(name="Filial Teste", type="filial", parent_id=1, city="Campinas", state="SP")
    c = companies.get_company(cid)
    assert c["name"] == "Filial Teste"
    assert c["type"] == "filial"
    assert c["parent_id"] == 1
    # cleanup
    from lib.database import transaction
    with transaction() as conn:
        conn.execute("DELETE FROM companies WHERE id = ?", (cid,))


def test_branch_stock_view_toggle():
    cid = companies.save_company(name="Filial Toggle", type="filial", parent_id=1, allow_branch_stock_view=False)
    companies.set_branch_stock_view(cid, True, "admin")
    c = companies.get_company(cid)
    assert c["allow_branch_stock_view"] == 1
    companies.set_branch_stock_view(cid, False, "admin")
    c = companies.get_company(cid)
    assert c["allow_branch_stock_view"] == 0
    from lib.database import transaction
    with transaction() as conn:
        conn.execute("DELETE FROM companies WHERE id = ?", (cid,))


def test_list_branches_with_stock():
    branches = companies.list_branches_with_stock(1)
    assert isinstance(branches, list)


def test_user_has_company_admin():
    assert companies.user_has_company(1, 1, is_superuser=True) is True


def test_assign_and_remove_company():
    # create a temp user via direct insert (no helper needed)
    # use direct db insert
    from lib.database import transaction
    import hashlib
    with transaction() as conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, active, is_superuser, must_change_password, created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("Teste User", "teste@x.com", "x", "Consulta", 1, 0, 0, "2026-01-01"),
        )
        uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    companies.assign_company(uid, 1, is_default=True)
    assert companies.user_has_company(uid, 1) is True
    linked = companies.list_user_companies(uid)
    assert len(linked) == 1
    assert linked[0]["is_default"] == 1
    companies.remove_company(uid, 1)
    assert companies.user_has_company(uid, 1) is False
    with transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def test_company_config():
    companies.set_company_config("test_key", "test_value")
    cfg = companies.get_company_config()
    assert cfg.get("test_key") == "test_value"
    # cleanup
    from lib.database import transaction
    with transaction() as conn:
        conn.execute("DELETE FROM company_config WHERE key = 'test_key'")
