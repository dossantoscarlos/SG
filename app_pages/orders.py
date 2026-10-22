"""Gestão de pedidos e vendas."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import acl, orders, ui
from lib.database import OPEN_STATUSES, ORDER_STATUSES, REVENUE_STATUSES
from lib.errors import DomainError
from lib.order_ui import open_new_order_dialog

user = acl.require("orders.view_order")


@st.dialog("Detalhes do pedido", width="large", icon=":material/receipt_long:")
def order_detail_dialog(order_id: int) -> None:
    if not acl.can_current("orders.view_order"):
        st.error("Seu perfil não permite consultar pedidos.")
        return
    order = orders.get_order(order_id)
    if order is None:
        st.error("Pedido não encontrado.")
        return
    items = orders.get_order_items(order_id)

    title_col, badge_col = st.columns([2, 1], vertical_alignment="center")
    with title_col:
        st.subheader(order["number"])
        st.caption(f"Criado em {ui.datetime_br(order['created_at'])}")
    with badge_col:
        with st.container(horizontal_alignment="right"):
            ui.status_badge(order["status"])

    with st.container(border=True):
        customer_col, meta_col = st.columns(2)
        with customer_col:
            st.caption("Cliente")
            st.markdown(f"**{order['customer_name']}**")
            st.caption(
                f"{order['customer_email'] or 'Sem e-mail'} · "
                f"{order['customer_phone'] or 'Sem telefone'}"
            )
            st.caption(
                f"{order['customer_city'] or 'Cidade não informada'}/"
                f"{order['customer_state'] or '—'}"
            )
        with meta_col:
            st.caption("Pagamento e origem")
            st.markdown(f"**{order['payment_method']}**")
            st.caption(f"Canal: {order['channel']}")
            st.caption(f"Status: {order['status']}")

    st.markdown("**Itens do pedido**")
    if not items.empty:
        items_display = pd.DataFrame(
            {
                "Produto": items["product_name"],
                "SKU": items["sku"],
                "Qtd.": items["quantity"],
                "Valor unit.": [ui.money(value) for value in items["unit_price"]],
                "Subtotal": [ui.money(value) for value in items["line_total"]],
            }
        )
        st.dataframe(
            items_display,
            hide_index=True,
            alt="Itens incluídos no pedido com quantidade e valores",
            column_config={
                "Qtd.": st.column_config.NumberColumn("Qtd.", format="%d", width="small"),
                "Valor unit.": st.column_config.TextColumn("Valor unit.", width="small"),
                "Subtotal": st.column_config.TextColumn("Subtotal", width="small"),
            },
        )
        subtotal = float(items["line_total"].sum())
    else:
        st.caption("Este pedido não possui itens registrados.")
        subtotal = 0.0

    total_col, summary_col = st.columns([1, 1.8], vertical_alignment="center")
    with total_col:
        st.metric("Total do pedido", ui.money(order["total"]), border=True)
    with summary_col:
        st.caption(
            f"Subtotal {ui.money_md(subtotal)} · Desconto {ui.money_md(order['discount'])} · "
            f"Frete {ui.money_md(order['shipping'])}"
        )
        if order["notes"]:
            st.caption(f"Observações: {order['notes']}")

    st.space("small")
    if acl.can_current("orders.change_order"):
        st.markdown("**Atualizar status**")
        new_status = st.selectbox(
            "Novo status",
            options=list(ORDER_STATUSES),
            index=list(ORDER_STATUSES).index(order["status"]),
            key=f"order_status_select_{order_id}",
        )
        if new_status == "Cancelado" and order["status"] != "Cancelado":
            st.caption("Ao cancelar, os itens serão devolvidos ao estoque.")
        elif order["status"] == "Cancelado" and new_status != "Cancelado":
            st.caption("Ao reativar, os itens serão reservados novamente do estoque.")
        if st.button(
            "Atualizar status",
            type="primary",
            icon=":material/sync:",
            disabled=new_status == order["status"],
            key=f"update_order_status_{order_id}",
        ):
            try:
                orders.update_order_status(
                    order_id, new_status, actor=user["name"]
                )
            except DomainError as exc:
                st.error(str(exc))
            else:
                ui.set_flash(f"Status do pedido {order['number']} atualizado.")
                st.rerun()
    else:
        st.caption("Seu perfil permite apenas consultar este pedido.")


@st.dialog("Excluir pedido", icon=":material/delete:")
def delete_order_dialog(order_id: int, number: str, status: str) -> None:
    if not acl.can_current("orders.delete_order"):
        st.error("Seu perfil não permite excluir pedidos.")
        return
    st.write(f"Tem certeza de que deseja excluir o pedido **{number}**?")
    message = (
        "O pedido será removido permanentemente. Os itens voltarão ao estoque."
        if status != "Cancelado"
        else "O pedido será removido permanentemente. Os itens já haviam retornado ao estoque."
    )
    st.warning(message, icon=":material/warning:")
    if st.button(
        "Excluir pedido",
        type="primary",
        icon=":material/delete:",
        width="stretch",
        key=f"confirm_delete_order_{order_id}",
    ):
        try:
            orders.delete_order(order_id, actor=user["name"])
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash(f"Pedido {number} excluído com sucesso.")
            st.rerun()


header_left, header_right = st.columns([1.8, 1], vertical_alignment="center")
with header_left:
    ui.page_header(
        "Pedidos",
        "Acompanhe vendas, atualize status e consulte o histórico de cada pedido.",
        icon=":material/receipt_long:",
    )
with header_right:
    with st.container(horizontal=True, horizontal_alignment="right"):
        if acl.has_perm(user, "orders.add_order"):
            if st.button(
                "Novo pedido",
                type="primary",
                icon=":material/add:",
                key="orders_new_order_button",
            ):
                open_new_order_dialog()

all_orders = orders.list_orders(limit=1000)
if all_orders.empty:
    order_count = open_count = revenue_count = 0
    revenue = 0.0
else:
    order_count = len(all_orders)
    open_count = int(all_orders["status"].isin(OPEN_STATUSES).sum())
    confirmed = all_orders[all_orders["status"].isin(REVENUE_STATUSES)]
    revenue_count = len(confirmed)
    revenue = float(confirmed["total"].sum())

summary_cols = st.columns(4)
summary_cols[0].metric(
    "Pedidos registrados",
    ui.number_br(order_count),
    border=True,
    icon=":material/receipt_long:",
    help="Todos os pedidos, incluindo cancelados.",
)
summary_cols[1].metric(
    "Em andamento",
    ui.number_br(open_count),
    border=True,
    icon=":material/pending_actions:",
    help="Pedidos pendentes, pagos ou enviados.",
)
summary_cols[2].metric(
    "Receita confirmada",
    ui.money(revenue),
    border=True,
    icon=":material/payments:",
    help="Total de pedidos pagos, enviados e entregues.",
)
summary_cols[3].metric(
    "Ticket médio",
    ui.money(revenue / revenue_count if revenue_count else 0),
    border=True,
    icon=":material/trending_up:",
    help="Receita confirmada dividida pelos pedidos confirmados.",
)

st.space("small")
search_col, status_col = st.columns([1.25, 2.3], vertical_alignment="bottom")
with search_col:
    search = st.text_input(
        "Buscar pedido",
        placeholder="Número, cliente ou e-mail",
        type="search",
        key="orders_search",
    )
with status_col:
    status_filter = st.pills(
        "Status",
        options=["Todos", *ORDER_STATUSES],
        default="Todos",
        key="orders_status_filter",
        wrap=True,
    )
status_filter = status_filter or "Todos"

filtered = orders.list_orders(search=search, status=status_filter, limit=500)
if filtered.empty:
    ui.empty_state(
        "Nenhum pedido encontrado",
        "Ajuste os filtros de busca ou registre um novo pedido.",
    )
else:
    display = pd.DataFrame(
        {
            "pedido": filtered["number"],
            "cliente": filtered["customer_name"],
            "data": pd.to_datetime(filtered["created_at"]).dt.strftime("%d/%m/%Y · %H:%M"),
            "unidades": filtered["item_units"],
            "pagamento": filtered["payment_method"],
            "total": filtered["total"],
            "status": [[status] for status in filtered["status"]],
            "id": filtered["id"],
        }
    )

    selection_signature = (
        (search or "").strip().lower(),
        status_filter,
        tuple(int(value) for value in filtered["id"]),
    )
    st.caption(f"{len(filtered)} pedido{'s' if len(filtered) != 1 else ''} encontrado{'s' if len(filtered) != 1 else ''}.")
    event = st.dataframe(
        display,
        hide_index=True,
        height=438,
        on_select="rerun",
        selection_mode="single-row",
        key=ui.table_key("orders_table", selection_signature),
        alt="Lista de pedidos com cliente, data, pagamento, total e status",
        column_config={
            "pedido": st.column_config.TextColumn("Pedido", width=128, pinned=True),
            "cliente": st.column_config.TextColumn("Cliente", width=170),
            "data": st.column_config.TextColumn("Data", width=150),
            "unidades": st.column_config.NumberColumn("Unid.", format="%d", width=64),
            "pagamento": st.column_config.TextColumn("Pagamento", width=120),
            "total": st.column_config.NumberColumn("Total", format="R$ %.2f", width=104),
            "status": st.column_config.MultiselectColumn(
                "Status",
                options=list(ui.STATUS_COLORS.keys()),
                color=list(ui.STATUS_TAG_COLORS.values()),
                width="medium",
            ),
            "id": None,
        },
    )

    selected_index = ui.selected_row_index(
        event,
        len(filtered),
        signature=selection_signature,
        state_key="orders_selected_row",
    )
    if selected_index is not None:
        selected = filtered.iloc[selected_index]
        order_id = int(selected["id"])
        st.space("small")
        with st.container(border=True):
            info_col, actions_col = st.columns([1.2, 3], vertical_alignment="center")
            with info_col:
                st.markdown(f"**{selected['number']}**")
                st.caption(
                    f"{selected['customer_name']} · {ui.datetime_br(selected['created_at'])}"
                )
            with actions_col:
                can_delete = acl.has_perm(user, "orders.delete_order")
                with st.container(horizontal=True, horizontal_alignment="right"):
                    if st.button(
                        "Ver detalhes",
                        icon=":material/visibility:",
                        key=f"view_order_{order_id}",
                    ):
                        order_detail_dialog(order_id)
                    if can_delete:
                        if st.button(
                            "Excluir",
                            icon=":material/delete:",
                            key=f"delete_order_{order_id}",
                        ):
                            delete_order_dialog(
                                order_id, selected["number"], selected["status"]
                            )
    else:
        if acl.has_perm(user, "orders.delete_order"):
            st.caption(
                "Selecione uma linha da tabela para ver os detalhes ou excluir um pedido."
            )
        else:
            st.caption("Selecione uma linha da tabela para ver os detalhes do pedido.")
