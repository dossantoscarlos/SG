"""Identidade visual e tema da empresa (nome, ícone e cores)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_BRANDING_PATH = Path("data") / "branding.json"

_DEFAULTS: dict[str, Any] = {
    "company_name": "SG Gestão",
    "icon_path": "assets/favicon.svg",
    "primary_color": "#0F766E",
    "secondary_color": "#111C2E",
    "tertiary_color": "#E2E8F0",
}


def _normalize_path(path: str | None) -> str:
    return str(path).strip() if path else _DEFAULTS["icon_path"]


def load_branding() -> dict[str, Any]:
    """Carrega a identidade salva, aplicando valores padrão quando faltar."""
    data: dict[str, Any] = dict(_DEFAULTS)
    try:
        if _BRANDING_PATH.exists():
            saved = json.loads(_BRANDING_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update({k: v for k, v in saved.items() if v not in (None, "")})
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    data["company_name"] = str(data.get("company_name") or _DEFAULTS["company_name"]).strip()
    data["icon_path"] = _normalize_path(data.get("icon_path"))
    for key in ("primary_color", "secondary_color", "tertiary_color"):
        value = str(data.get(key) or _DEFAULTS[key]).strip()
        if not value.startswith("#"):
            value = _DEFAULTS[key]
        data[key] = value
    return data


def save_branding(data: dict[str, Any]) -> None:
    """Persiste a identidade visual em ``data/branding.json``."""
    _BRANDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = load_branding()
    merged.update({k: v for k, v in data.items() if v is not None})
    _BRANDING_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_config_theme(primary: str, secondary: str, tertiary: str) -> None:
    """Atualiza as cores do tema no ``.streamlit/config.toml``.

    As mudanças só surtem efeito completo após reiniciar o servidor, mas o
    arquivo fica persistido para a próxima execução.
    """
    config_path = Path(".streamlit") / "config.toml"
    if not config_path.exists():
        return
    text = config_path.read_text(encoding="utf-8")
    # Atualiza primaryColor na seção [theme] (global) e nos temas light/dark.
    import re

    def _replace(key: str, value: str, scope: str | None = None) -> str:
        # Substitui a primeira ocorrência de key = "..." dentro da seção scope.
        if scope is None:
            pattern = rf'(?m)^({re.escape(key)}\s*=\s*)"[^"]*"'
            return re.sub(pattern, rf'\1"{value}"', text, count=1)
        # seção específica
        section_re = re.compile(rf"\[{re.escape(scope)}\]", re.IGNORECASE)
        m = section_re.search(text)
        if not m:
            return text
        start = m.end()
        # próximo '[' de seção
        nxt = text.find("[", start)
        end = nxt if nxt != -1 else len(text)
        head, body, tail = text[:start], text[start:end], text[end:]
        body2 = re.sub(
            rf'(?m)^({re.escape(key)}\s*=\s*)"[^"]*"',
            rf'\1"{value}"',
            body,
            count=1,
        )
        return head + body2 + tail

    # primaryColor global + light + dark
    text = _replace("primaryColor", primary, None)
    text = _replace("primaryColor", primary, "theme.light")
    text = _replace("primaryColor", primary, "theme.dark")
    # secondaryBackgroundColor -> secondary
    text = _replace("secondaryBackgroundColor", secondary, None)
    text = _replace("secondaryBackgroundColor", secondary, "theme.light")
    text = _replace("secondaryBackgroundColor", secondary, "theme.dark")
    # borderColor -> cor terciária
    text = _replace("borderColor", tertiary, None)
    text = _replace("borderColor", tertiary, "theme.light")
    text = _replace("borderColor", tertiary, "theme.dark")
    config_path.write_text(text, encoding="utf-8")
