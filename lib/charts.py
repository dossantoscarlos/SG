"""Gráficos Altair usados no painel."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from lib.ui import (
    CHART_COLORS,
    CHART_COLORS_LIGHT,
    STATUS_COLORS,
    STATUS_COLORS_LIGHT,
)


def _is_dark() -> bool:
    return st.context.theme.type == "dark"


def _palette() -> dict[str, str | float]:
    if _is_dark():
        return {
            "border": "#243244",
            "muted": "#94A3B8",
            "legend": "#CBD5E1",
            "teal": "#2DD4BF",
            "area_opacity": 0.18,
        }
    return {
        "border": "#E2E8F0",
        "muted": "#64748B",
        "legend": "#475569",
        "teal": "#0F766E",
        "area_opacity": 0.14,
    }


def _styled(chart: alt.Chart) -> alt.Chart:
    colors = _palette()
    return (
        chart.configure(background="transparent")
        .configure_view(strokeOpacity=0)
        .configure_axis(
            domain=False,
            ticks=False,
            gridColor=colors["border"],
            gridOpacity=0.7,
            labelColor=colors["muted"],
            titleColor=colors["muted"],
            labelFont="Inter, sans-serif",
            titleFont="Inter, sans-serif",
            labelFontSize=11,
            titleFontSize=11,
        )
        .configure_legend(
            labelColor=colors["legend"],
            titleColor=colors["muted"],
            labelFont="Inter, sans-serif",
            titleFont="Inter, sans-serif",
            orient="bottom",
            columns=3,
            labelLimit=160,
            symbolType="circle",
        )
    )


def revenue_chart(daily: pd.DataFrame) -> alt.Chart:
    colors = _palette()
    base = alt.Chart(daily).encode(
        x=alt.X(
            "data:T",
            title=None,
            axis=alt.Axis(format="%d/%m", tickCount=6, grid=False),
        ),
        y=alt.Y(
            "receita:Q",
            title=None,
            axis=alt.Axis(format="~s", grid=True),
        ),
    )
    tooltip = [
        alt.Tooltip("data:T", title="Data", format="%d/%m/%Y"),
        alt.Tooltip("receita:Q", title="Receita", format=",.2f"),
        alt.Tooltip("pedidos:Q", title="Pedidos"),
    ]
    area = base.mark_area(
        color=colors["teal"], opacity=colors["area_opacity"], line=False
    )
    line = base.mark_line(
        color=colors["teal"], strokeWidth=2.5, interpolate="monotone"
    )
    points = base.mark_circle(
        color=colors["teal"], size=34, opacity=0
    ).encode(tooltip=tooltip)
    return _styled((area + line + points).properties(height=270))


def status_donut(status_counts: pd.DataFrame) -> alt.Chart:
    colors = STATUS_COLORS if _is_dark() else STATUS_COLORS_LIGHT
    data = status_counts.copy()
    order = {status: index for index, status in enumerate(colors)}
    data["_ordem"] = data["status"].map(order).fillna(len(order))
    data = data.sort_values("_ordem").drop(columns="_ordem")
    return _styled(
        alt.Chart(data)
        .mark_arc(innerRadius=62, outerRadius=96, cornerRadius=3)
        .encode(
            theta=alt.Theta("pedidos:Q", stack=True),
            color=alt.Color(
                "status:N",
                title=None,
                scale=alt.Scale(
                    domain=list(colors.keys()),
                    range=list(colors.values()),
                ),
            ),
            tooltip=[
                alt.Tooltip("status:N", title="Status"),
                alt.Tooltip("pedidos:Q", title="Pedidos"),
                alt.Tooltip("valor:Q", title="Valor", format=",.2f"),
            ],
        )
        .properties(height=270)
    )


def top_products_bar(top_products: pd.DataFrame) -> alt.Chart:
    data = top_products.copy().sort_values("receita", ascending=False)
    return _styled(
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=6, color=_palette()["teal"])
        .encode(
            y=alt.Y(
                "produto:N",
                sort="-x",
                title=None,
                axis=alt.Axis(labelLimit=170),
            ),
            x=alt.X(
                "receita:Q",
                title=None,
                axis=alt.Axis(format="~s", grid=True),
            ),
            tooltip=[
                alt.Tooltip("produto:N", title="Produto"),
                alt.Tooltip("categoria:N", title="Categoria"),
                alt.Tooltip("unidades:Q", title="Unidades"),
                alt.Tooltip("receita:Q", title="Receita", format=",.2f"),
            ],
        )
        .properties(height=max(240, len(data) * 38))
    )


def category_donut(by_category: pd.DataFrame) -> alt.Chart:
    colors = CHART_COLORS if _is_dark() else CHART_COLORS_LIGHT
    data = by_category.copy()
    return _styled(
        alt.Chart(data)
        .mark_arc(innerRadius=56, outerRadius=94, cornerRadius=3)
        .encode(
            theta=alt.Theta("receita:Q", stack=True),
            color=alt.Color(
                "categoria:N",
                title=None,
                scale=alt.Scale(range=colors),
            ),
            tooltip=[
                alt.Tooltip("categoria:N", title="Categoria"),
                alt.Tooltip("unidades:Q", title="Unidades"),
                alt.Tooltip("receita:Q", title="Receita", format=",.2f"),
            ],
        )
        .properties(height=270)
    )


def payment_donut(payment_methods: pd.DataFrame) -> alt.Chart:
    colors = CHART_COLORS if _is_dark() else CHART_COLORS_LIGHT
    data = payment_methods.copy()
    return _styled(
        alt.Chart(data)
        .mark_arc(innerRadius=56, outerRadius=94, cornerRadius=3)
        .encode(
            theta=alt.Theta("receita:Q", stack=True),
            color=alt.Color(
                "forma_pagamento:N",
                title=None,
                scale=alt.Scale(range=colors),
            ),
            tooltip=[
                alt.Tooltip("forma_pagamento:N", title="Forma de pagamento"),
                alt.Tooltip("pedidos:Q", title="Pedidos"),
                alt.Tooltip("receita:Q", title="Receita", format=",.2f"),
            ],
        )
        .properties(height=250)
    )
