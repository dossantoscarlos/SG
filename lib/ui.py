"""Componentes visuais e formatadores compartilhados."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from typing import Any

import streamlit as st

# Paletas dos gráficos por aparência. `STATUS_COLORS` e `CHART_COLORS`
# continuam sendo as cores do modo escuro; as variantes `_LIGHT` são usadas
# quando o painel está no modo claro.
STATUS_COLORS = {
    "Pendente": "#FBBF24",
    "Pago": "#60A5FA",
    "Enviado": "#A78BFA",
    "Entregue": "#34D399",
    "Cancelado": "#F87171",
}

STATUS_COLORS_LIGHT = {
    "Pendente": "#F59E0B",
    "Pago": "#3B82F6",
    "Enviado": "#8B5CF6",
    "Entregue": "#10B981",
    "Cancelado": "#EF4444",
}

STATUS_BADGE_COLORS = {
    "Pendente": "orange",
    "Pago": "blue",
    "Enviado": "violet",
    "Entregue": "green",
    "Cancelado": "red",
}

# Cores de fundo para etiquetas em tabelas. O texto das etiquetas é branco,
# então estes tons precisam manter contraste AA sobre o branco.
STATUS_TAG_COLORS = {
    "Pendente": "#B45309",
    "Pago": "#2563EB",
    "Enviado": "#7C3AED",
    "Entregue": "#047857",
    "Cancelado": "#DC2626",
}

STATUS_ICONS = {
    "Pendente": ":material/schedule:",
    "Pago": ":material/payments:",
    "Enviado": ":material/local_shipping:",
    "Entregue": ":material/check_circle:",
    "Cancelado": ":material/cancel:",
}

CUSTOMER_STATUS_COLORS = {"Ativo": "green", "Inativo": "gray"}

CHART_COLORS = [
    "#2DD4BF",
    "#60A5FA",
    "#A78BFA",
    "#FB923C",
    "#F472B6",
    "#FBBF24",
    "#94A3B8",
    "#22D3EE",
]

CHART_COLORS_LIGHT = [
    "#0F766E",
    "#2563EB",
    "#7C3AED",
    "#EA580C",
    "#DB2777",
    "#CA8A04",
    "#64748B",
    "#0891B2",
]


def money(value: float | int | None) -> str:
    value = float(value or 0)
    formatted = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {formatted}" if value < 0 else f"R$ {formatted}"


def money_md(value: float | int | None) -> str:
    """Valor monetário seguro para textos Markdown do Streamlit."""
    return money(value).replace("$", r"\$")


def money_compact(value: float | int | None) -> str:
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{sign}R$ {absolute / 1_000_000:.1f} mi".replace(".", ",")
    if absolute >= 1_000:
        return f"{sign}R$ {absolute / 1_000:.1f} mil".replace(".", ",")
    return money(value)


def number_br(value: float | int | None, decimals: int = 0) -> str:
    value = float(value or 0)
    formatted = f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return formatted


def percent(value: float | int | None, decimals: int = 1) -> str:
    value = float(value or 0) * 100
    return f"{number_br(value, decimals)}%"


def date_br(value) -> str:
    if value is None:
        return "—"
    try:
        if isinstance(value, float) and math.isnan(value):
            return "—"
        parsed = value if isinstance(value, (date, datetime)) else datetime.fromisoformat(str(value))
        return parsed.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "—"


def datetime_br(value) -> str:
    if value is None:
        return "—"
    try:
        if isinstance(value, float) and math.isnan(value):
            return "—"
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return parsed.strftime("%d/%m/%Y · %H:%M")
    except (ValueError, TypeError):
        return "—"


def delta_percent(current: float, previous: float) -> str | int | None:
    if previous in (0, None):
        return None
    pct = ((float(current) - float(previous)) / float(previous)) * 100
    if abs(pct) < 0.05:
        return 0
    return f"{pct:+.1f}%".replace(".", ",")


def status_badge(status: str) -> None:
    st.badge(
        status,
        color=STATUS_BADGE_COLORS.get(status, "gray"),
        icon=STATUS_ICONS.get(status),
    )


def customer_status_badge(status: str) -> None:
    icons = {"Ativo": ":material/check_circle:", "Inativo": ":material/pause_circle:"}
    st.badge(
        status,
        color=CUSTOMER_STATUS_COLORS.get(status, "gray"),
        icon=icons.get(status),
    )


def set_flash(message: str, icon: str = ":material/check_circle:") -> None:
    st.session_state["_flash"] = {"message": message, "icon": icon}


def show_flash() -> None:
    flash = st.session_state.pop("_flash", None)
    if flash:
        st.toast(flash["message"], icon=flash.get("icon"))


def page_header(title: str, subtitle: str, icon: str | None = None) -> None:
    st.title(title, icon=icon)
    st.caption(subtitle)


def empty_state(title: str, description: str) -> None:
    with st.container(border=True, horizontal_alignment="center"):
        st.markdown(f"### {title}")
        st.caption(description)


def table_key(prefix: str, *parts: object) -> str:
    digest = hashlib.md5("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:12]}"


def selected_row_index(
    event: Any,
    row_count: int,
    *,
    signature: object,
    state_key: str,
) -> int | None:
    """Resolve a seleção da tabela, ignorando eventos de filtros anteriores.

    O Streamlit pode devolver por um rerun a seleção antiga logo depois que os
    filtros mudam. A assinatura evita usar esse índice em outra lista e o limite
    de linhas impede o acesso fora da faixa.
    """
    if st.session_state.get(state_key) != signature:
        st.session_state[state_key] = signature
        return None

    rows = event.selection.rows if event and event.selection else []
    if not rows:
        return None

    try:
        index = int(rows[0])
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < row_count else None


def selected_cell(
    event: Any,
    row_count: int,
    *,
    signature: object,
    state_key: str,
) -> tuple[int, str] | None:
    """Resolve uma célula selecionada, ignorando eventos antigos."""
    if st.session_state.get(state_key) != signature:
        st.session_state[state_key] = signature
        return None

    cells = event.selection.cells if event and event.selection else []
    if not cells:
        return None

    try:
        row, column = cells[0]
        index = int(row)
    except (TypeError, ValueError):
        return None
    if not 0 <= index < row_count:
        return None
    return index, str(column)


def initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    if not parts:
        return "SG"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()
