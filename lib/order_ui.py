"""Fluxo de criação de pedidos em uma janela modal."""

from __future__ import annotations

import streamlit as st

from lib import catalog, orders, ui
from lib.database import CHANNELS, PAYMENT_METHODS
from lib.errors import DomainError


def _remove_cart_item(index: int) -> None:
    cart = st.session_state.get("_new_order_cart", [])
    if 0 <= index < len(cart):
        cart.pop(index)


def open_new_order_dialog() -> None:
    st.session_state["_new_order_token"] = st.session_state.get("_new_order_token", 0) + 1
    st.session_state["_new_order_cart"] = []
    new_order_dialog()


@st.dialog("Novo pedido", width="large", icon=":material/add_shopping_cart:")
def new_order_dialog() -> None:
    token = st.session_state.get("_new_order_token", 0)
    cart: list[dict] = st.session_state.setdefault("_new_order_cart", [])

    customer_df = catalog.list_customers(status="Ativo")
    product_df = catalog.list_products(status="Ativos")
    product_df = product_df[product_df["stock"] > 0].reset_index(drop=True)

    customers = {
        f"{row.name} · {row.city or 'Sem cidade'}/{(row.state or '—')}": int(row.id)
        for row in customer_df.itertuples()
    }
    products: dict[str, dict] = {}
    for row in product_df.itertuples():
        label = f"{row.name} · {row.sku}"
        products[label] = {
            "id": int(row.id),
            "name": row.name,
            "sku": row.sku,
            "price": float(row.price),
            "stock": int(row.stock),
        }

    if not customers:
        st.warning(
            "Cadastre um cliente ativo antes de criar um pedido.",
            icon=":material/person_add:",
        )
    if not products:
        st.warning(
            "Nenhum produto ativo com estoque disponível.",
            icon=":material/inventory_2:",
        )

    st.markdown("**Dados do pedido**")
    col_customer, col_channel = st.columns([1.7, 1])
    with col_customer:
        customer_label = st.selectbox(
            "Cliente",
            options=list(customers.keys()),
            index=None,
            placeholder="Selecione um cliente",
            key=f"new_order_customer_{token}",
        )
    with col_channel:
        channel = st.selectbox(
            "Canal de venda",
            options=list(CHANNELS),
            key=f"new_order_channel_{token}",
        )

    col_payment, col_status = st.columns(2)
    with col_payment:
        payment = st.selectbox(
            "Forma de pagamento",
            options=list(PAYMENT_METHODS),
            key=f"new_order_payment_{token}",
        )
    with col_status:
        initial_status = st.segmented_control(
            "Status inicial",
            options=["Pendente", "Pago"],
            default="Pendente",
            key=f"new_order_status_{token}",
        )

    st.space("medium")
    st.markdown("**Itens do pedido**")
    st.caption("Os itens são reservados do estoque assim que o pedido for criado.")

    add_col, qty_col, button_col = st.columns([3, 1, 1.2], vertical_alignment="bottom")
    with add_col:
        product_label = st.selectbox(
            "Produto",
            options=list(products.keys()),
            index=None,
            placeholder="Busque pelo nome ou SKU",
            key=f"new_order_product_{token}",
        )
    selected_product = products.get(product_label) if product_label else None

    with qty_col:
        max_quantity = max(1, selected_product["stock"] if selected_product else 1)
        quantity = st.number_input(
            "Quantidade",
            min_value=1,
            max_value=max_quantity,
            value=1,
            step=1,
            key=f"new_order_qty_{token}",
        )

    with button_col:
        add_clicked = st.button(
            "Adicionar",
            icon=":material/add:",
            width="stretch",
            key=f"new_order_add_{token}",
            disabled=not selected_product,
        )

    if add_clicked and selected_product:
        existing = next(
            (item for item in cart if item["product_id"] == selected_product["id"]), None
        )
        existing_qty = existing["quantity"] if existing else 0
        if existing_qty + int(quantity) > selected_product["stock"]:
            st.error(
                f"Estoque insuficiente. Já existem {existing_qty} un. no carrinho e "
                f"o estoque disponível é de {selected_product['stock']} un."
            )
        else:
            if existing:
                existing["quantity"] += int(quantity)
            else:
                cart.append(
                    {"product_id": selected_product["id"], "quantity": int(quantity)}
                )
            st.toast("Item adicionado ao pedido.", icon=":material/check_circle:")

    if selected_product:
        st.caption(
            f"{ui.money(selected_product['price'])} por unidade · "
            f"{selected_product['stock']} un. em estoque"
        )

    st.space("small")
    if not cart:
        st.caption("Nenhum item adicionado ainda.")
    else:
        subtotal = 0.0
        for index, item in enumerate(cart):
            product = next(
                (value for value in products.values() if value["id"] == item["product_id"]),
                None,
            )
            if product is None:
                continue
            line_total = product["price"] * item["quantity"]
            subtotal += line_total
            item_col, qty_col, total_col, action_col = st.columns(
                [4.2, 1.1, 1.4, 0.8], vertical_alignment="center"
            )
            with item_col:
                st.markdown(f"**{product['name']}**")
                st.caption(f"{product['sku']} · {ui.money(product['price'])} / un.")
            with qty_col:
                st.markdown(f"{item['quantity']} un.")
            with total_col:
                st.markdown(f"**{ui.money(line_total)}**")
            with action_col:
                st.button(
                    "Remover",
                    icon=":material/delete:",
                    type="tertiary",
                    key=f"remove_order_item_{token}_{index}",
                    on_click=_remove_cart_item,
                    args=(index,),
                )

    subtotal = sum(
        next(
            (value["price"] for value in products.values() if value["id"] == item["product_id"]),
            0.0,
        )
        * item["quantity"]
        for item in cart
    )

    st.space("small")
    discount_col, shipping_col = st.columns(2)
    with discount_col:
        discount = st.number_input(
            "Desconto (R$)",
            min_value=0.0,
            value=0.0,
            step=5.0,
            format="%.2f",
            key=f"new_order_discount_{token}",
        )
    with shipping_col:
        shipping = st.number_input(
            "Frete (R$)",
            min_value=0.0,
            value=0.0,
            step=5.0,
            format="%.2f",
            key=f"new_order_shipping_{token}",
        )

    total = max(0.0, round(subtotal - float(discount) + float(shipping), 2))
    st.metric(
        "Total do pedido",
        ui.money(total),
        border=True,
        help=(
            f"Subtotal {ui.money_md(subtotal)} − desconto {ui.money_md(discount)} "
            f"+ frete {ui.money_md(shipping)}"
        ),
    )

    notes = st.text_area(
        "Observações (opcional)",
        placeholder="Instruções de entrega, preferências do cliente...",
        key=f"new_order_notes_{token}",
    )

    st.space("small")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancelar", key=f"cancel_order_{token}"):
            st.rerun()
        create_clicked = st.button(
            "Criar pedido",
            type="primary",
            icon=":material/check:",
            disabled=not cart or not customers,
            key=f"create_order_{token}",
        )

    if create_clicked:
        if not customer_label:
            st.error("Selecione o cliente do pedido.")
        elif initial_status not in ("Pendente", "Pago"):
            st.error("Selecione o status inicial do pedido.")
        elif not cart:
            st.error("Adicione pelo menos um item.")
        elif float(discount) > subtotal:
            st.error("O desconto não pode ser maior que o subtotal.")
        else:
            try:
                _, number = orders.create_order(
                    customer_id=customers[customer_label],
                    status=initial_status,
                    payment_method=payment,
                    channel=channel,
                    discount=float(discount),
                    shipping=float(shipping),
                    notes=notes,
                    items=[
                        (item["product_id"], item["quantity"]) for item in cart
                    ],
                    actor=st.session_state.get("auth_user", {}).get(
                        "name", "Sistema"
                    ),
                )
            except DomainError as exc:
                st.error(str(exc))
            else:
                st.session_state["_new_order_cart"] = []
                ui.set_flash(f"Pedido {number} criado com sucesso.")
                st.rerun()
