"""Gestão de empresas (matriz e filiais)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import acl, companies, ui
from lib.database import BRAZIL_STATES
from lib.errors import DomainError

user = st.session_state.get("auth_user")
if not user:
    st.error("Sessão expirada. Entre novamente.")
    st.stop()

if not acl.has_any(user, "products.view_product", "auth.view_user", "auth.view_group"):
    st.error("Você não tem permissão para gerenciar empresas.")
    st.stop()

can_manage = acl.has_any(user, "auth.view_user", "auth.view_group", "products.change_product")


def _reset_company_quick_edit() -> None:
    st.session_state["companies_table_nonce"] = (
        int(st.session_state.get("companies_table_nonce", 0)) + 1
    )
    st.session_state.pop("companies_quick_edit_token", None)


@st.dialog("Edição rápida", width="small", icon=":material/bolt:", on_dismiss=_reset_company_quick_edit)
def quick_edit_company_dialog(company_id: int, field: str) -> None:
    if not can_manage:
        st.error("Seu perfil não permite editar empresas.")
        return

    company = companies.get_company(company_id)
    if company is None:
        st.error("Empresa não encontrada.")
        return

    st.caption(f"Atualize o campo **{QUICK_EDIT_LABELS[field]}** de {company['name']}.")

    with st.form(f"quick_company_{company_id}_{field}"):
        if field == "name":
            value = st.text_input("Nome", value=company["name"] or "")
        elif field == "city":
            value = st.text_input("Cidade", value=company["city"] or "")
        elif field == "state":
            state_options = ("—", *BRAZIL_STATES)
            current_state = company["state"] or "—"
            value = st.selectbox(
                "UF",
                options=state_options,
                index=state_options.index(current_state) if current_state in state_options else 0,
            )
            value = "" if value == "—" else value
        elif field == "active":
            value = st.selectbox(
                "Situação",
                options=["Ativa", "Inativa"],
                index=0 if company["active"] else 1,
            )
            value = value == "Ativa"
        elif field == "allow_branch_stock_view":
            value = st.selectbox(
                "Consulta de estoque",
                options=["Sim", "Não"],
                index=0 if company["allow_branch_stock_view"] else 1,
            )
            value = value == "Sim"
        else:
            st.info("Este campo não pode ser editado.")
            return

        submitted = st.form_submit_button(
            "Salvar alteração",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if st.button("Cancelar", icon=":material/close:", width="stretch", key=f"cancel_quick_company_{company_id}_{field}"):
        _reset_company_quick_edit()
        st.rerun()

    if not submitted:
        return

    try:
        companies.save_company(
            company_id=company_id,
            name=value if field == "name" else company["name"],
            type=company["type"],
            parent_id=company["parent_id"],
            address=company["address"],
            city=value if field == "city" else company["city"],
            state=value if field == "state" else company["state"],
            zip_code=company["zip_code"],
            document=company["document"],
            phone=company["phone"],
            active=value if field == "active" else bool(company["active"]),
            allow_branch_stock_view=(
                value if field == "allow_branch_stock_view" else bool(company["allow_branch_stock_view"])
            ),
        )
    except DomainError as exc:
        st.error(str(exc))
    else:
        ui.set_flash("Empresa atualizada.")
        _reset_company_quick_edit()
        st.rerun()

QUICK_EDIT_COLUMNS = {
    "name": "name",
    "city": "city",
    "state": "state",
    "situacao": "active",
    "consulta_estoque": "allow_branch_stock_view",
}

QUICK_EDIT_LABELS = {
    "name": "nome",
    "city": "cidade",
    "state": "UF",
    "active": "situação",
    "allow_branch_stock_view": "consulta de estoque",
}

ui.page_header(
    "Empresas",
    "Gerencie matrizes e filiais, endereços e permissões de consulta de estoque.",
    icon=":material/apartment:",
)

all_companies = companies.list_companies(active=None)

# --- Métricas rápidas -----------------------------------------------------
total = len(all_companies)
active_count = sum(1 for c in all_companies if c.get("active"))
matrices = [c for c in all_companies if c.get("type") == "matriz"]
branches = [c for c in all_companies if c.get("type") == "filial"]
enabled_branches = sum(1 for c in branches if c.get("allow_branch_stock_view"))

metric_cols = st.columns(4)
metric_cols[0].metric(
    "Empresas",
    ui.number_br(total),
    border=True,
    icon=":material/apartment:",
    help="Total de matrizes e filiais cadastradas.",
)
metric_cols[1].metric(
    "Matrizes",
    ui.number_br(len(matrices)),
    border=True,
    icon=":material/account_balance:",
    help="Empresas do tipo matriz.",
)
metric_cols[2].metric(
    "Filiais",
    ui.number_br(len(branches)),
    border=True,
    icon=":material/storefront:",
    help="Filiais vinculadas a uma matriz.",
)
metric_cols[3].metric(
    "Filiais com consulta",
    ui.number_br(enabled_branches),
    border=True,
    icon=":material/visibility:",
    help="Filiais que permitem à matriz consultar o estoque.",
)

st.space("small")

# --- Modal de cadastro/edição ---------------------------------------------
@st.dialog("Empresa", width="large", icon=":material/apartment:")
def company_dialog(company_id: int | None = None) -> None:
    if not can_manage:
        st.error("Seu perfil não permite gerenciar empresas.")
        return

    company = companies.get_company(company_id) if company_id else None
    matrices = companies.list_companies(type="matriz", active=True)

    with st.form(f"company_form_{company_id or 'new'}"):
        name = st.text_input(
            "Nome",
            value=company["name"] if company else "",
            placeholder="Ex.: Filial Campinas",
        )
        kind = st.selectbox(
            "Tipo",
            options=["matriz", "filial"],
            index=0 if not company or company["type"] == "matriz" else 1,
            format_func=lambda x: "Matriz" if x == "matriz" else "Filial",
        )
        parent_options = {m["name"]: m["id"] for m in matrices}
        parent_label = None
        if kind == "filial":
            if not parent_options:
                st.warning("Cadastre uma matriz antes de criar a filial.")
            parent_label = st.selectbox(
                "Matriz vinculada",
                options=list(parent_options) if parent_options else [""],
            )
        address = st.text_input(
            "Endereço",
            value=company["address"] if company and company["address"] else "",
        )
        city_col, state_col = st.columns(2)
        with city_col:
            city = st.text_input(
                "Cidade",
                value=company["city"] if company and company["city"] else "",
            )
        with state_col:
            state_options = ("—", *BRAZIL_STATES)
            current_state = company["state"] if company and company["state"] else "—"
            state = st.selectbox(
                "UF",
                options=state_options,
                index=state_options.index(current_state)
                if current_state in state_options
                else 0,
            )
            state = "" if state == "—" else state
        zip_code = st.text_input(
            "CEP",
            value=company["zip_code"] if company and company["zip_code"] else "",
        )
        document = st.text_input(
            "CNPJ/CPF",
            value=company["document"] if company and company["document"] else "",
        )
        phone = st.text_input(
            "Telefone",
            value=company["phone"] if company and company["phone"] else "",
        )
        active = st.toggle(
            "Empresa ativa",
            value=bool(company["active"]) if company else True,
        )
        allow_view = False
        if kind == "filial":
            allow_view = st.toggle(
                "Permitir que a matriz consulte o estoque desta filial",
                value=bool(company["allow_branch_stock_view"]) if company else False,
            )
        submitted = st.form_submit_button(
            "Salvar empresa",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            companies.save_company(
                company_id=company_id,
                name=name,
                type=kind,
                parent_id=parent_options.get(parent_label) if kind == "filial" else None,
                address=address or None,
                city=city or None,
                state=state or None,
                zip_code=zip_code or None,
                document=document or None,
                phone=phone or None,
                active=active,
                allow_branch_stock_view=allow_view,
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Empresa salva com sucesso.")
            st.rerun()


# --- Listagem --------------------------------------------------------------
header_col, action_col = st.columns([2.4, 1], vertical_alignment="center")
with header_col:
    st.subheader("Empresas cadastradas")
    st.caption("Matrizes e filiais vinculadas ao sistema.")
with action_col:
    if can_manage:
        with st.container(horizontal=True, horizontal_alignment="right"):
            if st.button(
                "Nova empresa",
                type="primary",
                icon=":material/add:",
                key="new_company_button",
            ):
                company_dialog()

if all_companies:
    df = pd.DataFrame(all_companies)
    df["tipo"] = df["type"].map({"matriz": "Matriz", "filial": "Filial"})
    df["matriz"] = df["parent_id"].map(
        {c["id"]: c["name"] for c in all_companies}
    ).fillna("—")
    df["situacao"] = df["active"].map({1: "Ativa", 0: "Inativa"})
    df["consulta_estoque"] = df["allow_branch_stock_view"].map({1: "Sim", 0: "Não"})
    display = df[
        ["name", "tipo", "matriz", "city", "state", "situacao", "consulta_estoque", "id"]
    ]
    signature = tuple(int(value) for value in df["id"])
    column_config = {
        "name": st.column_config.TextColumn("Empresa", width="large"),
        "tipo": st.column_config.TextColumn("Tipo", width="small"),
        "matriz": st.column_config.TextColumn("Matriz", width="small"),
        "city": st.column_config.TextColumn("Cidade", width="small"),
        "state": st.column_config.TextColumn("UF", width="small"),
        "situacao": st.column_config.TextColumn("Situação", width="small"),
        "consulta_estoque": st.column_config.TextColumn("Consulta estoque", width="small"),
        "id": None,
    }

    table_nonce = int(st.session_state.get("companies_table_nonce", 0))
    selection_signature = (
        tuple(int(value) for value in df["id"]),
        table_nonce,
    )
    if can_manage:
        st.caption("Clique em uma célula editável para edição rápida. Marque a linha para ver todas as ações.")
    event = st.dataframe(
        display,
        hide_index=True,
        height=min(420, 38 + len(display) * 36),
        on_select="rerun",
        selection_mode=(
            ["single-row", "single-cell"] if can_manage else "single-row"
        ),
        key=ui.table_key("companies_table", selection_signature),
        alt="Empresas cadastradas com tipo, matriz, local e situação",
        column_config=column_config,
    )

    selected_index = ui.selected_row_index(
        event,
        len(all_companies),
        signature=selection_signature,
        state_key="companies_selected_row",
    )
    selected_cell = ui.selected_cell(
        event,
        len(all_companies),
        signature=selection_signature,
        state_key="companies_selected_cell",
    )
    if selected_index is None and selected_cell is not None:
        selected_index = selected_cell[0]

    if can_manage and selected_cell is not None:
        cell_row, cell_column = selected_cell
        if cell_column in QUICK_EDIT_COLUMNS:
            quick_token = (selection_signature, cell_row, cell_column)
            if st.session_state.get("companies_quick_edit_token") != quick_token:
                st.session_state["companies_quick_edit_token"] = quick_token
                quick_edit_company_dialog(
                    int(all_companies[cell_row]["id"]), QUICK_EDIT_COLUMNS[cell_column]
                )
    if selected_index is not None and can_manage:
        selected = all_companies[selected_index]
        st.space("small")
        with st.container(border=True):
            info_col, actions_col = st.columns([2.2, 1.4], vertical_alignment="center")
            with info_col:
                st.markdown(f"**{selected['name']}**")
                st.caption(
                    f"{selected['type'].capitalize()} · "
                    f"{selected.get('city') or '—'}"
                )
            with actions_col:
                with st.container(horizontal=True, horizontal_alignment="right"):
                    if st.button(
                        "Editar",
                        icon=":material/edit:",
                        key=f"edit_company_{selected['id']}",
                    ):
                        company_dialog(selected["id"])
                    if st.button(
                        "Ativar/Desativar",
                        icon=":material/toggle_on:",
                        key=f"toggle_company_{selected['id']}",
                    ):
                        companies.save_company(
                            company_id=selected["id"],
                            name=selected["name"],
                            type=selected["type"],
                            parent_id=selected["parent_id"],
                            address=selected["address"],
                            city=selected["city"],
                            state=selected["state"],
                            zip_code=selected["zip_code"],
                            document=selected["document"],
                            phone=selected["phone"],
                            active=not bool(selected["active"]),
                            allow_branch_stock_view=bool(selected["allow_branch_stock_view"]),
                        )
                        ui.set_flash("Situação da empresa atualizada.")
                        st.rerun()
else:
    ui.empty_state("Nenhuma empresa cadastrada", "Cadastre a primeira empresa.")
