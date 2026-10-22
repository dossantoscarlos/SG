"""Funções de hash e validação de senhas.

As senhas nunca são armazenadas em texto puro. O formato scrypt inclui os
parâmetros usados, permitindo atualizar o custo no futuro sem quebrar hashes
antigos.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("A senha não pode ser vazia.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LENGTH,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, digest_b64 = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(digest_b64)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> list[str]:
    """Retorna uma lista de problemas encontrados na senha."""
    problems: list[str] = []
    if len(password) < 8:
        problems.append("Use pelo menos 8 caracteres.")
    if not any(char.isalpha() for char in password):
        problems.append("Inclua pelo menos uma letra.")
    if not any(char.isdigit() for char in password):
        problems.append("Inclua pelo menos um número.")
    return problems
