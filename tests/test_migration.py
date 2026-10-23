import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SG_DB_PATH", str(Path(__import__("tempfile").gettempdir()) / "sg_test.db"))

from lib.database import init_database, connection
from lib import crypto


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SG_DB_PATH", str(db))
    init_database(seed_demo=True)
    yield db


def test_migration_user_version():
    with connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 8


def test_migration_integrity():
    with connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_users_have_email_hash():
    with connection() as conn:
        rows = conn.execute("SELECT id, email, email_hash FROM users").fetchall()
    for row in rows:
        assert row["email"].startswith("gAAAAA"), f"user {row['id']} email not encrypted"
        assert row["email_hash"] is not None
        assert len(row["email_hash"]) == 64


def test_migration_customers_have_email_hash():
    with connection() as conn:
        rows = conn.execute("SELECT id, email, email_hash FROM customers").fetchall()
    for row in rows:
        assert row["email"].startswith("gAAAAA"), f"customer {row['id']} email not encrypted"
        assert row["email_hash"] is not None


def test_migration_products_have_company():
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        with_company = conn.execute("SELECT COUNT(*) FROM products WHERE company_id IS NOT NULL").fetchone()[0]
    assert with_company == total


def test_migration_default_company_exists():
    with connection() as conn:
        row = conn.execute("SELECT id, type FROM companies WHERE type = 'matriz'").fetchone()
    assert row is not None


def test_migration_user_companies_exists():
    with connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM user_companies").fetchone()[0]
    assert count > 0


def test_migration_idempotent():
    # Re-running init_database should not break anything
    from lib.database import init_database
    init_database(seed_demo=True)
    with connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 8
