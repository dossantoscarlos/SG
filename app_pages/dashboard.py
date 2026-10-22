"""Visão geral do negócio."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import acl, analytics, charts, ui
from lib.order_ui import open_new_order_dialog

PERIODS = {"7 dias": 7, "30 dias": 30, "90 dias": 90}

user = acl.require("dashboard.view_dashboard")

header_left, header_right = st.columns([1.6, 1], vertical_alignment="center")
with header_left:
    ui.page_header(
        "Visão geral",
        "Acompanhe o desempenho do negócio e o que precisa de atenção hoje.",
        icon=":material/space_dashboard:",
    )
with header_right:
    with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
        period_label = st.segmented_control(
            "Período",
            options=list(PERIODS.keys()),
            default="30 dias",
            label_visibility="collapsed",
            key="dashboard_period",
        )
        if acl.has_perm(user, "orders.add_order"):
            if st.button(
                "Novo pedido",
                icon=":material/add:",
                type="primary",
                key="dashboard_new_order",
            ):
                open_new_order_dialog()

period_label = period_label or "30 dias"
period_days = PERIODS[period_label]
end_date = date.today()
start_date = end_date - timedelta(days=period_days - 1)
data = analytics.get_dashboard(start_date, end_date)
summary = data["summary"]
previous = data["previous"]
daily = data["daily"]

if user.get("must_change_password"):
    st.warning(
        "Você ainda está usando a senha inicial. Altere a senha em Configurações para proteger o acesso.",
        title="Proteja sua conta",
        icon=":material/lock_reset:",
    )

revenue_delta = ui.delta_percent(summary["revenue"], previous["revenue"])
orders_delta = ui.delta_percent(summary["orders_count"], previous["orders_count"])
ticket_delta = ui.delta_percent(summary["avg_ticket"], previous["avg_ticket"])
customers_delta = ui.delta_percent(summary["new_customers"], previous["new_customers"])
description = f"vs. {period_days} dias anteriores"
daily_ticket = [
    (float(revenue) / int(orders)) if orders else 0
    for revenue, orders in zip(daily["receita"], daily["pedidos_pagos"])
]

metric_cols = st.columns(4)
metric_cols[0].metric(
    "Receita confirmada",
    ui.money_compact(summary["revenue"]),
    delta=revenue_delta,
    delta_description=description,
    border=True,
    height="stretch",
    chart_data=daily["receita"].tolist(),
    chart_type="line",
    help=f"Receita total: {ui.money(summary['revenue'])}. Considera pedidos pagos, enviados e entregues.",
)
metric_cols[1].metric(
    "Pedidos",
    ui.number_br(summary["orders_count"]),
    delta=orders_delta,
    delta_description=description,
    border=True,
    height="stretch",
    chart_data=daily["pedidos"].tolist(),
    chart_type="bar",
    help="Todos os pedidos criados no período, incluindo cancelados.",
)
metric_cols[2].metric(
    "Ticket médio",
    ui.money_compact(summary["avg_ticket"]),
    delta=ticket_delta,
    delta_description=description,
    border=True,
    height="stretch",
    chart_data=daily_ticket,
    chart_type="line",
    help="Receita confirmada dividida pelo número de pedidos confirmados.",
)
metric_cols[3].metric(
    "Novos clientes",
    ui.number_br(summary["new_customers"]),
    delta=customers_delta,
    delta_description=description,
    border=True,
    height="stretch",
    chart_data=daily["novos_clientes"].tolist(),
    chart_type="bar",
    help="Clientes cadastrados no período selecionado.",
)

st.space("small")
revenue_col, status_col = st.columns([1.7, 1], gap="large")

with revenue_col:
    with st.container(border=True):
        st.subheader("Receita no período")
        st.caption(f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}")
        if summary["revenue"] > 0:
            st.altair_chart(
                charts.revenue_chart(daily),
                alt="Evolução diária da receita confirmada no período",
            )
        else:
            st.caption("Ainda não há receita confirmada neste período.")

with status_col:
    with st.container(border=True):
        st.subheader("Pedidos por status")
        st.caption("Distribuição dos pedidos criados no período.")
        status_counts = data["status_counts"]
        if not status_counts.empty:
            st.altair_chart(
                charts.status_donut(status_counts),
                alt="Distribuição dos pedidos por status",
            )
        else:
            st.caption("Nenhum pedido criado neste período.")

products_col, stock_col = st.columns([1.35, 1], gap="large")

with products_col:
    with st.container(border=True):
        st.subheader("Produtos com maior receita")
        st.caption("Receita em produtos, sem frete e descontos.")
        top_products = data["top_products"]
        if not top_products.empty:
            st.altair_chart(
                charts.top_products_bar(top_products),
                alt="Produtos com maior receita no período",
            )
        else:
            st.caption("Ainda não há vendas confirmadas no período.")

with stock_col:
    with st.container(border=True):
        st.subheader("Atenção ao estoque")
        st.caption("Produtos no ou abaixo do estoque mínimo.")
        low_stock = data["low_stock"]
        if low_stock.empty:
            st.markdown(":green-badge[:material/check_circle: Estoque saudável]")
            st.caption("Nenhum produto precisa de reposição agora.")
        else:
            for row in low_stock.itertuples():
                info_col, badge_col = st.columns([3, 1], vertical_alignment="center")
                with info_col:
                    st.markdown(f"**{row.name}**")
                    st.caption(f"{row.sku} · mínimo de {row.min_stock} un.")
                with badge_col:
                    color = "red" if row.stock == 0 else "orange"
                    label = "Sem estoque" if row.stock == 0 else f"{row.stock} un."
                    st.badge(label, color=color)

st.space("small")
with st.container(border=True):
    st.subheader("Pedidos recentes")
    st.caption("Os últimos pedidos registrados, independentemente do período.")
    recent = data["recent_orders"].copy()
    if recent.empty:
        st.caption("Nenhum pedido registrado.")
    else:
        display = pd.DataFrame(
            {
                "Pedido": recent["number"],
                "Cliente": recent["customer_name"],
                "Data": pd.to_datetime(recent["created_at"]).dt.strftime("%d/%m/%Y · %H:%M"),
                "Itens": recent["item_count"],
                "Total": [ui.money(value) for value in recent["total"]],
                "Status": [[status] for status in recent["status"]],
            }
        )
        st.dataframe(
            display,
            hide_index=True,
            height=38 + len(display) * 36,
            alt="Pedidos mais recentes com cliente, data, total e status",
            column_config={
                "Itens": st.column_config.NumberColumn("Itens", format="%d"),
                "Total": st.column_config.TextColumn("Total"),
                "Status": st.column_config.MultiselectColumn(
                    "Status",
                    options=list(ui.STATUS_COLORS.keys()),
                    color=list(ui.STATUS_TAG_COLORS.values()),
                ),
            },
        )
