"""Relatórios de vendas, produtos, clientes e pagamentos."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import acl, analytics, charts, reports, ui

PERIODS = ("7 dias", "30 dias", "90 dias", "Este ano", "Personalizado")

user = acl.require("reports.view_report")


def _period_range(period: str) -> tuple[date, date]:
    today = date.today()
    if period == "7 dias":
        return today - timedelta(days=6), today
    if period == "90 dias":
        return today - timedelta(days=89), today
    if period == "Este ano":
        return date(today.year, 1, 1), today
    if period == "Personalizado":
        start = st.session_state.get(
            "reports_custom_start", today - timedelta(days=29)
        )
        end = st.session_state.get("reports_custom_end", today)
        return start, end
    return today - timedelta(days=29), today


ui.page_header(
    "Relatórios",
    "Analise receita, produtos, clientes e formas de pagamento em cada período.",
    icon=":material/analytics:",
)

with st.container(border=True):
    filter_col, export_col = st.columns(
        [2.8, 1.3], vertical_alignment="bottom", gap="large"
    )

    with filter_col:
        period = st.segmented_control(
            "Período do relatório",
            options=list(PERIODS),
            default="30 dias",
            key="reports_period",
            wrap=True,
            width="stretch",
        )
        period = period or "30 dias"

        if period == "Personalizado":
            date_col, end_col = st.columns(2)
            with date_col:
                st.date_input(
                    "Data inicial",
                    value=date.today() - timedelta(days=29),
                    max_value=date.today(),
                    key="reports_custom_start",
                )
            with end_col:
                st.date_input(
                    "Data final",
                    value=date.today(),
                    max_value=date.today(),
                    key="reports_custom_end",
                )

    start_date, end_date = _period_range(period)

    if start_date > end_date:
        with filter_col:
            st.error(
                "A data inicial não pode ser posterior à data final.",
                icon=":material/error:",
            )
        st.stop()

    report = analytics.get_report(start_date, end_date)
    can_export = acl.has_perm(user, "reports.export_report")

    with export_col:
        st.caption("Exportar relatório")
        if can_export:
            excel_data = reports.build_excel(report)
            csv_data = reports.build_csv(report)
            with st.container(horizontal=True, wrap=True):
                st.download_button(
                    "Excel",
                    data=excel_data,
                    file_name=reports.export_filename(report, "xlsx"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    icon=":material/download:",
                    type="primary",
                    key="reports_download_excel",
                )
                st.download_button(
                    "CSV",
                    data=csv_data,
                    file_name=reports.export_filename(report, "csv"),
                    mime="text/csv",
                    icon=":material/download:",
                    key="reports_download_csv",
                )
        else:
            st.caption("Seu perfil não permite exportar relatórios.")

summary = report["summary"]
period_label = (
    f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
)

st.caption(f"Resultados de {period_label}, considerando apenas vendas confirmadas.")
metric_cols = st.columns(4)
metric_cols[0].metric(
    "Receita confirmada",
    ui.money_compact(summary["revenue"]),
    border=True,
    icon=":material/payments:",
    help=f"Receita total: {ui.money(summary['revenue'])}.",
)
metric_cols[1].metric(
    "Pedidos confirmados",
    ui.number_br(summary["orders_count"]),
    border=True,
    icon=":material/receipt_long:",
    help="Pedidos pagos, enviados ou entregues no período.",
)
metric_cols[2].metric(
    "Ticket médio",
    ui.money_compact(summary["avg_ticket"]),
    border=True,
    icon=":material/trending_up:",
    help="Receita confirmada dividida pelo número de pedidos confirmados.",
)
metric_cols[3].metric(
    "Lucro bruto",
    ui.money_compact(summary["gross_profit"]),
    border=True,
    icon=":material/savings:",
    help=(
        f"Receita de itens menos custo e descontos: {ui.money(summary['gross_profit'])}. "
        f"Margem bruta de {ui.percent(summary['gross_margin'])}."
    ),
)

st.markdown(
    f":green-badge[:material/percent: Margem bruta {ui.percent(summary['gross_margin'])}] "
    f":blue-badge[:material/inventory_2: {ui.number_br(summary['units_sold'])} itens vendidos] "
    f":orange-badge[:material/sell: {ui.money(summary['discounts'])} em descontos]"
)

st.space("small")
revenue_col, category_col = st.columns([1.7, 1], gap="large")

with revenue_col:
    with st.container(border=True):
        st.subheader("Receita no período")
        st.caption(period_label)
        if summary["revenue"] > 0:
            st.altair_chart(
                charts.revenue_chart(report["daily"]),
                alt="Evolução diária da receita confirmada no período",
            )
        else:
            st.caption("Nenhuma venda confirmada neste período.")

with category_col:
    with st.container(border=True):
        st.subheader("Receita por categoria")
        st.caption("Participação de cada categoria no faturamento.")
        by_category = report["by_category"]
        if not by_category.empty:
            st.altair_chart(
                charts.category_donut(by_category),
                alt="Participação das categorias na receita do período",
            )
        else:
            st.caption("Nenhuma categoria com vendas confirmadas no período.")

products_col, payments_col = st.columns([1.4, 1], gap="large")

with products_col:
    with st.container(border=True):
        st.subheader("Produtos com maior receita")
        st.caption("Os 10 produtos mais relevantes no faturamento.")
        top_products = report["top_products"]
        if not top_products.empty:
            st.altair_chart(
                charts.top_products_bar(top_products),
                alt="Produtos com maior receita no período",
            )
        else:
            st.caption("Nenhum produto vendido neste período.")

with payments_col:
    with st.container(border=True):
        st.subheader("Formas de pagamento")
        st.caption("Distribuição da receita por meio de pagamento.")
        payments = report["payment_methods"]
        if not payments.empty:
            st.altair_chart(
                charts.payment_donut(payments),
                alt="Distribuição da receita por forma de pagamento",
            )
        else:
            st.caption("Nenhum pagamento confirmado neste período.")

with st.container(border=True):
    st.subheader("Clientes que mais compraram")
    st.caption("Ranking por receita confirmada no período.")
    top_customers = report["top_customers"]
    if top_customers.empty:
        st.caption("Nenhum cliente com compras confirmadas neste período.")
    else:
        display_customers = pd.DataFrame(
            {
                "Cliente": top_customers["cliente"],
                "E-mail": top_customers["email"].fillna("—"),
                "Local": [
                    f"{city}/{state}" if city and state else (city or state or "—")
                    for city, state in zip(top_customers["cidade"], top_customers["uf"])
                ],
                "Pedidos": top_customers["pedidos"],
                "Receita": top_customers["receita"],
                "Último pedido": pd.to_datetime(
                    top_customers["ultimo_pedido"], errors="coerce"
                ).dt.strftime("%d/%m/%Y"),
            }
        )
        st.dataframe(
            display_customers,
            hide_index=True,
            height=min(430, 38 + len(display_customers) * 36),
            alt="Ranking de clientes por receita confirmada no período",
            column_config={
                "E-mail": st.column_config.TextColumn("E-mail", width="medium"),
                "Local": st.column_config.TextColumn("Local", width="small"),
                "Pedidos": st.column_config.NumberColumn(
                    "Pedidos", format="%d", width="small"
                ),
                "Receita": st.column_config.NumberColumn(
                    "Receita", format="R$ %.2f", width="small"
                ),
                "Último pedido": st.column_config.TextColumn(
                    "Último pedido", width="small"
                ),
            },
        )

st.space("small")
st.subheader("Detalhamento do período")
orders_detail = report["orders_detail"]
items_detail = report["items_detail"]

orders_tab, items_tab = st.tabs(
    [
        f"Pedidos ({len(orders_detail)})",
        f"Itens vendidos ({len(items_detail)})",
    ]
)

with orders_tab:
    if orders_detail.empty:
        st.caption("Nenhum pedido confirmado neste período.")
    else:
        display_orders = pd.DataFrame(
            {
                "Pedido": orders_detail["pedido"],
                "Data": pd.to_datetime(
                    orders_detail["data"], errors="coerce"
                ).dt.strftime("%d/%m/%Y"),
                "Cliente": orders_detail["cliente"],
                "Status": [[status] for status in orders_detail["status"]],
                "Pagamento": orders_detail["pagamento"],
                "Canal": orders_detail["canal"],
                "Itens": orders_detail["itens"],
                "Total": orders_detail["total"],
            }
        )
        st.dataframe(
            display_orders,
            hide_index=True,
            height=420,
            alt="Pedidos confirmados no período com cliente, status e total",
            column_config={
                "Pedido": st.column_config.TextColumn(
                    "Pedido", width=128, pinned=True
                ),
                "Data": st.column_config.TextColumn("Data", width=96),
                "Cliente": st.column_config.TextColumn("Cliente", width=170),
                "Status": st.column_config.MultiselectColumn(
                    "Status",
                    options=list(ui.STATUS_COLORS.keys()),
                    color=list(ui.STATUS_TAG_COLORS.values()),
                    width=108,
                ),
                "Pagamento": st.column_config.TextColumn(
                    "Pagamento", width=124
                ),
                "Canal": st.column_config.TextColumn("Canal", width=108),
                "Itens": st.column_config.NumberColumn(
                    "Itens", format="%d", width=64
                ),
                "Total": st.column_config.NumberColumn(
                    "Total", format="R$ %.2f", width=104
                ),
            },
        )

with items_tab:
    if items_detail.empty:
        st.caption("Nenhum item vendido neste período.")
    else:
        display_items = pd.DataFrame(
            {
                "Pedido": items_detail["pedido"],
                "Data": pd.to_datetime(
                    items_detail["data"], errors="coerce"
                ).dt.strftime("%d/%m/%Y"),
                "Cliente": items_detail["cliente"],
                "SKU": items_detail["sku"],
                "Produto": items_detail["produto"],
                "Categoria": items_detail["categoria"],
                "Qtd.": items_detail["quantidade"],
                "Valor unit.": items_detail["valor_unitario"],
                "Total": items_detail["total_item"],
            }
        )
        st.dataframe(
            display_items,
            hide_index=True,
            height=420,
            alt="Itens vendidos no período com produto, quantidade e valores",
            column_config={
                "Pedido": st.column_config.TextColumn(
                    "Pedido", width=128, pinned=True
                ),
                "Data": st.column_config.TextColumn("Data", width=96),
                "Cliente": st.column_config.TextColumn("Cliente", width=150),
                "SKU": st.column_config.TextColumn("SKU", width=86),
                "Produto": st.column_config.TextColumn("Produto", width=190),
                "Categoria": st.column_config.TextColumn(
                    "Categoria", width=108
                ),
                "Qtd.": st.column_config.NumberColumn(
                    "Qtd.", format="%d", width=64
                ),
                "Valor unit.": st.column_config.NumberColumn(
                    "Valor unit.", format="R$ %.2f", width=112
                ),
                "Total": st.column_config.NumberColumn(
                    "Total", format="R$ %.2f", width=104
                ),
            },
        )

st.caption(
    "Receita confirmada considera pedidos pagos, enviados e entregues. "
    "O lucro bruto é uma estimativa que usa o custo registrado no momento da venda."
)
