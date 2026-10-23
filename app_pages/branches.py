"""Consulta de estoque das filiais (disponível para matriz)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import acl, catalog, companies, ui

user = st.session_state.get("auth_user")
if not user:
    st.error("Sessão expirada. Entre novamente.")
    st.stop()

company = st.session_state.get("auth_company")
if not company or company.get("type") != "matriz":
    st.error("Esta tela é disponível apenas para a matriz.")
    st.stop()

if not acl.has_perm(user, "logistics.view_shipment"):
    st.error("Você não tem permissão para consultar o estoque das filiais.")
    st.stop()

ui.page_header(
    "Filiais",
    "Consulte o estoque inicial e atual das filiais vinculadas à matriz.",
    icon=":material/storefront:",
)

branches = companies.list_branches_with_stock(int(company["id"]))
if not branches:
    st.info("Nenhuma filial cadastrada para esta matriz.", icon=":material/info:")
    st.stop()

# Filtro de habilitação: filial só aparece se allow_branch_stock_view = 1
# OU se o usuário logado for superusuário/admin da filial.
visible = []
for b in branches:
    if b.get("allow_branch_stock_view"):
        visible.append(b)
    elif user.get("is_superuser"):
        visible.append(b)

if not visible:
    st.warning(
        "Nenhuma filial habilitou a consulta de estoque. Peça ao administrador "
        "da filial que habilite o recurso.",
        icon=":material/lock:",
    )
    st.stop()

branch_labels = {f"{b['name']} ({b['city'] or '-'})": b for b in visible}
selected_label = st.selectbox("Filial", options=list(branch_labels), key="branch_select")
selected = branch_labels[selected_label]

st.space("small")
st.subheader(f"Estoque — {selected['name']}")
st.caption(
    f"Total em estoque: {int(selected.get('total_stock') or 0)} unidades em "
    f"{int(selected.get('product_count') or 0)} produtos."
)

# Lista de produtos da filial
products_df = catalog.list_products(company_id=int(selected["id"]))
if products_df.empty:
    st.info("Nenhum produto cadastrado para esta filial.", icon=":material/info:")
else:
    display = products_df.copy()
    display["status"] = display["active"].map({1: "Ativo", 0: "Inativo"})
    st.dataframe(
        display[["sku", "name", "category", "stock", "min_stock", "status"]],
        hide_index=True,
        width="stretch",
        column_config={
            "sku": st.column_config.TextColumn("SKU", width="small"),
            "name": st.column_config.TextColumn("Produto", width="large"),
            "category": st.column_config.TextColumn("Categoria", width="small"),
            "stock": st.column_config.NumberColumn("Estoque", width="small"),
            "min_stock": st.column_config.NumberColumn("Mínimo", width="small"),
            "status": st.column_config.TextColumn("Status", width="small"),
        },
    )

st.space("small")
with st.expander("Habilitar consulta de estoque (admin da filial)"):
    st.caption(
        "O administrador da filial pode habilitar ou desabilitar a consulta "
        "do estoque pela matriz."
    )
    current_enabled = bool(selected.get("allow_branch_stock_view"))
    new_state = st.toggle(
        "Permitir que a matriz consulte o estoque desta filial",
        value=current_enabled,
        key="branch_stock_toggle",
    )
    if new_state != current_enabled:
        try:
            companies.set_branch_stock_view(
                int(selected["id"]), new_state, user["name"]
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Configuração atualizada.")
            st.rerun()
