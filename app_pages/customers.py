"""Cadastro, relacionamento e histórico de clientes."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import acl, catalog, orders, ui
from lib.database import BRAZIL_STATES
from lib.errors import DomainError

user = acl.require("customers.view_customer")
can_view_orders = acl.has_perm(user, "orders.view_order")
can_change = acl.has_perm(user, "customers.change_customer")

# (importado de lib.database)

QUICK_EDIT_COLUMNS = {
    "cliente": "name",
    "email": "email",
    "telefone": "phone",
    "local": "location",
    "status": "status",
}

QUICK_EDIT_LABELS = {
    "name": "nome",
    "email": "e-mail",
    "phone": "telefone",
    "location": "localização",
    "status": "situação",
}


def _customer_form_body(customer_id: int | None) -> None:
    required = "customers.change_customer" if customer_id else "customers.add_customer"
    if not acl.can_current(required):
        st.error("Seu perfil não permite esta ação.")
        return

    customer = catalog.get_customer(customer_id) if customer_id else None

    with st.form(f"customer_form_{customer_id or 'new'}"):
        name = st.text_input(
            "Nome completo",
            value=customer["name"] if customer else "",
            placeholder="Ex.: Ana Souza",
        )
        email_col, phone_col = st.columns(2)
        with email_col:
            email = st.text_input(
                "E-mail",
                value=customer["email"] if customer and customer["email"] else "",
                placeholder="cliente@email.com",
                autocomplete="email",
            )
        with phone_col:
            phone = st.text_input(
                "Telefone",
                value=customer["phone"] if customer and customer["phone"] else "",
                placeholder="(11) 99999-0000",
                autocomplete="tel",
            )

        city_col, state_col = st.columns([2, 1])
        with city_col:
            city = st.text_input(
                "Cidade",
                value=customer["city"] if customer and customer["city"] else "",
                placeholder="São Paulo",
            )
        with state_col:
            state_options = ("—", *BRAZIL_STATES)
            current_state = customer["state"] if customer and customer["state"] else "—"
            state = st.selectbox(
                "UF",
                options=state_options,
                index=state_options.index(current_state)
                if current_state in state_options
                else 0,
            )

        status = st.selectbox(
            "Situação",
            options=["Ativo", "Inativo"],
            index=1 if customer and customer["status"] == "Inativo" else 0,
            help="Clientes inativos não aparecem na criação de novos pedidos.",
        )
        notes = st.text_area(
            "Observações (opcional)",
            value=customer["notes"] if customer and customer["notes"] else "",
            placeholder="Preferências de contato, histórico de atendimento...",
            height=100,
        )
        submitted = st.form_submit_button(
            "Salvar cliente",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            catalog.save_customer(
                customer_id=customer_id,
                name=name,
                email=email,
                phone=phone,
                city=city,
                state="" if state == "—" else state,
                status=status,
                notes=notes,
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            message = (
                "Cliente atualizado com sucesso."
                if customer_id
                else "Cliente cadastrado com sucesso."
            )
            ui.set_flash(message)
            st.rerun()


@st.dialog("Novo cliente", width="large", icon=":material/person_add:")
def new_customer_dialog() -> None:
    _customer_form_body(None)


@st.dialog("Editar cliente", width="large", icon=":material/edit:")
def edit_customer_dialog(customer_id: int) -> None:
    _customer_form_body(customer_id)


def _reset_customer_quick_edit() -> None:
    st.session_state["customers_table_nonce"] = (
        int(st.session_state.get("customers_table_nonce", 0)) + 1
    )
    st.session_state.pop("customers_quick_edit_token", None)


@st.dialog(
    "Edição rápida",
    width="small",
    icon=":material/bolt:",
    on_dismiss=_reset_customer_quick_edit,
)
def quick_edit_customer_dialog(customer_id: int, column: str) -> None:
    if not acl.can_current("customers.change_customer"):
        st.error("Seu perfil não permite editar clientes.")
        return

    customer = catalog.get_customer(customer_id)
    if customer is None:
        st.error("Cliente não encontrado.")
        return

    field = QUICK_EDIT_COLUMNS.get(column)
    if field is None:
        st.info("Este campo é calculado e não pode ser editado.")
        return

    st.caption(
        f"Atualize o campo **{QUICK_EDIT_LABELS[field]}** de {customer['name']}."
    )

    with st.form(f"quick_customer_{customer_id}_{field}"):
        if field == "location":
            city_col, state_col = st.columns([2, 1])
            with city_col:
                city = st.text_input(
                    "Cidade",
                    value=customer["city"] or "",
                    placeholder="São Paulo",
                )
            with state_col:
                state_options = ("—", *BRAZIL_STATES)
                current_state = customer["state"] or "—"
                state = st.selectbox(
                    "UF",
                    options=state_options,
                    index=(
                        state_options.index(current_state)
                        if current_state in state_options
                        else 0
                    ),
                )
        elif field == "status":
            status = st.selectbox(
                "Situação",
                options=["Ativo", "Inativo"],
                index=1 if customer["status"] == "Inativo" else 0,
            )
        elif field == "email":
            email = st.text_input(
                "E-mail",
                value=customer["email"] or "",
                placeholder="cliente@email.com",
                autocomplete="email",
            )
        elif field == "phone":
            phone = st.text_input(
                "Telefone",
                value=customer["phone"] or "",
                placeholder="(11) 99999-0000",
                autocomplete="tel",
            )
        else:
            name = st.text_input(
                "Nome completo",
                value=customer["name"],
                placeholder="Ex.: Ana Souza",
            )

        submitted = st.form_submit_button(
            "Salvar alteração",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if st.button(
        "Cancelar",
        icon=":material/close:",
        width="stretch",
        key=f"cancel_quick_{customer_id}_{field}",
    ):
        _reset_customer_quick_edit()
        st.rerun()

    if not submitted:
        return

    data = {
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["phone"],
        "city": customer["city"],
        "state": customer["state"],
        "status": customer["status"],
        "notes": customer["notes"],
    }
    if field == "location":
        data["city"] = city
        data["state"] = "" if state == "—" else state
    elif field == "status":
        data["status"] = status
    elif field == "email":
        data["email"] = email
    elif field == "phone":
        data["phone"] = phone
    else:
        data["name"] = name

    try:
        catalog.save_customer(customer_id=customer_id, **data)
    except DomainError as exc:
        st.error(str(exc))
    else:
        _reset_customer_quick_edit()
        ui.set_flash("Cliente atualizado com sucesso.")
        st.rerun()


@st.dialog("Ficha do cliente", width="large", icon=":material/account_box:")
def customer_detail_dialog(customer_id: int) -> None:
    if not acl.can_current("customers.view_customer"):
        st.error("Seu perfil não permite consultar clientes.")
        return
    customer = catalog.get_customer(customer_id)
    if customer is None:
        st.error("Cliente não encontrado.")
        return

    stats = catalog.get_customer_stats(customer_id) if can_view_orders else None

    title_col, badge_col = st.columns([2, 1], vertical_alignment="center")
    with title_col:
        st.subheader(customer["name"])
        st.caption(f"Cliente desde {ui.date_br(customer['created_at'])}")
    with badge_col:
        with st.container(horizontal_alignment="right"):
            ui.customer_status_badge(customer["status"])

    with st.container(border=True):
        contact_col, location_col = st.columns(2)
        with contact_col:
            st.caption("Contato")
            st.markdown(f"**{customer['email'] or 'E-mail não informado'}**")
            st.caption(customer["phone"] or "Telefone não informado")
        with location_col:
            st.caption("Localização")
            city = customer["city"] or "Cidade não informada"
            state = customer["state"] or "—"
            st.markdown(f"**{city}/{state}**")
            st.caption("Atendimento: " + customer["status"].lower())

    if can_view_orders and stats is not None:
        metric_cols = st.columns(4)
        metric_cols[0].metric(
            "Pedidos",
            ui.number_br(stats["orders_count"]),
            border=True,
            icon=":material/receipt_long:",
            help="Todos os pedidos do cliente, incluindo pendentes e cancelados.",
        )
        metric_cols[1].metric(
            "Receita confirmada",
            ui.money_compact(stats["total_spent"]),
            border=True,
            icon=":material/payments:",
            help=ui.money(stats["total_spent"]),
        )
        metric_cols[2].metric(
            "Ticket médio",
            ui.money_compact(stats["avg_ticket"]),
            border=True,
            icon=":material/trending_up:",
            help="Receita confirmada dividida pelos pedidos confirmados.",
        )
        metric_cols[3].metric(
            "Último pedido",
            ui.date_br(stats["last_order"]),
            border=True,
            icon=":material/history:",
        )

    if customer["notes"]:
        st.space("small")
        with st.container(border=True):
            st.caption("Observações")
            st.write(customer["notes"])

    if can_view_orders:
        st.space("small")
        st.markdown("**Pedidos recentes**")
        recent = orders.list_orders(customer_id=customer_id, limit=6)
        if recent.empty:
            st.caption("Este cliente ainda não possui pedidos registrados.")
        else:
            display = pd.DataFrame(
                {
                    "Pedido": recent["number"],
                    "Data": pd.to_datetime(recent["created_at"]).dt.strftime("%d/%m/%Y"),
                    "Itens": recent["item_units"],
                    "Total": [ui.money(value) for value in recent["total"]],
                    "Status": [[status] for status in recent["status"]],
                }
            )
            st.dataframe(
                display,
                hide_index=True,
                height=min(250, 36 + len(display) * 35),
                alt="Pedidos recentes do cliente com data, itens, total e status",
                column_config={
                    "Data": st.column_config.TextColumn("Data", width="small"),
                    "Itens": st.column_config.NumberColumn(
                        "Itens", format="%d", width="small"
                    ),
                    "Total": st.column_config.TextColumn("Total", width="small"),
                    "Status": st.column_config.MultiselectColumn(
                        "Status",
                        options=list(ui.STATUS_COLORS.keys()),
                        color=list(ui.STATUS_TAG_COLORS.values()),
                        width="medium",
                    ),
                },
            )
    else:
        st.space("small")
        st.caption("Seu perfil não permite consultar os pedidos deste cliente.")


@st.dialog("Excluir cliente", icon=":material/delete:")
def delete_customer_dialog(customer_id: int, customer_name: str) -> None:
    if not acl.can_current("customers.delete_customer"):
        st.error("Seu perfil não permite excluir clientes.")
        return
    st.write(f"Tem certeza de que deseja excluir **{customer_name}**?")
    st.warning(
        "A exclusão é permanente. Clientes com pedidos vinculados não podem ser "
        "excluídos; nesse caso, desative o cadastro.",
        icon=":material/warning:",
    )
    if st.button(
        "Excluir cliente",
        type="primary",
        icon=":material/delete:",
        width="stretch",
        key=f"confirm_delete_customer_{customer_id}",
    ):
        try:
            catalog.delete_customer(customer_id)
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Cliente excluído com sucesso.")
            st.rerun()


header_left, header_right = st.columns([1.8, 1], vertical_alignment="center")
with header_left:
    ui.page_header(
        "Clientes",
        "Organize contatos, acompanhe o histórico e fortaleça o relacionamento.",
        icon=":material/group:",
    )
with header_right:
    with st.container(horizontal=True, horizontal_alignment="right"):
        if acl.has_perm(user, "customers.add_customer"):
            if st.button(
                "Novo cliente",
                type="primary",
                icon=":material/person_add:",
                key="new_customer_button",
            ):
                new_customer_dialog()

all_customers = catalog.list_customers()
if all_customers.empty:
    total_customers = active_customers = new_customers = 0
    confirmed_revenue = 0.0
else:
    total_customers = len(all_customers)
    active_customers = int((all_customers["status"] == "Ativo").sum())
    created = pd.to_datetime(all_customers["created_at"], errors="coerce")
    cutoff = pd.Timestamp(date.today() - timedelta(days=29))
    new_customers = int((created >= cutoff).sum())
    confirmed_revenue = float(all_customers["total_spent"].sum())

metrics = [
    (
        "Clientes cadastrados",
        ui.number_br(total_customers),
        ":material/group:",
        "Todos os clientes da base, incluindo inativos.",
    ),
    (
        "Clientes ativos",
        ui.number_br(active_customers),
        ":material/how_to_reg:",
        "Clientes disponíveis para receber novos pedidos.",
    ),
    (
        "Novos em 30 dias",
        ui.number_br(new_customers),
        ":material/person_add:",
        "Cadastros criados nos últimos 30 dias.",
    ),
]
if can_view_orders:
    metrics.append(
        (
            "Receita confirmada",
            ui.money_compact(confirmed_revenue),
            ":material/payments:",
            f"Total histórico: {ui.money(confirmed_revenue)}.",
        )
    )

summary_cols = st.columns(len(metrics))
for column, (label, value, icon, help_text) in zip(summary_cols, metrics):
    column.metric(
        label,
        value,
        border=True,
        icon=icon,
        help=help_text,
    )

st.space("small")
search_col, status_col = st.columns([1.3, 2], vertical_alignment="bottom")
with search_col:
    search = st.text_input(
        "Buscar cliente",
        placeholder="Nome, e-mail, telefone ou cidade",
        type="search",
        key="customers_search",
    )
with status_col:
    status_filter = st.segmented_control(
        "Situação",
        options=["Todos", "Ativo", "Inativo"],
        default="Todos",
        key="customers_status_filter",
        width="stretch",
    )
status_filter = status_filter or "Todos"

filtered = catalog.list_customers(search=search, status=status_filter)
if filtered.empty:
    ui.empty_state(
        "Nenhum cliente encontrado",
        "Ajuste os filtros de busca ou cadastre um novo cliente.",
    )
else:
    locations = []
    for row in filtered.itertuples():
        if row.city and row.state:
            locations.append(f"{row.city}/{row.state}")
        elif row.city:
            locations.append(row.city)
        elif row.state:
            locations.append(row.state)
        else:
            locations.append("—")

    table_data = {
        "cliente": filtered["name"],
        "email": filtered["email"].fillna("—"),
        "telefone": filtered["phone"].fillna("—"),
        "local": locations,
    }
    if can_view_orders:
        table_data["pedidos"] = filtered["orders_count"]
        table_data["total"] = filtered["total_spent"]
    table_data["status"] = [[status] for status in filtered["status"]]
    table_data["id"] = filtered["id"]
    display = pd.DataFrame(table_data)

    column_config = {
        "cliente": st.column_config.TextColumn(
            "Cliente", width=170, pinned=True
        ),
        "email": st.column_config.TextColumn("E-mail", width=220),
        "telefone": st.column_config.TextColumn("Telefone", width=130),
        "local": st.column_config.TextColumn("Local", width=150),
    }
    if can_view_orders:
        column_config["pedidos"] = st.column_config.NumberColumn(
            "Pedidos", format="%d", width=80
        )
        column_config["total"] = st.column_config.NumberColumn(
            "Receita", format="R$ %.2f", width=104
        )
    column_config["status"] = st.column_config.MultiselectColumn(
        "Status",
        options=["Ativo", "Inativo"],
        color=["#047857", "#64748B"],
        width="small",
    )
    column_config["id"] = None

    table_nonce = int(st.session_state.get("customers_table_nonce", 0))
    selection_signature = (
        (search or "").strip().lower(),
        status_filter,
        tuple(int(value) for value in filtered["id"]),
        table_nonce,
    )
    st.caption(
        f"{len(filtered)} cliente{'s' if len(filtered) != 1 else ''} encontrado"
        f"{'s' if len(filtered) != 1 else ''}."
    )
    if can_change:
        st.caption(
            "Clique em uma célula editável para edição rápida. "
            "Marque a linha para ver todas as ações."
        )
    event = st.dataframe(
        display,
        hide_index=True,
        height=438,
        on_select="rerun",
        selection_mode=(
            ["single-row", "single-cell"] if can_change else "single-row"
        ),
        key=ui.table_key("customers_table", selection_signature),
        alt=(
            "Lista de clientes com contato, localização, pedidos e receita"
            if can_view_orders
            else "Lista de clientes com contato, localização e situação"
        ),
        column_config=column_config,
    )

    selected_index = ui.selected_row_index(
        event,
        len(filtered),
        signature=selection_signature,
        state_key="customers_selected_row",
    )
    selected_cell = ui.selected_cell(
        event,
        len(filtered),
        signature=selection_signature,
        state_key="customers_selected_cell",
    )
    if selected_index is None and selected_cell is not None:
        selected_index = selected_cell[0]

    if can_change and selected_cell is not None:
        cell_row, cell_column = selected_cell
        if cell_column in QUICK_EDIT_COLUMNS:
            quick_token = (selection_signature, cell_row, cell_column)
            if st.session_state.get("customers_quick_edit_token") != quick_token:
                st.session_state["customers_quick_edit_token"] = quick_token
                quick_edit_customer_dialog(
                    int(filtered.iloc[cell_row]["id"]), cell_column
                )

    if selected_index is not None:
        selected = filtered.iloc[selected_index]
        customer_id = int(selected["id"])
        has_orders = can_view_orders and int(selected["orders_count"]) > 0

        st.space("small")
        with st.container(border=True):
            info_col, actions_col = st.columns([1.2, 3], vertical_alignment="center")
            with info_col:
                st.markdown(f"**{selected['name']}**")
                subtitle = selected["email"] or "Sem e-mail"
                if can_view_orders:
                    subtitle += (
                        f" · {selected['orders_count']} pedido"
                        f"{'s' if selected['orders_count'] != 1 else ''}"
                    )
                st.caption(subtitle)
            with actions_col:
                can_delete = acl.has_perm(user, "customers.delete_customer")
                with st.container(horizontal=True, horizontal_alignment="right"):
                    if st.button(
                        "Ver ficha",
                        icon=":material/account_box:",
                        key=f"view_customer_{customer_id}",
                    ):
                        customer_detail_dialog(customer_id)
                    if can_change:
                        if st.button(
                            "Editar",
                            icon=":material/edit:",
                            key=f"edit_customer_{customer_id}",
                        ):
                            edit_customer_dialog(customer_id)
                        is_active = selected["status"] == "Ativo"
                        if st.button(
                            "Desativar" if is_active else "Ativar",
                            icon=":material/pause_circle:"
                            if is_active
                            else ":material/play_circle:",
                            key=f"toggle_customer_{customer_id}",
                        ):
                            catalog.set_customer_status(
                                customer_id, "Inativo" if is_active else "Ativo"
                            )
                            ui.set_flash(
                                f"Cliente {'desativado' if is_active else 'ativado'} com sucesso."
                            )
                            st.rerun()
                    if can_delete:
                        if st.button(
                            "Excluir",
                            icon=":material/delete:",
                            key=f"delete_customer_{customer_id}",
                            disabled=has_orders,
                            help=(
                                "Clientes com pedidos vinculados não podem ser excluídos."
                                if has_orders
                                else None
                            ),
                        ):
                            delete_customer_dialog(customer_id, selected["name"])

            if has_orders:
                st.caption(
                    "Este cliente possui pedidos vinculados e deve ser desativado "
                    "em vez de excluído."
                )
    else:
        can_change = acl.has_perm(user, "customers.change_customer")
        if can_change:
            st.caption(
                "Selecione uma linha da tabela para ver a ficha, editar ou alterar a situação."
            )
        else:
            st.caption(
                "Selecione uma linha da tabela para consultar a ficha do cliente."
            )
