"""Cadastro e gestão de produtos."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import acl, catalog, companies, ui
from lib.errors import DomainError

user = acl.require("products.view_product")


def _product_form_body(product_id: int | None) -> None:
    required = "products.change_product" if product_id else "products.add_product"
    if not acl.can_current(required):
        st.error("Seu perfil não permite esta ação.")
        return

    product = catalog.get_product(product_id) if product_id else None
    categories = catalog.list_categories()

    with st.form(f"product_form_{product_id or 'new'}"):
        name = st.text_input(
            "Nome do produto",
            value=product["name"] if product else "",
            placeholder="Ex.: Fone Bluetooth Pulse",
        )
        sku_col, category_col = st.columns(2)
        with sku_col:
            sku = st.text_input(
                "SKU",
                value=product["sku"] if product else catalog.next_sku_suggestion(),
                help="Código único de identificação do produto.",
            )
        with category_col:
            default_category = product["category"] if product else None
            category = st.selectbox(
                "Categoria",
                options=categories,
                index=categories.index(default_category) if default_category in categories else None,
                placeholder="Selecione ou digite uma categoria",
                accept_new_options=True,
            )

        price_col, cost_col = st.columns(2)
        with price_col:
            price = st.number_input(
                "Preço de venda (R$)",
                min_value=0.0,
                value=float(product["price"]) if product else 0.0,
                step=10.0,
                format="%.2f",
            )
        with cost_col:
            cost = st.number_input(
                "Custo unitário (R$)",
                min_value=0.0,
                value=float(product["cost"]) if product else 0.0,
                step=10.0,
                format="%.2f",
            )

        stock_col, min_stock_col = st.columns(2)
        with stock_col:
            stock = st.number_input(
                "Estoque atual",
                min_value=0,
                value=int(product["stock"]) if product else 0,
                step=1,
            )
        with min_stock_col:
            min_stock = st.number_input(
                "Estoque mínimo",
                min_value=0,
                value=int(product["min_stock"]) if product else 5,
                step=1,
                help="O produto aparecerá nos alertas quando o estoque ficar abaixo deste valor.",
            )

        description = st.text_area(
            "Descrição (opcional)",
            value=product["description"] if product and product["description"] else "",
            placeholder="Detalhes, materiais, cores ou diferenciais do produto.",
            height=100,
        )
        active = st.toggle(
            "Produto ativo",
            value=bool(product["active"]) if product else True,
            help="Produtos inativos não podem ser adicionados a novos pedidos.",
        )
        submitted = st.form_submit_button(
            "Salvar produto",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            catalog.save_product(
                product_id=product_id,
                sku=sku,
                name=name,
                category=category or "",
                description=description,
                price=float(price),
                cost=float(cost),
                stock=int(stock),
                min_stock=int(min_stock),
                active=active,
                actor=user["name"],
                company_id=companies.current_company_id(),
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            message = "Produto atualizado com sucesso." if product_id else "Produto cadastrado com sucesso."
            ui.set_flash(message)
            st.rerun()


@st.dialog("Novo produto", width="large", icon=":material/add_box:")
def new_product_dialog() -> None:
    _product_form_body(None)


@st.dialog("Editar produto", width="large", icon=":material/edit:")
def edit_product_dialog(product_id: int) -> None:
    _product_form_body(product_id)


@st.dialog("Excluir produto", icon=":material/delete:")
def delete_product_dialog(product_id: int, product_name: str) -> None:
    if not acl.can_current("products.delete_product"):
        st.error("Seu perfil não permite excluir produtos.")
        return
    st.write(f"Tem certeza de que deseja excluir **{product_name}**?")
    st.warning(
        "A exclusão é permanente. Produtos com pedidos vinculados não podem ser excluídos; nesse caso, desative o item.",
        icon=":material/warning:",
    )
    if st.button(
        "Excluir produto",
        type="primary",
        icon=":material/delete:",
        width="stretch",
        key=f"confirm_delete_product_{product_id}",
    ):
        try:
            catalog.delete_product(product_id)
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Produto excluído com sucesso.")
            st.rerun()


header_left, header_right = st.columns([1.8, 1], vertical_alignment="center")
with header_left:
    ui.page_header(
        "Produtos",
        "Gerencie o catálogo, preços e a disponibilidade do estoque.",
        icon=":material/inventory_2:",
    )
with header_right:
    with st.container(horizontal=True, horizontal_alignment="right"):
        if acl.has_perm(user, "products.add_product"):
            if st.button(
                "Novo produto",
                type="primary",
                icon=":material/add:",
                key="new_product_button",
            ):
                new_product_dialog()

all_products = catalog.list_products(company_id=companies.current_company_id())
active_products = int(all_products["active"].sum()) if not all_products.empty else 0
low_stock_count = int(
    ((all_products["stock"] <= all_products["min_stock"]) & (all_products["active"] == 1)).sum()
)
stock_value = float((all_products["stock"] * all_products["cost"]).sum())

summary_cols = st.columns(3)
summary_cols[0].metric(
    "Produtos ativos",
    ui.number_br(active_products),
    border=True,
    icon=":material/inventory_2:",
    help=f"{len(all_products)} produtos no catálogo.",
)
summary_cols[1].metric(
    "Estoque baixo",
    ui.number_br(low_stock_count),
    border=True,
    icon=":material/warning:",
    help="Produtos ativos no ou abaixo do estoque mínimo.",
)
summary_cols[2].metric(
    "Valor em estoque",
    ui.money(stock_value),
    border=True,
    icon=":material/savings:",
    help="Calculado pelo custo unitário dos produtos em estoque.",
)

st.space("small")
with st.container(vertical_alignment="bottom"):
    search_col, category_col, status_col = st.columns(
        [2.2, 1.15, 1.3], vertical_alignment="bottom"
    )
    with search_col:
        search = st.text_input(
            "Buscar produto",
            placeholder="Nome, SKU ou categoria",
            type="search",
            key="products_search",
        )
    with category_col:
        categories = ["Todas"] + catalog.list_categories()
        category_filter = st.selectbox(
            "Categoria", options=categories, key="products_category_filter"
        )
    with status_col:
        status_filter = st.segmented_control(
            "Situação",
            options=["Todos", "Ativos", "Inativos"],
            default="Todos",
            key="products_status_filter",
        )

filtered = catalog.list_products(
    search=search,
    category=category_filter,
    status=status_filter or "Todos",
    company_id=companies.current_company_id(),
)

if filtered.empty:
    ui.empty_state(
        "Nenhum produto encontrado",
        "Ajuste os filtros de busca ou cadastre um novo produto.",
    )
else:
    table_data = filtered.copy()
    table_data["estoque_situacao"] = table_data.apply(
        lambda row: [
            "Sem estoque"
            if row["stock"] == 0
            else "Estoque baixo"
            if row["stock"] <= row["min_stock"]
            else "Em estoque"
        ],
        axis=1,
    )
    table_data["status_label"] = table_data["active"].map(
        {1: ["Ativo"], 0: ["Inativo"]}
    )
    display = pd.DataFrame(
        {
            "sku": table_data["sku"],
            "produto": table_data["name"],
            "categoria": table_data["category"],
            "preco": table_data["price"],
            "estoque": table_data["stock"],
            "situacao": table_data["estoque_situacao"],
            "status": table_data["status_label"],
            "id": table_data["id"],
        }
    )

    selection_signature = (
        (search or "").strip().lower(),
        category_filter or "Todas",
        status_filter or "Todos",
        tuple(int(value) for value in filtered["id"]),
    )
    event = st.dataframe(
        display,
        hide_index=True,
        height=438,
        on_select="rerun",
        selection_mode="single-row",
        key=ui.table_key("products_table", selection_signature),
        alt="Catálogo de produtos com preço, estoque e situação",
        column_config={
            "sku": st.column_config.TextColumn("SKU", width="small"),
            "produto": st.column_config.TextColumn("Produto", width="large", pinned=True),
            "categoria": st.column_config.TextColumn("Categoria", width="small"),
            "preco": st.column_config.NumberColumn("Preço", format="R$ %.2f", width="small"),
            "estoque": st.column_config.NumberColumn("Estoque", format="%d", width="small"),
            "situacao": st.column_config.MultiselectColumn(
                "Situação",
                options=["Em estoque", "Estoque baixo", "Sem estoque"],
                color=["#047857", "#B45309", "#B91C1C"],
                width="medium",
            ),
            "status": st.column_config.MultiselectColumn(
                "Status",
                options=["Ativo", "Inativo"],
                color=["#0F766E", "#64748B"],
                width="small",
            ),
            "id": None,
        },
    )

    selected_index = ui.selected_row_index(
        event,
        len(filtered),
        signature=selection_signature,
        state_key="products_selected_row",
    )
    if selected_index is not None:
        selected = filtered.iloc[selected_index]
        product_id = int(selected["id"])
        st.space("small")
        with st.container(border=True):
            info_col, actions_col = st.columns([1.2, 3], vertical_alignment="center")
            with info_col:
                st.markdown(f"**{selected['name']}**")
                st.caption(f"{selected['sku']} · {ui.money(selected['price'])}")
            with actions_col:
                can_change = acl.has_perm(user, "products.change_product")
                can_delete = acl.has_perm(user, "products.delete_product")
                if not can_change and not can_delete:
                    st.caption("Seu perfil permite apenas consultar o catálogo.")
                else:
                    with st.container(horizontal=True, horizontal_alignment="right"):
                        if can_change:
                            if st.button(
                                "Editar",
                                icon=":material/edit:",
                                key=f"edit_product_{product_id}",
                            ):
                                edit_product_dialog(product_id)
                            active_label = (
                                "Desativar" if selected["active"] else "Ativar"
                            )
                            if st.button(
                                active_label,
                                icon=":material/pause_circle:"
                                if selected["active"]
                                else ":material/play_circle:",
                                key=f"toggle_product_{product_id}",
                            ):
                                catalog.set_product_active(
                                    product_id, not bool(selected["active"])
                                )
                                ui.set_flash(
                                    f"Produto {'desativado' if selected['active'] else 'ativado'} com sucesso."
                                )
                                st.rerun()
                        if can_delete:
                            if st.button(
                                "Excluir",
                                icon=":material/delete:",
                                key=f"delete_product_{product_id}",
                            ):
                                delete_product_dialog(
                                    product_id, selected["name"]
                                )
    else:
        can_change = acl.has_perm(user, "products.change_product")
        can_delete = acl.has_perm(user, "products.delete_product")
        if can_change or can_delete:
            st.caption(
                "Selecione uma linha da tabela para editar, ativar ou excluir um produto."
            )
        else:
            st.caption("Selecione uma linha da tabela para consultar os detalhes.")
