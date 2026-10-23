"""Tela de entrada do painel administrativo."""

from __future__ import annotations

import os
import time
from datetime import datetime

import streamlit as st

from lib.auth import authenticate
from lib import companies, crypto

SHOW_DEMO_HINT = os.environ.get("SG_SHOW_DEMO_HINT", "1") != "0"


def _brand_logo() -> str:
    if st.context.theme.type == "dark":
        return "assets/logo_login.svg"
    return "assets/logo_login_light.svg"


def _login_page() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        .st-key-login_shell {
            max-width: 1060px;
            margin: 0 auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.space("large")

    with st.container(key="login_shell"):
        form_col, brand_col = st.columns(
            [1, 1.12],
            gap="large",
            vertical_alignment="center",
        )

        with form_col:
            with st.container(border=True):
                st.subheader("Acesse sua conta")
                st.caption("Entre com as credenciais da sua conta para continuar.")

                attempts = int(st.session_state.get("login_attempts", 0))
                lock_until = float(st.session_state.get("login_locked_until", 0))
                locked = time.time() < lock_until

                with st.form("login_form", border=False):
                    email = st.text_input(
                        "E-mail",
                        placeholder="voce@empresa.com",
                        autocomplete="email",
                        key="login_email",
                    )
                    password = st.text_input(
                        "Senha",
                        type="password",
                        placeholder="Sua senha",
                        autocomplete="current-password",
                        key="login_password",
                    )
                    user_id = None
                    # Descobre o user_id pelo email para filtrar empresas.
                    from lib.database import connection as _conn
                    with _conn() as _c:
                        row = _c.execute(
                            "SELECT id FROM users WHERE email_hash = ?",
                            (crypto.hash_email(email),),
                        ).fetchone()
                        user_id = row["id"] if row else None
                        is_superuser = False
                        if user_id is not None:
                            u = _c.execute(
                                "SELECT is_superuser FROM users WHERE id = ?", (user_id,)
                            ).fetchone()
                            is_superuser = bool(u["is_superuser"]) if u else False
                    company_options = companies.list_companies_for_user(
                        user_id, is_superuser=is_superuser
                    ) if user_id is not None else companies.list_companies(active=True)
                    company_labels = {
                        f"{c['name']} ({'Matriz' if c['type'] == 'matriz' else 'Filial'})": c['id']
                        for c in company_options
                    }
                    company_label = st.selectbox(
                        "Empresa",
                        options=list(company_labels) or ["Sem empresa cadastrada"],
                        key="login_company",
                        help="Selecione a matriz ou filial em que deseja operar.",
                    )
                    submitted = st.form_submit_button(
                        "Entrar",
                        type="primary",
                        icon=":material/login:",
                        width="stretch",
                        disabled=locked,
                    )

                if locked:
                    remaining = max(1, int(lock_until - time.time()))
                    st.error(
                        f"Muitas tentativas. Aguarde {remaining}s antes de tentar novamente.",
                        icon=":material/lock_clock:",
                    )
                elif submitted:
                    user = authenticate(email, password)
                    if user:
                        selected_id = company_labels.get(company_label)
                        selected_company = (
                            companies.get_company(selected_id) if selected_id else None
                        )
                        st.session_state["auth_user"] = user
                        st.session_state["auth_company"] = selected_company
                        st.session_state["auth_started_at"] = datetime.now().isoformat()
                        st.session_state["login_attempts"] = 0
                        st.session_state.pop("login_locked_until", None)
                        st.rerun()
                    else:
                        attempts += 1
                        st.session_state["login_attempts"] = attempts
                        if attempts >= 5:
                            st.session_state["login_locked_until"] = time.time() + 30
                            st.session_state["login_attempts"] = 0
                            st.error(
                                "Muitas tentativas. Aguarde 30 segundos e tente novamente.",
                                icon=":material/lock_clock:",
                            )
                        else:
                            st.error(
                                "E-mail ou senha inválidos.",
                                icon=":material/error:",
                            )

                if SHOW_DEMO_HINT:
                    with st.expander("Credenciais de demonstração"):
                        st.caption(
                            "Use no primeiro acesso e altere a senha em Configurações."
                        )
                        st.code(
                            "E-mail: admin@sg.com.br\nSenha: admin123",
                            language=None,
                        )

            st.caption(
                "Ambiente protegido. A sessão expira automaticamente em 12 horas."
            )

        with brand_col:
            st.image(_brand_logo(), width=210, alt="SG Gestão")
            st.title("Gestão clara.\nDecisões melhores.")
            st.caption(
                "Um painel único para acompanhar vendas, estoque, clientes e o "
                "crescimento do seu negócio."
            )
            st.space("small")
            st.markdown(
                ":green-badge[:material/shield: Acesso administrativo] "
                ":blue-badge[:material/insights: Visão em tempo real]"
            )
            st.space("medium")
            st.markdown(
                ":material/check_circle: Receita, pedidos e indicadores em uma visão objetiva.\n\n"
                ":material/check_circle: Produtos, clientes e estoque sempre organizados.\n\n"
                ":material/check_circle: Relatórios prontos para exportar e decidir."
            )
            st.space("large")
            st.caption("SG Gestão · Painel administrativo")


_login_page()
