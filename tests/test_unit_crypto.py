import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import crypto


def test_normalize_email():
    assert crypto.normalize_email("  Foo@Bar.com ") == "foo@bar.com"
    assert crypto.normalize_email(None) == ""


def test_normalize_document():
    assert crypto.normalize_document("12.345.678/0001-90") == "12345678000190"
    assert crypto.normalize_document(None) == ""


def test_encrypt_decrypt_roundtrip():
    plain = "ana.souza@email.com"
    enc = crypto.encrypt(plain)
    assert enc != plain
    assert enc.startswith("gAAAAA")
    assert crypto.decrypt(enc) == plain


def test_encrypt_none():
    assert crypto.encrypt(None) is None
    assert crypto.encrypt("") is None
    assert crypto.decrypt(None) is None
    assert crypto.decrypt("") is None


def test_hash_deterministic():
    h1 = crypto.hash_email("Foo@Bar.com")
    h2 = crypto.hash_email("  foo@bar.com ")
    assert h1 == h2
    assert h1 is not None
    assert len(h1) == 64


def test_hash_different_values():
    assert crypto.hash_email("a@b.com") != crypto.hash_email("c@d.com")


def test_hash_empty():
    assert crypto.hash_email(None) is None
    assert crypto.hash_email("") is None
    assert crypto.hash_email("   ") is None


def test_decrypt_legacy_plaintext():
    # Valores antigos em texto claro devem ser devolvidos como estão.
    assert crypto.decrypt("admin@sg.com.br") == "admin@sg.com.br"


def test_contrast_color():
    from lib import branding
    assert branding.contrast_color("#FFFFFF") == "#111827"
    assert branding.contrast_color("#000000") == "#FFFFFF"
    assert branding.contrast_color("#FBBF24") == "#111827"
    assert branding.contrast_color("#0F766E") == "#FFFFFF"
    assert branding.contrast_color("invalid") == "#FFFFFF"
