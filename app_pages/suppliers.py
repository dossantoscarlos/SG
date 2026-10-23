"""Cadastro e gestão de fornecedores."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import acl, inventory, ui
from lib.database import BRAZIL_STATES
from lib.errors import DomainError

user = st.session_state.get("auth_user")
if not user:
    st.error("Sessão expirada. Entre novamente.")
    st.stop()

if not acl.has_perm(user, "logistics.view_shipment"):
    st.error("Você não tem permissão para gerenciar fornecedores.")
    st.stop()

can_manage = acl.has_perm(user, "logistics.manage_carrier") or acl.has_perm(
    user, "logistics.adjust_stock"
)

QUICK_EDIT_COLUMNS = {
    "name": "name",
    "document": "document",
    "situacao": "active",
}

QUICK_EDIT_LABELS = {
    "name": "nome",
    "document": "documento",
    "active": "situação",
}


def _reset_supplier_quick_edit() -> None:
    st.session_state["suppliers_table_nonce"] = (
        int(st.session_state.get("suppliers_table_nonce", 0)) + 1
    )
    st.session_state.pop("suppliers_quick_edit_token", None)


@st.dialog("Edição rápida", width="small", icon=":material/bolt:", on_dismiss=_reset_supplier_quick_edit)
def quick_edit_supplier_dialog(supplier_id: int, field: str) -> None:
    if not can_manage:
        st.error("Seu perfil não permite editar fornecedores.")
        return
    from lib import inventory

    entity = inventory.get_stock_entity(supplier_id)
    if entity is None:
        st.error("Fornecedor não encontrado.")
        return

    st.caption(f"Atualize o campo **{QUICK_EDIT_LABELS[field]}** de {entity['name']}.")

    with st.form(f"quick_supplier_{supplier_id}_{field}"):
        if field == "name":
            value = st.text_input("Nome", value=entity["name"] or "")
        elif field == "document":
            value = st.text_input("Documento", value=entity["document"] or "")
        elif field == "active":
            value = st.selectbox(
                "Situação",
                options=["Ativa", "Inativa"],
                index=0 if entity["active"] else 1,
            )
            value = value == "Ativa"
        else:
            st.info("Este campo não pode ser editado.")
            return

        submitted = st.form_submit_button(
            "Salvar alteração",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if st.button("Cancelar", icon=":material/close:", width="stretch", key=f"cancel_quick_supplier_{supplier_id}_{field}"):
        _reset_supplier_quick_edit()
        st.rerun()

    if not submitted:
        return

    try:
        inventory.save_stock_entity(
            kind="Fornecedor",
            name=value if field == "name" else entity["name"],
            document=value if field == "document" else entity["document"],
            city=entity["city"],
            state=entity["state"],
            active=value if field == "active" else bool(entity["active"]),
            entity_id=supplier_id,
        )
    except DomainError as exc:
        st.error(str(exc))
    else:
        ui.set_flash("Fornecedor atualizado.")
        _reset_supplier_quick_edit()
        st.rerun()

ui.page_header(
    "Fornecedores",
    "Cadastre e acompanhe fornecedores usados nas entradas de estoque.",
    icon=":material/local_shipping:",
)

STOCK_ENTITY_KINDS = ("Filial", "Fornecedor")


@st.dialog("Fornecedor", width="large", icon=":material/local_shipping:")
def supplier_dialog(entity_id: int | None = None) -> None:
    if not can_manage:
        st.error("Seu perfil não permite gerenciar fornecedores.")
        return

    entity = inventory.get_stock_entity(entity_id) if entity_id else None

    with st.form(f"supplier_form_{entity_id or 'new'}"):
        name = st.text_input(
            "Nome",
            value=entity["name"] if entity else "",
            placeholder="Ex.: Fornecedor ABC",
        )
        document = st.text_input(
            "Documento (opcional)",
            value=entity["document"] if entity and entity["document"] else "",
            placeholder="CNPJ ou CPF",
        )
        city_col, state_col = st.columns([2.2, 1])
        with city_col:
            city = st.text_input(
                "Cidade",
                value=entity["city"] if entity and entity["city"] else "",
                placeholder="São Paulo",
            )
        with state_col:
            state_options = ("—", *BRAZIL_STATES)
            current_state = entity["state"] if entity and entity["state"] else "—"
            state = st.selectbox(
                "UF",
                options=state_options,
                index=state_options.index(current_state)
                if current_state in state_options
                else 0,
            )
            state = "" if state == "—" else state
        active = st.toggle(
            "Fornecedor ativo",
            value=bool(entity["active"]) if entity else True,
            help="Fornecedores inativos não aparecem em novas movimentações.",
        )
        submitted = st.form_submit_button(
            "Salvar fornecedor",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            inventory.save_stock_entity(
                kind="Fornecedor",
                name=name,
                document=document,
                city=city,
                state=state,
                active=active,
                entity_id=entity_id,
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Fornecedor salvo com sucesso.")
            st.rerun()


all_entities = inventory.list_stock_entities()
suppliers = (
    all_entities[all_entities["kind"] == "Fornecedor"]
    if not all_entities.empty
    else all_entities
)

# --- Métricas rápidas -----------------------------------------------------
total = len(suppliers)
active_count = int(suppliers["active"].sum()) if not suppliers.empty else 0
with_moves = (
    int((suppliers["movements_count"] > 0).sum()) if not suppliers.empty else 0
)

metric_cols = st.columns(3)
metric_cols[0].metric(
    "Fornecedores",
    ui.number_br(total),
    border=True,
    icon=":material/local_shipping:",
    help="Total de fornecedores cadastrados.",
)
metric_cols[1].metric(
    "Ativos",
    ui.number_br(active_count),
    border=True,
    icon=":material/check_circle:",
    help="Fornecedores ativos.",
)
metric_cols[2].metric(
    "Com movimentações",
    ui.number_br(with_moves),
    border=True,
    icon=":material/receipt_long:",
    help="Fornecedores com histórico de movimentação de estoque.",
)

st.space("small")

# --- Listagem -------------------------------------------------------------
header_col, action_col = st.columns([2.4, 1], vertical_alignment="center")
with header_col:
    st.subheader("Fornecedores cadastrados")
    st.caption("Fornecedores usados como origem nas entradas de estoque.")
with action_col:
    if can_manage:
        with st.container(horizontal=True, horizontal_alignment="right"):
            if st.button(
                "Novo fornecedor",
                type="primary",
                icon=":material/add:",
                key="new_supplier_button",
            ):
                supplier_dialog()

if suppliers.empty:
    ui.empty_state("Nenhum fornecedor cadastrado", "Cadastre o primeiro fornecedor.")
else:
    display = suppliers.copy()
    display["situacao"] = display["active"].map({1: "Ativa", 0: "Inativa"})
    display["local"] = [
        f"{row.city or '—'} / {row.state or '—'}" for row in suppliers.itertuples()
    ]
    table = display[["name", "document", "local", "movements_count", "situacao", "id"]]
    column_config = {
        "name": st.column_config.TextColumn("Fornecedor", width="large"),
        "document": st.column_config.TextColumn("Documento", width="small"),
        "local": st.column_config.TextColumn("Local", width="small"),
        "movements_count": st.column_config.NumberColumn(
            "Movimentações", format="%d", width="small"
        ),
        "situacao": st.column_config.MultiselectColumn(
            "Situação",
            options=["Ativa", "Inativa"],
            color=["#047857", "#64748B"],
            width="small",
        ),
        "id": None,
    }

    table_nonce = int(st.session_state.get("suppliers_table_nonce", 0))
    selection_signature = (
        tuple(int(value) for value in suppliers["id"]),
        table_nonce,
    )
    if can_manage:
        st.caption("Clique em uma célula editável para edição rápida. Marque a linha para ver todas as ações.")
    event = st.dataframe(
        table,
        hide_index=True,
        height=min(420, 38 + len(table) * 36),
        on_select="rerun",
        selection_mode=(
            ["single-row", "single-cell"] if can_manage else "single-row"
        ),
        key=ui.table_key("suppliers_table", selection_signature),
        alt="Fornecedores cadastrados com documento, local e movimentações",
        column_config=column_config,
    )

    selected_index = ui.selected_row_index(
        event,
        len(suppliers),
        signature=selection_signature,
        state_key="suppliers_selected_row",
    )
    selected_cell = ui.selected_cell(
        event,
        len(suppliers),
        signature=selection_signature,
        state_key="suppliers_selected_cell",
    )
    if selected_index is None and selected_cell is not None:
        selected_index = selected_cell[0]

    if can_manage and selected_cell is not None:
        cell_row, cell_column = selected_cell
        if cell_column in QUICK_EDIT_COLUMNS:
            quick_token = (selection_signature, cell_row, cell_column)
            if st.session_state.get("suppliers_quick_edit_token") != quick_token:
                st.session_state["suppliers_quick_edit_token"] = quick_token
                quick_edit_supplier_dialog(
                    int(suppliers.iloc[cell_row]["id"]), QUICK_EDIT_COLUMNS[cell_column]
                )

    if selected_index is not None:
        selected = suppliers.iloc[selected_index]
        st.space("small")
        with st.container(border=True):
            info_col, actions_col = st.columns([2.2, 1.4], vertical_alignment="center")
            with info_col:
                st.markdown(f"**{selected['name']}**")
                st.caption(
                    f"{selected['city'] or '—'} / {selected['state'] or '—'} · "
                    f"{int(selected['movements_count'])} movimentação(ões)"
                )
            with actions_col:
                with st.container(horizontal=True, horizontal_alignment="right"):
                    if st.button(
                        "Editar",
                        icon=":material/edit:",
                        key=f"edit_supplier_{selected['id']}",
                    ):
                        supplier_dialog(int(selected["id"]))
                    if st.button(
                        "Ativar/Desativar",
                        icon=":material/toggle_on:",
                        key=f"toggle_supplier_{selected['id']}",
                    ):
                        inventory.set_stock_entity_active(
                            int(selected["id"]), not bool(selected["active"])
                        )
                        ui.set_flash("Situação do fornecedor atualizada.")
                        st.rerun()
