"""Criptografia simétrica e hash determinístico para dados sensíveis.

Usa Fernet (AES-128-CBC + HMAC) para armazenamento reversível de e-mails
e documentos (CPF/CNPJ), e HMAC-SHA256 para busca determinística. A chave é
persistida em ``data/.secret_key`` para que os valores continuem legíveis
entre reinícios do servidor.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.fernet import Fernet

_KEY_PATH = Path("data") / ".secret_key"


def _load_or_create_key() -> bytes:
    try:
        if _KEY_PATH.exists():
            raw = _KEY_PATH.read_bytes().strip()
            if raw:
                # Aceita chave Fernet (44 bytes base64) ou deriva uma.
                try:
                    Fernet(raw)
                    return raw
                except Exception:
                    pass
    except OSError:
        pass
    key = Fernet.generate_key()
    try:
        _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _KEY_PATH.write_bytes(key)
        try:
            os.chmod(_KEY_PATH, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return key


_FERNET = Fernet(_load_or_create_key())
_HMAC_KEY = _FERNET._signing_key  # 32 bytes derivados da chave Fernet


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize_document(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return _FERNET.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _FERNET.decrypt(value.encode("ascii")).decode("utf-8")
    except Exception:
        # Valor antigo em texto claro: devolve como está.
        return value


def hash_email(value: str | None) -> str | None:
    normalized = normalize_email(value)
    if not normalized:
        return None
    return hmac.new(_HMAC_KEY, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_document(value: str | None) -> str | None:
    normalized = normalize_document(value)
    if not normalized:
        return None
    return hmac.new(_HMAC_KEY, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
