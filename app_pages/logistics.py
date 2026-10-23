"""Logística: expedição, transportadoras, rastreio, entidades e movimentações."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import acl, catalog, inventory, logistics, orders, stock_items, ui
from lib.database import BRAZIL_STATES
from lib.errors import DomainError

user = acl.require("logistics.view_shipment")
can_change_shipment = acl.has_perm(user, "logistics.change_shipment")
can_manage_carriers = acl.has_perm(user, "logistics.manage_carrier")
can_adjust_stock = acl.has_perm(user, "logistics.adjust_stock")
can_receive_stock = acl.has_perm(user, "logistics.receive_stock")
can_reverse_stock = acl.has_perm(user, "logistics.reverse_stock")

LOGISTICS_TAG_COLORS = {
    "A separar": "#B45309",
    "Em trânsito": "#2563EB",
    "Atrasado": "#DC2626",
    "Entregue": "#047857",
}
STOCK_STATUS_COLORS = {
    "A separar": "#B45309",
    "Em trânsito": "#2563EB",
    "Concluído": "#047857",
}
STOCK_DOCUMENT_STATUS_COLORS = {
    "A separar": "#B45309",
    "Em trânsito": "#2563EB",
    "Recebido": "#047857",
    "Concluído": "#047857",
    "Divergente": "#DC2626",
    "Estornado": "#7C3AED",
    "Cancelado": "#64748B",
}
STOCK_TRANSIT_STATUS_COLORS = {
    "Em trânsito": "#2563EB",
    "Parcial": "#B45309",
    "Recebido": "#047857",
    "Divergente": "#DC2626",
    "Cancelado": "#64748B",
}


def _period_range(period: str) -> tuple[date, date]:
    today = date.today()
    if period == "90 dias":
        return today - timedelta(days=89), today
    if period == "Este ano":
        return date(today.year, 1, 1), today
    return today - timedelta(days=29), today


def _destination(row) -> str:
    city = row.customer_city if pd.notna(row.customer_city) else ""
    state = row.customer_state if pd.notna(row.customer_state) else ""
    if city and state:
        return f"{city}/{state}"
    return city or state or "—"


def _due_label(row) -> str:
    if row.logistics_status == "Entregue":
        return "Entregue"
    if pd.isna(row.days_to_due):
        return "Sem previsão"
    if row.days_to_due < 0:
        return f"{abs(int(row.days_to_due))} d em atraso"
    if row.days_to_due == 0:
        return "Hoje"
    return f"{int(row.days_to_due)} d"


def _carrier_options() -> dict[str, int]:
    carriers = logistics.list_carriers()
    return {
        f"{row.name}{' · inativa' if not row.active else ''}": int(row.id)
        for row in carriers.itertuples()
    }


def _stock_party_options() -> dict[str, tuple[str, int | None]]:
    """Entidades disponíveis para uma movimentação manual."""
    options: dict[str, tuple[str, int | None]] = {
        inventory.INTERNAL_STOCK: (inventory.INTERNAL_STOCK, None)
    }
    parties = inventory.list_stock_parties(active_only=True)
    for row in parties.itertuples():
        city = row.city if pd.notna(row.city) else ""
        state = row.state if pd.notna(row.state) else ""
        location = f"{city}/{state}" if city and state else city or state
        label = f"{row.kind} · {row.name}"
        if location:
            label += f" · {location}"
        if label in options:
            label = f"{label} · #{int(row.id)}"
        options[label] = (row.kind, int(row.id))
    return options


def _movement_destination(row) -> str:
    if int(row.quantity) < 0 and row.entity_kind != inventory.INTERNAL_STOCK:
        return row.entity_location or row.entity_name or inventory.INTERNAL_STOCK
    return inventory.INTERNAL_STOCK


def _movement_entity(row) -> str:
    if row.entity_kind == inventory.INTERNAL_STOCK:
        return inventory.INTERNAL_STOCK
    return f"{row.entity_kind} · {row.entity_name}"


def _invoice_label(row) -> str:
    number = getattr(row, "invoice_number", None)
    series = getattr(row, "invoice_series", None)
    access_key = getattr(row, "invoice_key", None)
    if pd.notna(number) and str(number).strip():
        label = f"NF {str(number).strip()}"
        if pd.notna(series) and str(series).strip():
            label += f"/{str(series).strip()}"
        return label
    if pd.notna(access_key) and str(access_key).strip():
        return f"NF …{str(access_key).strip()[-6:]}"
    return "—"


def _entity_location(row) -> str:
    city = row.city if pd.notna(row.city) else ""
    state = row.state if pd.notna(row.state) else ""
    if city and state:
        return f"{city}/{state}"
    return city or state or "—"


def _party_label(kind: str | None, name: str | None, location: str | None) -> str:
    name = (name or inventory.INTERNAL_STOCK).strip() or inventory.INTERNAL_STOCK
    if kind and kind != inventory.INTERNAL_STOCK:
        label = f"{kind} · {name}"
    else:
        label = name
    if location:
        label += f" · {location}"
    return label


def _document_route(row) -> str:
    source = _party_label(
        getattr(row, "source_kind", None),
        getattr(row, "source_name", None),
        getattr(row, "source_location", None),
    )
    destination = _party_label(
        getattr(row, "destination_kind", None),
        getattr(row, "destination_name", None),
        getattr(row, "destination_location", None),
    )
    if source == destination:
        return "Estoque interno"
    return f"{source} → {destination}"


def _document_invoice_label(row) -> str:
    number = getattr(row, "invoice_number", None)
    series = getattr(row, "invoice_series", None)
    access_key = getattr(row, "invoice_key", None)
    if pd.notna(number) and str(number).strip():
        label = f"NF {str(number).strip()}"
        if pd.notna(series) and str(series).strip():
            label += f"/{str(series).strip()}"
        return label
    if pd.notna(access_key) and str(access_key).strip():
        return f"NF …{str(access_key).strip()[-6:]}"
    return "—"


def _stock_filter_dates(period: str) -> tuple[str | None, str | None]:
    if period == "Tudo":
        return None, None
    start, end = _period_range(period)
    return start.isoformat(), end.isoformat()


@st.dialog("Preparar envio", width="large", icon=":material/local_shipping:")
def shipment_dialog(order_id: int) -> None:
    if not can_change_shipment:
        st.error("Seu perfil não permite gerenciar envios.")
        return

    order = orders.get_order(order_id)
    if order is None:
        st.error("Pedido não encontrado.")
        return
    shipment = logistics.get_shipment(order_id)
    status = order["status"]

    st.markdown(f"**{order['number']}** · {order['customer_name']}")
    st.caption(
        f"{order['customer_city'] or 'Cidade não informada'}/"
        f"{order['customer_state'] or '—'} · status atual: {status}"
    )
    if status == "Pago":
        st.info(
            "Ao despachar, o status do pedido muda para Enviado e ele passa a "
            "aparecer no acompanhamento de trânsito.",
            icon=":material/info:",
        )

    carrier_options = _carrier_options()
    current_carrier = int(shipment["carrier_id"]) if shipment and shipment["carrier_id"] else None
    carrier_labels = list(carrier_options.keys())
    current_label = next(
        (label for label, value in carrier_options.items() if value == current_carrier),
        None,
    )

    with st.form(f"shipment_form_{order_id}"):
        carrier_label = st.selectbox(
            "Transportadora",
            options=carrier_labels,
            index=carrier_labels.index(current_label) if current_label else None,
            placeholder="Selecione a transportadora",
        )
        service_options = list(logistics.DEFAULT_SERVICES)
        current_service = (shipment or {}).get("service")
        if current_service and current_service not in service_options:
            service_options.append(current_service)
        service = st.selectbox(
            "Serviço",
            options=service_options,
            index=service_options.index(current_service)
            if current_service in service_options
            else 0,
            accept_new_options=True,
        )
        tracking_code = st.text_input(
            "Código de rastreio",
            value=(shipment or {}).get("tracking_code") or "",
            placeholder="Ex.: SG000000123BR",
        )
        expected_default = (
            date.fromisoformat(str(shipment["expected_delivery"]))
            if shipment and shipment.get("expected_delivery")
            else date.today() + timedelta(days=5)
        )
        expected_delivery = st.date_input(
            "Previsão de entrega",
            value=expected_default,
            format="DD/MM/YYYY",
        )
        cost = st.number_input(
            "Frete registrado (R$)",
            min_value=0.0,
            value=float((shipment or {}).get("cost") or order["shipping"] or 0),
            step=5.0,
            format="%.2f",
            help="Valor do frete para acompanhar o custo logístico do envio.",
        )
        notes = st.text_area(
            "Observações do envio (opcional)",
            value=(shipment or {}).get("notes") or "",
            placeholder="Instruções para a transportadora, janela de entrega...",
        )

        mark_shipped = False
        if status == "Pago":
            mark_shipped = st.checkbox(
                "Despachar agora e mudar o status para Enviado",
                value=True,
            )
        elif status == "Enviado":
            st.caption("O pedido já está em trânsito. Salvar atualiza os dados do envio.")
        elif status == "Entregue":
            st.caption("O pedido já foi entregue. Salvar mantém a data de entrega.")

        submitted = st.form_submit_button(
            "Salvar envio",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            logistics.save_shipment(
                order_id=order_id,
                carrier_id=carrier_options.get(carrier_label),
                service=service,
                tracking_code=tracking_code,
                expected_delivery=expected_delivery,
                cost=float(cost),
                notes=notes,
                mark_shipped=mark_shipped or status in ("Enviado", "Entregue"),
                actor=user["name"],
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash(f"Envio do pedido {order['number']} salvo.")
            st.rerun()


@st.dialog("Registrar entrega", icon=":material/check_circle:")
def delivery_dialog(order_id: int) -> None:
    if not can_change_shipment:
        st.error("Seu perfil não permite registrar entregas.")
        return
    order = orders.get_order(order_id)
    if order is None:
        st.error("Pedido não encontrado.")
        return

    st.markdown(f"**{order['number']}** · {order['customer_name']}")
    st.caption(
        "A data informada será usada no cálculo de entregas no prazo. "
        "O status do pedido será atualizado para Entregue."
    )
    delivered_on = st.date_input(
        "Data da entrega",
        value=date.today(),
        max_value=date.today(),
        format="DD/MM/YYYY",
        key=f"delivered_on_{order_id}",
    )
    if st.button(
        "Confirmar entrega",
        type="primary",
        icon=":material/check:",
        width="stretch",
        key=f"confirm_delivery_{order_id}",
    ):
        try:
            logistics.mark_delivered(
                order_id=order_id,
                delivered_on=delivered_on,
                actor=user["name"],
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash(f"Pedido {order['number']} marcado como entregue.")
            st.rerun()


@st.dialog("Transportadora", width="large", icon=":material/local_shipping:")
def carrier_dialog(carrier_id: int | None = None) -> None:
    if not can_manage_carriers:
        st.error("Seu perfil não permite gerenciar transportadoras.")
        return
    carrier = logistics.get_carrier(carrier_id) if carrier_id else None

    with st.form(f"carrier_form_{carrier_id or 'new'}"):
        name = st.text_input(
            "Nome",
            value=carrier["name"] if carrier else "",
            placeholder="Ex.: Correios",
        )
        tracking_url = st.text_input(
            "Endereço de rastreio",
            value=(carrier or {}).get("tracking_url") or "",
            placeholder="https://transportadora.com/rastreio?codigo={tracking}",
            help="Use {tracking} no lugar onde o código deve aparecer.",
        )
        phone = st.text_input(
            "Telefone (opcional)",
            value=(carrier or {}).get("phone") or "",
        )
        active = st.toggle(
            "Transportadora ativa",
            value=bool(carrier["active"]) if carrier else True,
            help="Transportadoras inativas continuam no histórico, mas não aparecem como padrão.",
        )
        st.caption(
            "Para manter o histórico dos envios, transportadoras não são excluídas; "
            "basta desativá-las."
        )
        submitted = st.form_submit_button(
            "Salvar transportadora",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            logistics.save_carrier(
                name=name,
                tracking_url=tracking_url,
                phone=phone,
                active=active,
                carrier_id=carrier_id,
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Transportadora salva com sucesso.")
            st.rerun()


@st.dialog("Entidade de estoque", width="large", icon=":material/warehouse:")
def stock_entity_dialog(entity_id: int | None = None) -> None:
    if not can_adjust_stock:
        st.error("Seu perfil não permite gerenciar entidades de estoque.")
        return

    entity = inventory.get_stock_entity(entity_id) if entity_id else None
    with st.form(f"stock_entity_form_{entity_id or 'new'}"):
        kind = st.selectbox(
            "Tipo",
            options=list(inventory.STOCK_ENTITY_KINDS),
            index=(
                list(inventory.STOCK_ENTITY_KINDS).index(entity["kind"])
                if entity and entity["kind"] in inventory.STOCK_ENTITY_KINDS
                else 0
            ),
            help="Clientes são cadastrados na página Clientes.",
        )
        name = st.text_input(
            "Nome",
            value=entity["name"] if entity else "",
            placeholder="Ex.: Filial São Paulo ou Fornecedor ABC",
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
                placeholder="Ex.: São Paulo",
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
            "Entidade ativa",
            value=bool(entity["active"]) if entity else True,
            help="Entidades inativas continuam no histórico, mas não aparecem para novos movimentos.",
        )
        submitted = st.form_submit_button(
            "Salvar entidade",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        try:
            inventory.save_stock_entity(
                kind=kind,
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
            ui.set_flash("Entidade de estoque salva com sucesso.")
            st.rerun()


@st.dialog("Nova movimentação", width="large", icon=":material/inventory_2:")
def stock_document_dialog() -> None:
    if not can_adjust_stock:
        st.error("Seu perfil não permite movimentar o estoque.")
        return

    products = catalog.list_products(status="Todos")
    if products.empty:
        st.warning("Cadastre um produto antes de movimentar o estoque.")
        return
    product_options = {
        f"{row.name} · {row.sku} · saldo {int(row.stock)}": int(row.id)
        for row in products.itertuples()
    }
    product_labels = list(product_options)
    product_costs = {
        label: float(row.cost or 0)
        for label, row in zip(product_labels, products.itertuples())
    }

    kind = st.segmented_control(
        "Tipo de documento",
        options=["Entrada", "Saída", "Transferência"],
        default="Entrada",
        key="stock_document_kind",
    )
    kind = kind or "Entrada"

    party_options = _stock_party_options()
    if kind == "Transferência":
        party_options = {
            label: value
            for label, value in party_options.items()
            if value[0] != inventory.INTERNAL_STOCK
        }
        if not party_options:
            st.warning(
                "Cadastre uma filial ou fornecedor na aba Entidades para "
                "registrar uma transferência."
            )
            return

    party_labels = list(party_options)
    if kind == "Entrada":
        default_party_index = next(
            (
                index
                for index, label in enumerate(party_labels)
                if label.startswith("Fornecedor")
            ),
            0,
        )
        party_title = "Origem da entrada"
    elif kind == "Saída":
        default_party_index = next(
            (
                index
                for index, label in enumerate(party_labels)
                if label.startswith("Cliente")
            ),
            0,
        )
        party_title = "Destino da saída"
    else:
        default_party_index = 0
        party_title = "Destino da transferência"

    if kind == "Entrada":
        status_options = ["Concluído", "Em trânsito"]
        default_status_index = 0
        status_help = (
            "Concluído soma a entrada ao estoque agora. Em trânsito mantém a "
            "carga aguardando recebimento; o saldo só é somado ao receber."
        )
    elif kind == "Transferência":
        status_options = ["A separar", "Em trânsito", "Concluído"]
        default_status_index = 1
        status_help = (
            "A separar não baixa o estoque até o despacho. Em trânsito baixa "
            "da origem e cria o acompanhamento no destino. Concluído registra "
            "uma transferência imediata."
        )
    else:
        status_options = ["A separar", "Em trânsito", "Concluído"]
        default_status_index = 2
        status_help = (
            "O status acompanha a separação e o transporte. A saída baixa o "
            "estoque central em todos os casos."
        )

    st.caption(
        "Use o botão + para adicionar um ou vários produtos ao documento. Ao "
        "selecionar o produto, a quantidade é preenchida com 1 e o custo com o "
        "valor cadastrado."
    )

    dialog_token = int(st.session_state.get("stock_document_dialog_token", 0))
    seed_key = f"stock_document_seed_{dialog_token}_{kind}"
    version_key = f"stock_document_version_{dialog_token}_{kind}"
    editor_version = int(st.session_state.get(version_key, 0))
    editor_key = (
        f"stock_document_items_{dialog_token}_{kind}_v{editor_version}"
    )
    processed_key = f"stock_document_processed_{editor_key}"
    if seed_key not in st.session_state:
        st.session_state[seed_key] = stock_items.empty_items()

    def _fill_product_defaults() -> None:
        state = st.session_state.get(editor_key)
        if state is None:
            return
        if st.session_state.get(processed_key):
            return
        edited_rows = state.get("edited_rows") or {}
        added_rows = state.get("added_rows") or []
        deleted_rows = state.get("deleted_rows") or []
        product_changed = any(
            "Produto" in changes for changes in edited_rows.values()
        )
        if not product_changed and not added_rows and not deleted_rows:
            return
        st.session_state[seed_key] = stock_items.build_items_seed(
            st.session_state[seed_key], state, product_costs
        )
        st.session_state[version_key] = editor_version + 1
        st.session_state[processed_key] = True

    edited_items = st.data_editor(
        st.session_state[seed_key],
        key=editor_key,
        on_change=_fill_product_defaults,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Produto": st.column_config.SelectboxColumn(
                "Produto",
                options=product_labels,
                required=True,
                width="large",
            ),
            "Quantidade": st.column_config.NumberColumn(
                "Qtd.", min_value=1, step=1, width="small"
            ),
            "Custo unitário": st.column_config.NumberColumn(
                "Custo un. (R$)",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                width="small",
            ),
        },
    )

    with st.form(f"stock_document_form_{kind}"):
        entity_label = st.selectbox(
            party_title,
            options=party_labels,
            index=default_party_index,
            help=(
                "Na entrada, indica de onde o material veio. Na saída ou "
                "transferência, indica quem recebe o estoque."
            ),
        )
        movement_status = st.selectbox(
            "Status inicial",
            options=status_options,
            index=default_status_index,
            help=status_help,
        )
        reason = st.text_input(
            "Motivo",
            placeholder="Ex.: compra de fornecedor, transferência para filial, devolução",
        )
        notes = st.text_area(
            "Observações (opcional)",
            placeholder="Informações complementares para a trilha de auditoria",
        )
        invoice_file = st.file_uploader(
            "XML da nota fiscal (opcional)",
            type=["xml"],
            accept_multiple_files=False,
            help=(
                "Importe o XML da NF-e (até 5 MB) para vincular número, série, "
                "emitente e chave de acesso ao documento."
            ),
        )
        submitted = st.form_submit_button(
            "Registrar movimentação",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if submitted:
        items: list[dict] = []
        seen_products: set[int] = set()
        for row in edited_items.itertuples(index=False):
            label = getattr(row, "Produto", None)
            if label is None or pd.isna(label) or not str(label).strip():
                continue
            if label not in product_options:
                st.error("Um dos produtos selecionados não é válido.")
                return
            product_id = product_options[label]
            if product_id in seen_products:
                st.error("Não repita o mesmo produto no documento.")
                return
            seen_products.add(product_id)
            quantity = getattr(row, "Quantidade", 0)
            cost = getattr(row, "Custo unitário", 0)
            quantity = int(quantity) if pd.notna(quantity) else 0
            cost = float(cost) if pd.notna(cost) else 0.0
            if quantity <= 0:
                st.error("A quantidade dos itens deve ser maior que zero.")
                return
            items.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_cost": cost if kind == "Entrada" and cost > 0 else None,
                }
            )
        if not items:
            st.error("Adicione pelo menos um item à movimentação.")
            return
        try:
            document_id = inventory.create_stock_document(
                kind=kind,
                items=items,
                reason=reason,
                actor=user["name"],
                entity_kind=party_options[entity_label][0],
                entity_id=party_options[entity_label][1],
                status=movement_status,
                invoice_xml=invoice_file.getvalue() if invoice_file else None,
                invoice_file_name=invoice_file.name if invoice_file else None,
                notes=notes,
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            document = inventory.get_stock_document(document_id)
            number = document["number"] if document else f"#{document_id}"
            if kind == "Transferência" and movement_status == "A separar":
                message = f"{number} criado. Use Despachar na aba Documentos."
            elif kind == "Entrada" and movement_status == "Em trânsito":
                message = f"{number} criado. Aguardando recebimento."
            else:
                message = f"{number} registrado com sucesso."
            ui.set_flash(message)
            st.rerun()


def _open_stock_document_dialog() -> None:
    """Abre um novo formulário com a tabela de itens vazia."""
    st.session_state["stock_document_dialog_token"] = (
        int(st.session_state.get("stock_document_dialog_token", 0)) + 1
    )
    stock_document_dialog()


@st.dialog("Receber item em trânsito", width="large", icon=":material/move_to_inbox:")
def stock_receive_dialog(transit_id: int) -> None:
    if not can_receive_stock:
        st.error("Seu perfil não permite receber itens em trânsito.")
        return
    transit = inventory.get_stock_transit(transit_id)
    if transit is None:
        st.error("Item em trânsito não encontrado.")
        return
    remaining = int(transit["quantity"]) - int(transit["received_quantity"])
    st.markdown(f"**{transit['product_name']}** · {transit['document_number']}")
    st.caption(
        f"{_party_label(transit['source_kind'], transit['source_name'], transit['source_location'])}"
        f" → "
        f"{_party_label(transit['destination_kind'], transit['destination_name'], transit['destination_location'])}"
    )
    st.caption(
        f"Quantidade prevista: {int(transit['quantity'])} un. · "
        f"Já recebida: {int(transit['received_quantity'])} un. · "
        f"Saldo em trânsito: {remaining} un."
    )
    if transit["document_kind"] == "Entrada":
        st.info(
            "A quantidade recebida será somada ao estoque central e atualizará "
            "o custo médio do produto.",
            icon=":material/info:",
        )
    else:
        st.info(
            "A transferência já baixou o estoque central. O recebimento confirma "
            "a chegada ao destino e encerra o trânsito.",
            icon=":material/info:",
        )
    received = st.number_input(
        "Quantidade recebida agora",
        min_value=0,
        max_value=max(remaining, 0),
        value=max(remaining, 0),
        step=1,
        key=f"receive_qty_{transit_id}",
    )
    close_divergence = st.checkbox(
        "Encerrar com divergência",
        value=False,
        disabled=int(received) >= remaining,
        help=(
            "Use quando a quantidade recebida for menor que a prevista e não "
            "houver expectativa de completar o recebimento."
        ),
        key=f"receive_divergence_{transit_id}",
    )
    note = st.text_input(
        "Observação do recebimento (opcional)",
        key=f"receive_note_{transit_id}",
    )
    if st.button(
        "Confirmar recebimento",
        type="primary",
        icon=":material/check:",
        width="stretch",
        key=f"confirm_receive_{transit_id}",
    ):
        try:
            inventory.receive_stock_transit(
                transit_id,
                received_quantity=int(received),
                actor=user["name"],
                note=note,
                close_divergence=bool(close_divergence),
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash("Recebimento confirmado e trânsito atualizado.")
            st.rerun()


@st.dialog("Estornar movimentação", width="large", icon=":material/undo:")
def stock_reverse_dialog(document_id: int) -> None:
    if not can_reverse_stock:
        st.error("Seu perfil não permite estornar movimentações.")
        return
    document = inventory.get_stock_document(document_id)
    if document is None:
        st.error("Documento de movimentação não encontrado.")
        return
    st.markdown(f"**{document['number']}** · {document['kind']}")
    st.caption(_document_route(document))
    st.warning(
        "O estorno cria um novo documento inverso. O documento original e o "
        "histórico permanecem preservados para auditoria.",
        icon=":material/warning:",
    )
    reason = st.text_input(
        "Motivo do estorno",
        placeholder="Ex.: lançamento incorreto, devolução, correção de saldo",
    )
    if st.button(
        "Confirmar estorno",
        type="primary",
        icon=":material/undo:",
        width="stretch",
        key=f"confirm_reverse_{document_id}",
    ):
        try:
            reversal_id = inventory.reverse_stock_document(
                document_id, actor=user["name"], reason=reason
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            reversal = inventory.get_stock_document(reversal_id)
            number = reversal["number"] if reversal else f"#{reversal_id}"
            ui.set_flash(f"{document['number']} estornado por {number}.")
            st.rerun()


ui.page_header(
    "Logística",
    "Acompanhe a expedição, o rastreio, as transportadoras, as entidades e as movimentações de estoque.",
    icon=":material/local_shipping:",
)

period = st.segmented_control(
    "Período dos indicadores",
    options=["30 dias", "90 dias", "Este ano"],
    default="30 dias",
    key="logistics_period",
    label_visibility="collapsed",
)
period = period or "30 dias"
start_date, end_date = _period_range(period)
summary = logistics.get_logistics_summary(start_date, end_date)

metric_cols = st.columns(4)
metric_cols[0].metric(
    "A separar",
    ui.number_br(summary["waiting"]),
    border=True,
    icon=":material/package_2:",
    help="Pedidos pagos que ainda não foram despachados.",
)
metric_cols[1].metric(
    "Em trânsito",
    ui.number_br(summary["transit"]),
    border=True,
    icon=":material/local_shipping:",
    help="Pedidos enviados e ainda não entregues.",
)
metric_cols[2].metric(
    "Atrasados",
    ui.number_br(summary["late"]),
    border=True,
    icon=":material/warning:",
    help="Envios em trânsito com previsão de entrega vencida.",
)
metric_cols[3].metric(
    "Entregues no prazo",
    ui.percent(summary["on_time_rate"]),
    border=True,
    icon=":material/task_alt:",
    help=(
        f"{summary['on_time']} de {summary['delivered']} entregas do período "
        "foram concluídas até a previsão."
    ),
)

st.caption(
    f"Entregas no período: {ui.number_br(summary['delivered'])} · "
    f"Prazo médio de entrega: {ui.number_br(summary['avg_delivery_days'], 1)} dias · "
    f"Despacho médio: {ui.number_br(summary['avg_dispatch_hours'], 1)} h · "
    f"Frete registrado: {ui.money(summary['freight_cost'])}"
)

overview_tab, carriers_tab, stock_tab, documents_tab, entities_tab, performance_tab = st.tabs(
    [
        "Expedição",
        "Transportadoras",
        "Estoque",
        "Documentos",
        "Entidades",
        "Desempenho",
    ]
)

with overview_tab:
    search_col, view_col = st.columns([1.4, 2.4], vertical_alignment="bottom")
    with search_col:
        search = st.text_input(
            "Buscar envio",
            placeholder="Pedido, cliente ou rastreio",
            type="search",
            key="logistics_search",
        )
    with view_col:
        view = st.pills(
            "Fila",
            options=list(logistics.FULFILLMENT_VIEWS),
            default="Todos",
            key="logistics_view",
            wrap=True,
        )
    view = view or "Todos"

    fulfillment = logistics.list_fulfillment_orders(
        search=search, view=view, limit=500
    )
    if fulfillment.empty:
        ui.empty_state(
            "Nenhum envio nesta fila",
            "Ajuste os filtros ou aguarde novos pedidos pagos.",
        )
    else:
        display = pd.DataFrame(
            {
                "pedido": fulfillment["number"],
                "cliente": fulfillment["customer_name"],
                "destino": [_destination(row) for row in fulfillment.itertuples()],
                "status": [[status] for status in fulfillment["logistics_status"]],
                "transportadora": fulfillment["carrier_name"].fillna("Não definida"),
                "rastreio": fulfillment["tracking_code"].fillna("—"),
                "previsao": [ui.date_br(value) for value in fulfillment["expected_delivery"]],
                "prazo": [_due_label(row) for row in fulfillment.itertuples()],
                "id": fulfillment["order_id"],
            }
        )
        selection_signature = (
            (search or "").strip().lower(),
            view,
            tuple(int(value) for value in fulfillment["order_id"]),
        )
        st.caption(
            f"{len(fulfillment)} envio{'s' if len(fulfillment) != 1 else ''} "
            f"encontrado{'s' if len(fulfillment) != 1 else ''}."
        )
        event = st.dataframe(
            display,
            hide_index=True,
            height=max(180, min(438, 38 + len(display) * 36)),
            on_select="rerun",
            selection_mode="single-row",
            key=ui.table_key("logistics_table", selection_signature),
            alt="Fila logística com pedido, cliente, status, transportadora e prazo",
            column_config={
                "pedido": st.column_config.TextColumn("Pedido", width=126, pinned=True),
                "cliente": st.column_config.TextColumn("Cliente", width=150),
                "destino": st.column_config.TextColumn("Destino", width=112),
                "status": st.column_config.MultiselectColumn(
                    "Status",
                    options=list(LOGISTICS_TAG_COLORS),
                    color=list(LOGISTICS_TAG_COLORS.values()),
                    width=118,
                ),
                "transportadora": st.column_config.TextColumn(
                    "Transportadora", width=136
                ),
                "rastreio": st.column_config.TextColumn("Rastreio", width=140),
                "previsao": st.column_config.TextColumn("Previsão", width=100),
                "prazo": st.column_config.TextColumn("Prazo", width=108),
                "id": None,
            },
        )

        selected_index = ui.selected_row_index(
            event,
            len(fulfillment),
            signature=selection_signature,
            state_key="logistics_selected_row",
        )
        if selected_index is not None:
            selected = fulfillment.iloc[selected_index]
            order_id = int(selected["order_id"])
            has_tracking = pd.notna(selected["tracking_code"]) and bool(
                str(selected["tracking_code"]).strip()
            )
            has_carrier = pd.notna(selected["carrier_name"]) and bool(
                str(selected["carrier_name"]).strip()
            )
            tracking_link = (
                selected["tracking_link"]
                if pd.notna(selected["tracking_link"])
                else None
            )
            st.space("small")
            with st.container(border=True):
                info_col, actions_col = st.columns(
                    [1.35, 2.4], vertical_alignment="center"
                )
                with info_col:
                    st.markdown(f"**{selected['number']}** · {selected['customer_name']}")
                    transit_detail = (
                        f" · {int(selected['days_in_transit'])} d em trânsito"
                        if selected["order_status"] == "Enviado"
                        and pd.notna(selected["days_in_transit"])
                        else ""
                    )
                    st.caption(
                        f"{_destination(selected)} · {selected['logistics_status']}"
                        f"{transit_detail} · {ui.money(selected['shipping_cost'])} de frete"
                    )
                    if has_tracking:
                        st.caption(
                            f"Rastreio: `{selected['tracking_code']}`"
                            + (
                                f" · {selected['carrier_name']}"
                                if has_carrier
                                else ""
                            )
                        )
                    else:
                        st.caption("Ainda não há código de rastreio.")
                    timeline: list[str] = []
                    if pd.notna(selected["expected_delivery"]):
                        timeline.append(
                            f"Previsão {ui.date_br(selected['expected_delivery'])}"
                        )
                    if pd.notna(selected["shipped_at"]):
                        timeline.append(
                            f"Enviado {ui.datetime_br(selected['shipped_at'])}"
                        )
                    if pd.notna(selected["delivered_at"]):
                        timeline.append(
                            f"Entregue {ui.datetime_br(selected['delivered_at'])}"
                        )
                    if timeline:
                        st.caption(" · ".join(timeline))
                with actions_col:
                    with st.container(horizontal=True, horizontal_alignment="right"):
                        if can_change_shipment:
                            shipment_label = (
                                "Editar envio"
                                if pd.notna(selected["shipment_id"])
                                else "Preparar envio"
                            )
                            if st.button(
                                shipment_label,
                                icon=":material/local_shipping:",
                                key=f"shipment_{order_id}",
                            ):
                                shipment_dialog(order_id)
                            if selected["order_status"] == "Enviado":
                                if st.button(
                                    "Marcar entregue",
                                    icon=":material/check_circle:",
                                    key=f"deliver_{order_id}",
                                ):
                                    delivery_dialog(order_id)
                        if tracking_link:
                            st.link_button(
                                "Abrir rastreio",
                                tracking_link,
                                icon=":material/open_in_new:",
                            )
                    if not can_change_shipment:
                        st.caption("Seu perfil permite apenas consultar a logística.")
        else:
            st.caption(
                "Selecione uma linha para preparar o envio, registrar a entrega "
                "ou abrir o rastreio."
            )

with carriers_tab:
    header_col, action_col = st.columns([2.4, 1], vertical_alignment="center")
    with header_col:
        st.subheader("Transportadoras")
        st.caption(
            "Cadastre os parceiros de entrega e o endereço de rastreio usado no acompanhamento."
        )
    with action_col:
        if can_manage_carriers:
            with st.container(horizontal=True, horizontal_alignment="right"):
                if st.button(
                    "Nova transportadora",
                    type="primary",
                    icon=":material/add:",
                    key="new_carrier_button",
                ):
                    carrier_dialog()

    carriers = logistics.list_carriers()
    if carriers.empty:
        ui.empty_state(
            "Nenhuma transportadora cadastrada",
            "Cadastre a primeira transportadora para vincular aos envios.",
        )
    else:
        carrier_display = pd.DataFrame(
            {
                "transportadora": carriers["name"],
                "telefone": carriers["phone"].fillna("—"),
                "envios": carriers["shipments_count"],
                "status": [
                    ["Ativa" if active else "Inativa"] for active in carriers["active"]
                ],
                "id": carriers["id"],
            }
        )
        carrier_signature = tuple(int(value) for value in carriers["id"])
        carrier_event = st.dataframe(
            carrier_display,
            hide_index=True,
            height=min(360, 38 + len(carrier_display) * 36),
            on_select="rerun",
            selection_mode="single-row",
            key=ui.table_key("carriers_table", carrier_signature),
            alt="Transportadoras cadastradas com telefone, envios e situação",
            column_config={
                "transportadora": st.column_config.TextColumn(
                    "Transportadora", width="large", pinned=True
                ),
                "telefone": st.column_config.TextColumn("Telefone", width="medium"),
                "envios": st.column_config.NumberColumn(
                    "Envios", format="%d", width="small"
                ),
                "status": st.column_config.MultiselectColumn(
                    "Status",
                    options=["Ativa", "Inativa"],
                    color=["#047857", "#64748B"],
                    width=90,
                ),
                "id": None,
            },
        )
        selected_carrier = ui.selected_row_index(
            carrier_event,
            len(carriers),
            signature=carrier_signature,
            state_key="carriers_selected_row",
        )
        if selected_carrier is not None and can_manage_carriers:
            carrier = carriers.iloc[selected_carrier]
            carrier_id = int(carrier["id"])
            st.space("small")
            with st.container(border=True):
                info_col, actions_col = st.columns(
                    [2.2, 1.4], vertical_alignment="center"
                )
                with info_col:
                    st.markdown(f"**{carrier['name']}**")
                    tracking_url = (
                        carrier["tracking_url"]
                        if pd.notna(carrier["tracking_url"])
                        else None
                    )
                    phone = carrier["phone"] if pd.notna(carrier["phone"]) else None
                    st.caption(
                        (tracking_url or "Sem endereço de rastreio")
                        + (f" · {phone}" if phone else "")
                    )
                with actions_col:
                    with st.container(horizontal=True, horizontal_alignment="right"):
                        if st.button(
                            "Editar",
                            icon=":material/edit:",
                            key=f"edit_carrier_{carrier_id}",
                        ):
                            carrier_dialog(carrier_id)
                        active_label = "Desativar" if carrier["active"] else "Ativar"
                        if st.button(
                            active_label,
                            icon=":material/pause_circle:"
                            if carrier["active"]
                            else ":material/play_circle:",
                            key=f"toggle_carrier_{carrier_id}",
                        ):
                            logistics.set_carrier_active(
                                carrier_id, not bool(carrier["active"])
                            )
                            ui.set_flash(
                                f"Transportadora {carrier['name']} "
                                f"{'desativada' if carrier['active'] else 'ativada'}."
                            )
                            st.rerun()
        elif selected_carrier is None:
            st.caption("Selecione uma transportadora para editar ou alterar a situação.")

with stock_tab:
    products = catalog.list_products(status="Todos")
    stock_units = int(products["stock"].sum()) if not products.empty else 0
    low_stock = int(
        ((products["stock"] <= products["min_stock"]) & (products["active"] == 1)).sum()
    ) if not products.empty else 0
    stock_value = float((products["stock"] * products["cost"]).sum()) if not products.empty else 0.0
    transit_summary = inventory.stock_transit_summary()

    stock_metrics = st.columns(4)
    stock_metrics[0].metric(
        "Unidades no estoque central",
        ui.number_br(stock_units),
        border=True,
        icon=":material/inventory_2:",
    )
    stock_metrics[1].metric(
        "Em trânsito",
        ui.number_br(transit_summary["units"]),
        border=True,
        icon=":material/local_shipping:",
        help="Unidades ainda não recebidas em transferências e entradas em trânsito.",
    )
    stock_metrics[2].metric(
        "Produtos em alerta",
        ui.number_br(low_stock),
        border=True,
        icon=":material/warning:",
        help="Produtos ativos no ou abaixo do estoque mínimo.",
    )
    stock_metrics[3].metric(
        "Valor do estoque",
        ui.money(stock_value),
        border=True,
        icon=":material/savings:",
        help="Calculado pelo custo unitário dos produtos no estoque central.",
    )

    stock_header_col, stock_action_col = st.columns(
        [2.4, 1], vertical_alignment="center"
    )
    with stock_header_col:
        st.subheader("Movimentações de estoque")
        st.caption(
            "Livro-razão de vendas, cancelamentos, exclusões, transferências e "
            "movimentações manuais. Cada linha preserva saldo anterior e "
            "posterior, custo, documento de origem, entidade, status e nota fiscal."
        )
    with stock_action_col:
        if can_adjust_stock:
            with st.container(horizontal=True, horizontal_alignment="right"):
                if st.button(
                    "Nova movimentação",
                    type="primary",
                    icon=":material/add_box:",
                    key="new_stock_document_button",
                ):
                    _open_stock_document_dialog()

    movement_search_col, movement_kind_col, movement_status_col, movement_period_col = st.columns(
        [1.5, 1, 1, 0.9], vertical_alignment="bottom"
    )
    with movement_search_col:
        movement_search = st.text_input(
            "Buscar movimentação",
            placeholder="Produto, documento, pedido, entidade, NF ou chave",
            type="search",
            key="stock_movement_search",
        )
    with movement_kind_col:
        movement_kind = st.selectbox(
            "Tipo de movimento",
            options=["Todos", *inventory.STOCK_MOVEMENT_KINDS],
            key="stock_movement_kind",
        )
    with movement_status_col:
        movement_status = st.selectbox(
            "Status",
            options=["Todos", *inventory.STOCK_MOVEMENT_STATUSES],
            key="stock_movement_status",
        )
    with movement_period_col:
        movement_period = st.selectbox(
            "Período",
            options=["Tudo", "30 dias", "90 dias", "Este ano"],
            key="stock_movement_period",
        )
    movement_start, movement_end = _stock_filter_dates(movement_period)

    movements = inventory.list_stock_movements(
        search=movement_search,
        kind=movement_kind or "Todos",
        status=movement_status or "Todos",
        start_date=movement_start,
        end_date=movement_end,
        limit=500,
    )
    if movements.empty:
        ui.empty_state(
            "Nenhuma movimentação encontrada",
            "Ajuste os filtros ou registre uma nova entrada, saída ou transferência.",
        )
    else:
        movement_display = pd.DataFrame(
            {
                "data": pd.to_datetime(movements["created_at"]).dt.strftime(
                    "%d/%m/%Y · %H:%M"
                ),
                "documento": movements["document_number"].fillna("—"),
                "produto": movements["product_name"],
                "tipo": movements["kind"],
                "status": [[value] for value in movements["status"]],
                "quantidade": [
                    f"{int(value):+d}" for value in movements["quantity"]
                ],
                "saldo_anterior": movements["balance_before"],
                "saldo": movements["balance_after"],
                "custo": [
                    ui.money(value) if pd.notna(value) else "—"
                    for value in movements["unit_cost"]
                ],
                "pedido": movements["order_number"].fillna("—"),
                "nf": [_invoice_label(row) for row in movements.itertuples()],
                "id": movements["id"],
            }
        )
        st.caption(f"{len(movements)} movimentação(ões) encontrada(s).")
        movement_signature = (
            (movement_search or "").strip().lower(),
            movement_kind,
            movement_status,
            movement_period,
            tuple(int(value) for value in movements["id"]),
        )
        movement_event = st.dataframe(
            movement_display,
            hide_index=True,
            height=max(220, min(500, 38 + len(movement_display) * 36)),
            on_select="rerun",
            selection_mode="single-row",
            key=ui.table_key("stock_movements_table", movement_signature),
            alt=(
                "Livro-razão de estoque com documento, produto, status, quantidade, "
                "saldo anterior, saldo posterior, custo e nota fiscal"
            ),
            column_config={
                "data": st.column_config.TextColumn("Data", width=125),
                "documento": st.column_config.TextColumn("Documento", width=120),
                "produto": st.column_config.TextColumn("Produto", width=140),
                "tipo": st.column_config.TextColumn("Tipo", width=92),
                "status": st.column_config.MultiselectColumn(
                    "Status",
                    options=list(STOCK_STATUS_COLORS),
                    color=list(STOCK_STATUS_COLORS.values()),
                    width=96,
                ),
                "quantidade": st.column_config.TextColumn("Qtd.", width=44),
                "saldo_anterior": st.column_config.NumberColumn(
                    "Anterior", format="%d", width=62
                ),
                "saldo": st.column_config.NumberColumn(
                    "Saldo", format="%d", width=56
                ),
                "custo": st.column_config.TextColumn("Custo un.", width=86),
                "pedido": st.column_config.TextColumn("Pedido", width=76),
                "nf": st.column_config.TextColumn("NF", width=88),
                "id": None,
            },
        )
        selected_movement = ui.selected_row_index(
            movement_event,
            len(movements),
            signature=movement_signature,
            state_key="stock_movement_selected_row",
        )
        if selected_movement is not None:
            row = movements.iloc[selected_movement]
            document_id = (
                int(row["document_id"]) if pd.notna(row["document_id"]) else None
            )
            st.space("small")
            with st.container(border=True):
                st.markdown(
                    f"**{row['product_name']}** · {row['kind']} · "
                    f"{row['document_number'] or 'sem documento'}"
                )
                st.caption(
                    f"{ui.datetime_br(row['created_at'])} · {row['actor'] or 'Sistema'} · "
                    f"status {row['status']}"
                )
                detail_cols = st.columns(4)
                detail_cols[0].metric(
                    "Quantidade", f"{int(row['quantity']):+d}", border=True
                )
                detail_cols[1].metric(
                    "Saldo anterior",
                    ui.number_br(row["balance_before"]),
                    border=True,
                )
                detail_cols[2].metric(
                    "Saldo posterior",
                    ui.number_br(row["balance_after"]),
                    border=True,
                )
                detail_cols[3].metric(
                    "Custo total",
                    ui.money(row["total_cost"]),
                    border=True,
                )
                st.caption(
                    f"Origem/destino: {_movement_entity(row)} · "
                    f"local: {_movement_destination(row)} · "
                    f"motivo: {row['reason'] or '—'}"
                )
                if document_id is not None:
                    history = inventory.list_document_status_history(document_id)
                    with st.expander(
                        "Histórico de status do documento",
                        icon=":material/history:",
                    ):
                        if history.empty:
                            st.caption("Sem mudanças de status registradas.")
                        else:
                            history_display = pd.DataFrame(
                                {
                                    "de": history["from_status"].fillna("—"),
                                    "para": history["to_status"],
                                    "observacao": history["note"].fillna("—"),
                                    "responsavel": history["actor"].fillna("—"),
                                    "quando": [
                                        ui.datetime_br(value)
                                        for value in history["created_at"]
                                    ],
                                }
                            )
                            st.dataframe(
                                history_display,
                                hide_index=True,
                                alt="Histórico de status do documento de estoque",
                            )

        movement_export = pd.DataFrame(
            {
                "data": [ui.datetime_br(value) for value in movements["created_at"]],
                "documento": movements["document_number"].fillna(""),
                "tipo_documento": movements["document_kind"].fillna(""),
                "status_documento": movements["document_status"].fillna(""),
                "produto": movements["product_name"],
                "sku": movements["product_sku"],
                "tipo": movements["kind"],
                "status": movements["status"],
                "quantidade": movements["quantity"],
                "saldo_anterior": movements["balance_before"],
                "saldo_posterior": movements["balance_after"],
                "custo_unitario": movements["unit_cost"],
                "custo_total": movements["total_cost"],
                "pedido": movements["order_number"].fillna(""),
                "entidade": [
                    _movement_entity(row) for row in movements.itertuples()
                ],
                "local": [
                    _movement_destination(row) for row in movements.itertuples()
                ],
                "motivo": movements["reason"].fillna(""),
                "responsavel": movements["actor"].fillna(""),
                "nf_numero": movements["invoice_number"].fillna(""),
                "nf_chave": movements["invoice_key"].fillna(""),
                "estorno_do_movimento": [
                    int(value) if pd.notna(value) else ""
                    for value in movements["reversal_of_id"]
                ],
            }
        )
        st.download_button(
            "Exportar movimentações (CSV)",
            data=movement_export.to_csv(index=False).encode("utf-8-sig"),
            file_name="movimentacoes-estoque.csv",
            mime="text/csv",
            icon=":material/download:",
            key="download_stock_movements",
        )

        with st.expander("Notas fiscais importadas", icon=":material/receipt_long:"):
            invoices = inventory.list_stock_invoices(limit=100)
            if invoices.empty:
                st.caption(
                    "Nenhuma nota fiscal importada. Use **Nova movimentação** para "
                    "anexar o XML de uma NF-e a um documento."
                )
            else:
                invoice_display = pd.DataFrame(
                    {
                        "numero": invoices["number"].fillna("s/n"),
                        "serie": invoices["series"].fillna("—"),
                        "emitente": invoices["issuer_name"].fillna("—"),
                        "valor": [
                            ui.money(value) if pd.notna(value) else "—"
                            for value in invoices["total_value"]
                        ],
                        "movimentacoes": invoices["movements_count"],
                        "importada": [
                            ui.datetime_br(value) for value in invoices["created_at"]
                        ],
                    }
                )
                st.dataframe(
                    invoice_display,
                    hide_index=True,
                    height=min(300, 38 + len(invoice_display) * 36),
                    alt="Notas fiscais importadas com número, emitente e valor",
                    column_config={
                        "numero": st.column_config.TextColumn("Número", width=100),
                        "serie": st.column_config.TextColumn("Série", width=70),
                        "emitente": st.column_config.TextColumn("Emitente", width=250),
                        "valor": st.column_config.TextColumn("Valor", width=100),
                        "movimentacoes": st.column_config.NumberColumn(
                            "Movimentações", format="%d", width=120
                        ),
                        "importada": st.column_config.TextColumn(
                            "Importada em", width=150
                        ),
                    },
                )
                invoice_labels: dict[str, int] = {}
                for row in invoices.itertuples():
                    label = f"NF {row.number or 's/n'}"
                    if pd.notna(row.series) and str(row.series).strip():
                        label += f"/{row.series}"
                    if pd.notna(row.access_key) and str(row.access_key).strip():
                        label += f" · …{str(row.access_key)[-6:]}"
                    if label in invoice_labels:
                        label += f" · #{int(row.id)}"
                    invoice_labels[label] = int(row.id)
                selected_invoice_label = st.selectbox(
                    "Selecionar nota fiscal para baixar o XML",
                    options=list(invoice_labels),
                    key="stock_invoice_download",
                )
                selected_invoice = inventory.get_stock_invoice(
                    invoice_labels[selected_invoice_label]
                )
                if selected_invoice:
                    st.download_button(
                        "Baixar XML da nota fiscal",
                        data=selected_invoice["xml"].encode("utf-8"),
                        file_name=selected_invoice["file_name"]
                        or "nota-fiscal.xml",
                        mime="application/xml",
                        icon=":material/download:",
                        key=f"download_stock_invoice_{selected_invoice['id']}",
                    )

with documents_tab:
    document_header_col, document_action_col = st.columns(
        [2.4, 1], vertical_alignment="center"
    )
    with document_header_col:
        st.subheader("Documentos de movimentação")
        st.caption(
            "Cabeçalhos com vários itens, status, origem, destino, nota fiscal "
            "e histórico de alterações. Transferências e entradas em trânsito "
            "podem ser recebidas e conferidas."
        )
    with document_action_col:
        if can_adjust_stock:
            with st.container(horizontal=True, horizontal_alignment="right"):
                if st.button(
                    "Nova movimentação",
                    type="primary",
                    icon=":material/add_box:",
                    key="new_stock_document_button_documents",
                ):
                    _open_stock_document_dialog()

    transit_search = st.text_input(
        "Buscar item em trânsito",
        placeholder="Produto, documento, origem ou destino",
        type="search",
        key="stock_transit_search",
    )
    open_transits = inventory.list_stock_transits(
        status="Abertos", search=transit_search, limit=300
    )
    st.markdown("#### Em trânsito")
    if open_transits.empty:
        st.caption("Nenhum item em trânsito no momento.")
    else:
        transit_display = pd.DataFrame(
            {
                "documento": open_transits["document_number"],
                "produto": open_transits["product_name"],
                "origem": [
                    _party_label(row.source_kind, row.source_name, row.source_location)
                    for row in open_transits.itertuples()
                ],
                "destino": [
                    _party_label(
                        row.destination_kind,
                        row.destination_name,
                        row.destination_location,
                    )
                    for row in open_transits.itertuples()
                ],
                "previsto": open_transits["quantity"],
                "recebido": open_transits["received_quantity"],
                "saldo": open_transits["quantity"] - open_transits["received_quantity"],
                "status": [[value] for value in open_transits["status"]],
                "enviado": [
                    ui.datetime_br(value) for value in open_transits["shipped_at"]
                ],
                "id": open_transits["id"],
            }
        )
        transit_signature = (
            (transit_search or "").strip().lower(),
            tuple(int(value) for value in open_transits["id"]),
        )
        transit_event = st.dataframe(
            transit_display,
            hide_index=True,
            height=max(160, min(360, 38 + len(transit_display) * 36)),
            on_select="rerun",
            selection_mode="single-row",
            key=ui.table_key("stock_transits_table", transit_signature),
            alt="Itens em trânsito com documento, produto, origem, destino e saldo",
            column_config={
                "documento": st.column_config.TextColumn("Documento", width=120),
                "produto": st.column_config.TextColumn("Produto", width=170),
                "origem": st.column_config.TextColumn("Origem", width=180),
                "destino": st.column_config.TextColumn("Destino", width=180),
                "previsto": st.column_config.NumberColumn(
                    "Previsto", format="%d", width=70
                ),
                "recebido": st.column_config.NumberColumn(
                    "Recebido", format="%d", width=70
                ),
                "saldo": st.column_config.NumberColumn("Saldo", format="%d", width=60),
                "status": st.column_config.MultiselectColumn(
                    "Status",
                    options=list(STOCK_TRANSIT_STATUS_COLORS),
                    color=list(STOCK_TRANSIT_STATUS_COLORS.values()),
                    width=94,
                ),
                "enviado": st.column_config.TextColumn("Enviado em", width=140),
                "id": None,
            },
        )
        selected_transit = ui.selected_row_index(
            transit_event,
            len(open_transits),
            signature=transit_signature,
            state_key="stock_transit_selected_row",
        )
        if selected_transit is not None:
            transit_row = open_transits.iloc[selected_transit]
            transit_id = int(transit_row["id"])
            st.space("small")
            with st.container(border=True):
                st.markdown(
                    f"**{transit_row['product_name']}** · {transit_row['document_number']}"
                )
                st.caption(
                    f"{_party_label(transit_row['source_kind'], transit_row['source_name'], transit_row['source_location'])}"
                    f" → "
                    f"{_party_label(transit_row['destination_kind'], transit_row['destination_name'], transit_row['destination_location'])}"
                    f" · {int(transit_row['quantity'])} un. previstas"
                )
                if can_receive_stock:
                    if st.button(
                        "Receber item",
                        type="primary",
                        icon=":material/move_to_inbox:",
                        key=f"receive_transit_{transit_id}",
                    ):
                        stock_receive_dialog(transit_id)
                else:
                    st.caption("Seu perfil permite apenas consultar o trânsito.")

    st.divider()
    st.markdown("#### Documentos")
    doc_search_col, doc_kind_col, doc_status_col, doc_period_col = st.columns(
        [1.5, 1, 1, 0.9], vertical_alignment="bottom"
    )
    with doc_search_col:
        document_search = st.text_input(
            "Buscar documento",
            placeholder="Número, produto, pedido, entidade, NF ou chave",
            type="search",
            key="stock_document_search",
        )
    with doc_kind_col:
        document_kind = st.selectbox(
            "Tipo de documento",
            options=["Todos", *inventory.STOCK_DOCUMENT_KINDS],
            key="stock_document_kind_filter",
        )
    with doc_status_col:
        document_status = st.selectbox(
            "Status do documento",
            options=["Todos", *inventory.STOCK_DOCUMENT_STATUSES],
            key="stock_document_status_filter",
        )
    with doc_period_col:
        document_period = st.selectbox(
            "Período",
            options=["Tudo", "30 dias", "90 dias", "Este ano"],
            key="stock_document_period",
        )
    document_start, document_end = _stock_filter_dates(document_period)

    documents = inventory.list_stock_documents(
        search=document_search,
        kind=document_kind or "Todos",
        status=document_status or "Todos",
        start_date=document_start,
        end_date=document_end,
        limit=300,
    )
    if documents.empty:
        ui.empty_state(
            "Nenhum documento encontrado",
            "Ajuste os filtros ou registre uma nova movimentação.",
        )
    else:
        document_display = pd.DataFrame(
            {
                "numero": documents["number"],
                "data": pd.to_datetime(documents["created_at"]).dt.strftime(
                    "%d/%m/%Y · %H:%M"
                ),
                "tipo": documents["kind"],
                "status": [[value] for value in documents["status"]],
                "rota": [_document_route(row) for row in documents.itertuples()],
                "itens": documents["item_count"],
                "unidades": documents["units"],
                "valor": [ui.money(value) for value in documents["total_cost"]],
                "pedido": documents["order_number"].fillna("—"),
                "nf": [_document_invoice_label(row) for row in documents.itertuples()],
                "responsavel": documents["created_by"].fillna("—"),
                "id": documents["id"],
            }
        )
        document_signature = (
            (document_search or "").strip().lower(),
            document_kind,
            document_status,
            document_period,
            tuple(int(value) for value in documents["id"]),
        )
        document_event = st.dataframe(
            document_display,
            hide_index=True,
            height=max(220, min(460, 38 + len(document_display) * 36)),
            on_select="rerun",
            selection_mode="single-row",
            key=ui.table_key("stock_documents_table", document_signature),
            alt=(
                "Documentos de movimentação com número, tipo, status, rota, "
                "itens, valor e nota fiscal"
            ),
            column_config={
                "numero": st.column_config.TextColumn(
                    "Documento", width=120, pinned=True
                ),
                "data": st.column_config.TextColumn("Data", width=125),
                "tipo": st.column_config.TextColumn("Tipo", width=100),
                "status": st.column_config.MultiselectColumn(
                    "Status",
                    options=list(STOCK_DOCUMENT_STATUS_COLORS),
                    color=list(STOCK_DOCUMENT_STATUS_COLORS.values()),
                    width=104,
                ),
                "rota": st.column_config.TextColumn("Origem → destino", width=280),
                "itens": st.column_config.NumberColumn(
                    "Itens", format="%d", width=54
                ),
                "unidades": st.column_config.NumberColumn(
                    "Un.", format="%d", width=48
                ),
                "valor": st.column_config.TextColumn("Valor", width=94),
                "pedido": st.column_config.TextColumn("Pedido", width=76),
                "nf": st.column_config.TextColumn("NF", width=84),
                "responsavel": st.column_config.TextColumn("Responsável", width=120),
                "id": None,
            },
        )
        selected_document = ui.selected_row_index(
            document_event,
            len(documents),
            signature=document_signature,
            state_key="stock_document_selected_row",
        )
        if selected_document is not None:
            document_row = documents.iloc[selected_document]
            document_id = int(document_row["id"])
            document = inventory.get_stock_document(document_id)
            if document:
                st.space("small")
                with st.container(border=True):
                    header_col, action_col = st.columns(
                        [2.2, 1.6], vertical_alignment="center"
                    )
                    with header_col:
                        st.markdown(
                            f"**{document['number']}** · {document['kind']}"
                        )
                        st.caption(
                            f"{_document_route(document_row)} · "
                            f"status {document['status']} · "
                            f"criado por {document['created_by']} em "
                            f"{ui.datetime_br(document['created_at'])}"
                        )
                        if document["reason"]:
                            st.caption(f"Motivo: {document['reason']}")
                        if document["notes"]:
                            st.caption(f"Observações: {document['notes']}")
                    with action_col:
                        with st.container(
                            horizontal=True, horizontal_alignment="right"
                        ):
                            if (
                                document["kind"] == "Transferência"
                                and document["status"] == "A separar"
                                and can_adjust_stock
                            ):
                                if st.button(
                                    "Despachar",
                                    type="primary",
                                    icon=":material/local_shipping:",
                                    key=f"ship_document_{document_id}",
                                ):
                                    try:
                                        inventory.ship_stock_document(
                                            document_id, user["name"]
                                        )
                                    except DomainError as exc:
                                        st.error(str(exc))
                                    else:
                                        ui.set_flash(
                                            f"{document['number']} despachado para trânsito."
                                        )
                                        st.rerun()
                            if (
                                document["kind"] == "Saída"
                                and document["status"] == "A separar"
                                and can_adjust_stock
                            ):
                                if st.button(
                                    "Marcar em trânsito",
                                    icon=":material/local_shipping:",
                                    key=f"advance_document_{document_id}",
                                ):
                                    try:
                                        inventory.advance_stock_document(
                                            document_id, "Em trânsito", user["name"]
                                        )
                                    except DomainError as exc:
                                        st.error(str(exc))
                                    else:
                                        ui.set_flash(
                                            f"{document['number']} marcado em trânsito."
                                        )
                                        st.rerun()
                            if (
                                document["kind"] == "Saída"
                                and document["status"] == "Em trânsito"
                                and can_adjust_stock
                            ):
                                if st.button(
                                    "Concluir",
                                    icon=":material/check_circle:",
                                    key=f"complete_document_{document_id}",
                                ):
                                    try:
                                        inventory.advance_stock_document(
                                            document_id, "Concluído", user["name"]
                                        )
                                    except DomainError as exc:
                                        st.error(str(exc))
                                    else:
                                        ui.set_flash(
                                            f"{document['number']} concluído."
                                        )
                                        st.rerun()
                            if (
                                document["kind"] in (
                                    "Entrada",
                                    "Saída",
                                    "Transferência",
                                    "Ajuste",
                                )
                                and document["status"]
                                in ("Concluído", "Recebido", "Divergente")
                                and can_reverse_stock
                                and not document["reversed_by_document_id"]
                            ):
                                if st.button(
                                    "Estornar",
                                    icon=":material/undo:",
                                    key=f"reverse_document_{document_id}",
                                ):
                                    stock_reverse_dialog(document_id)

                    items = inventory.list_stock_document_items(document_id)
                    if not items.empty:
                        item_display = pd.DataFrame(
                            {
                                "produto": items["product_name"],
                                "sku": items["product_sku"],
                                "quantidade": items["quantity"],
                                "recebido": items["received_quantity"],
                                "custo_unitario": [
                                    ui.money(value) for value in items["unit_cost"]
                                ],
                                "custo_total": [
                                    ui.money(value) for value in items["total_cost"]
                                ],
                            }
                        )
                        st.dataframe(
                            item_display,
                            hide_index=True,
                            alt="Itens do documento de movimentação",
                            column_config={
                                "produto": st.column_config.TextColumn(
                                    "Produto", width=220
                                ),
                                "sku": st.column_config.TextColumn("SKU", width=100),
                                "quantidade": st.column_config.NumberColumn(
                                    "Qtd.", format="%d", width=64
                                ),
                                "recebido": st.column_config.NumberColumn(
                                    "Recebido", format="%d", width=76
                                ),
                                "custo_unitario": st.column_config.TextColumn(
                                    "Custo un.", width=100
                                ),
                                "custo_total": st.column_config.TextColumn(
                                    "Custo total", width=110
                                ),
                            },
                        )

                    if document["invoice_id"]:
                        invoice = inventory.get_stock_invoice(
                            int(document["invoice_id"])
                        )
                        if invoice:
                            st.download_button(
                                "Baixar XML da nota fiscal",
                                data=invoice["xml"].encode("utf-8"),
                                file_name=invoice["file_name"] or "nota-fiscal.xml",
                                mime="application/xml",
                                icon=":material/download:",
                                key=f"download_document_invoice_{document_id}",
                            )

                    document_transits = inventory.list_stock_transits(
                        status="Abertos", limit=500
                    )
                    if not document_transits.empty:
                        document_transits = document_transits[
                            document_transits["document_id"] == document_id
                        ]
                    if not document_transits.empty:
                        st.caption("Itens deste documento aguardando recebimento:")
                        for transit_row in document_transits.itertuples():
                            transit_id = int(transit_row.id)
                            cols = st.columns([3, 1])
                            with cols[0]:
                                st.caption(
                                    f"{transit_row.product_name} · "
                                    f"{int(transit_row.quantity) - int(transit_row.received_quantity)} un. "
                                    f"em trânsito"
                                )
                            with cols[1]:
                                if can_receive_stock:
                                    if st.button(
                                        "Receber",
                                        icon=":material/move_to_inbox:",
                                        key=f"receive_document_transit_{transit_id}",
                                    ):
                                        stock_receive_dialog(transit_id)
                                else:
                                    st.caption("Sem permissão")

                    history = inventory.list_document_status_history(document_id)
                    with st.expander(
                        "Histórico de status", icon=":material/history:"
                    ):
                        if history.empty:
                            st.caption("Sem mudanças de status registradas.")
                        else:
                            history_display = pd.DataFrame(
                                {
                                    "de": history["from_status"].fillna("—"),
                                    "para": history["to_status"],
                                    "observacao": history["note"].fillna("—"),
                                    "responsavel": history["actor"].fillna("—"),
                                    "quando": [
                                        ui.datetime_br(value)
                                        for value in history["created_at"]
                                    ],
                                }
                            )
                            st.dataframe(
                                history_display,
                                hide_index=True,
                                alt="Histórico de status do documento",
                            )

        document_export = pd.DataFrame(
            {
                "documento": documents["number"],
                "criado_em": [
                    ui.datetime_br(value) for value in documents["created_at"]
                ],
                "tipo": documents["kind"],
                "status": documents["status"],
                "origem": [
                    _party_label(row.source_kind, row.source_name, row.source_location)
                    for row in documents.itertuples()
                ],
                "destino": [
                    _party_label(
                        row.destination_kind,
                        row.destination_name,
                        row.destination_location,
                    )
                    for row in documents.itertuples()
                ],
                "itens": documents["item_count"],
                "unidades": documents["units"],
                "custo_total": documents["total_cost"],
                "pedido": documents["order_number"].fillna(""),
                "nf_numero": documents["invoice_number"].fillna(""),
                "nf_chave": documents["invoice_key"].fillna(""),
                "responsavel": documents["created_by"].fillna(""),
                "motivo": documents["reason"].fillna(""),
                "observacao": documents["notes"].fillna(""),
            }
        )
        st.download_button(
            "Exportar documentos (CSV)",
            data=document_export.to_csv(index=False).encode("utf-8-sig"),
            file_name="documentos-movimentacao.csv",
            mime="text/csv",
            icon=":material/download:",
            key="download_stock_documents",
        )

with entities_tab:
    entity_header_col, entity_action_col = st.columns(
        [2.4, 1], vertical_alignment="center"
    )
    with entity_header_col:
        st.subheader("Entidades de estoque")
        st.caption(
            "Cadastre filiais e fornecedores que podem receber o estoque ou "
            "ser a origem de uma entrada. Clientes são cadastrados na página Clientes."
        )
    with entity_action_col:
        if can_adjust_stock:
            with st.container(horizontal=True, horizontal_alignment="right"):
                if st.button(
                    "Nova entidade",
                    type="primary",
                    icon=":material/add:",
                    key="new_stock_entity_button",
                ):
                    stock_entity_dialog()

    entities = inventory.list_stock_entities()
    if entities.empty:
        ui.empty_state(
            "Nenhuma filial ou fornecedor cadastrado",
            "Cadastre a primeira entidade para vinculá-la às movimentações de estoque.",
        )
    else:
        entity_display = pd.DataFrame(
            {
                "entidade": entities["name"],
                "tipo": entities["kind"],
                "documento": entities["document"].fillna("—"),
                "local": [_entity_location(row) for row in entities.itertuples()],
                "movimentacoes": entities["movements_count"],
                "situacao": [
                    ["Ativa" if active else "Inativa"]
                    for active in entities["active"]
                ],
                "id": entities["id"],
            }
        )
        entity_signature = tuple(int(value) for value in entities["id"])
        entity_event = st.dataframe(
            entity_display,
            hide_index=True,
            height=min(360, 38 + len(entity_display) * 36),
            on_select="rerun",
            selection_mode="single-row",
            key=ui.table_key("stock_entities_table", entity_signature),
            alt="Filiais e fornecedores de estoque com tipo, local e movimentações",
            column_config={
                "entidade": st.column_config.TextColumn("Entidade", width=270),
                "tipo": st.column_config.TextColumn("Tipo", width=82),
                "documento": st.column_config.TextColumn("Documento", width=150),
                "local": st.column_config.TextColumn("Local", width=120),
                "movimentacoes": st.column_config.NumberColumn(
                    "Movimentações", format="%d", width=120
                ),
                "situacao": st.column_config.MultiselectColumn(
                    "Situação",
                    options=["Ativa", "Inativa"],
                    color=["#047857", "#64748B"],
                    width=90,
                ),
                "id": None,
            },
        )
        selected_entity = ui.selected_row_index(
            entity_event,
            len(entities),
            signature=entity_signature,
            state_key="stock_entities_selected_row",
        )
        if selected_entity is not None and can_adjust_stock:
            entity = entities.iloc[selected_entity]
            entity_id = int(entity["id"])
            st.space("small")
            with st.container(border=True):
                info_col, actions_col = st.columns(
                    [2.2, 1.4], vertical_alignment="center"
                )
                with info_col:
                    st.markdown(f"**{entity['kind']} · {entity['name']}**")
                    st.caption(
                        f"{_entity_location(entity)} · "
                        f"{int(entity['movements_count'])} movimentação(ões)"
                    )
                with actions_col:
                    with st.container(horizontal=True, horizontal_alignment="right"):
                        if st.button(
                            "Editar",
                            icon=":material/edit:",
                            key=f"edit_stock_entity_{entity_id}",
                        ):
                            stock_entity_dialog(entity_id)
                        active_label = "Desativar" if entity["active"] else "Ativar"
                        if st.button(
                            active_label,
                            icon=":material/pause_circle:"
                            if entity["active"]
                            else ":material/play_circle:",
                            key=f"toggle_stock_entity_{entity_id}",
                        ):
                            inventory.set_stock_entity_active(
                                entity_id, not bool(entity["active"])
                            )
                            ui.set_flash(
                                f"Entidade {entity['name']} "
                                f"{'desativada' if entity['active'] else 'ativada'}."
                            )
                            st.rerun()
        elif selected_entity is None:
            st.caption("Selecione uma entidade para editar ou alterar a situação.")
        if not can_adjust_stock:
            st.caption("Seu perfil permite apenas consultar as entidades de estoque.")

with performance_tab:
    st.subheader("Desempenho por transportadora")
    st.caption(
        f"Entregas concluídas entre {ui.date_br(start_date)} e {ui.date_br(end_date)}."
    )
    performance = logistics.get_carrier_performance(start_date, end_date)
    if performance.empty:
        ui.empty_state(
            "Ainda não há entregas no período",
            "Os indicadores aparecem quando envios forem marcados como entregues.",
        )
    else:
        performance_display = pd.DataFrame(
            {
                "transportadora": performance["carrier_name"],
                "entregues": performance["delivered"],
                "no_prazo": [ui.percent(value) for value in performance["on_time_rate"]],
                "prazo_medio": [
                    f"{ui.number_br(value, 1)} dias"
                    for value in performance["avg_delivery_days"]
                ],
                "frete_medio": [
                    ui.money(value) for value in performance["avg_freight"]
                ],
                "frete_total": [
                    ui.money(value) for value in performance["total_freight"]
                ],
            }
        )
        st.dataframe(
            performance_display,
            hide_index=True,
            height=min(420, 38 + len(performance_display) * 36),
            alt="Desempenho de prazo e frete por transportadora",
            column_config={
                "transportadora": st.column_config.TextColumn(
                    "Transportadora", width="large", pinned=True
                ),
                "entregues": st.column_config.NumberColumn(
                    "Entregues", format="%d", width="small"
                ),
                "no_prazo": st.column_config.TextColumn("No prazo", width="small"),
                "prazo_medio": st.column_config.TextColumn("Prazo médio", width="small"),
                "frete_medio": st.column_config.TextColumn("Frete médio", width="small"),
                "frete_total": st.column_config.TextColumn("Frete total", width="small"),
            },
        )
