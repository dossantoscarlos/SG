"""SG Gestão — entrada do painel administrativo."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import streamlit as st

from lib import acl, branding, theme_toggle, ui
from lib.database import init_database

_BRANDING = branding.load_branding()

st.set_page_config(
    page_title=_BRANDING["company_name"],
    page_icon=_BRANDING["icon_path"],
    layout="wide",
    initial_sidebar_state="auto",
)

SESSION_HOURS = 12


@st.cache_resource(show_spinner=False)
def _boot_database() -> bool:
    seed_demo = os.environ.get("SG_SEED_DEMO", "1") != "0"
    init_database(seed_demo=seed_demo)
    return True


_boot_database()


@st.fragment(run_every="1s")
def _sync_theme() -> None:
    """Atualiza logo e gráficos depois da troca de aparência.

    O seletor de tema do Streamlit altera o CSS no navegador sem reexecutar o
    script. Este fragmento observa a mudança e pede um rerun completo, para que
    ``st.context.theme.type`` volte a casar com as cores renderizadas no servidor.
    """
    st.empty()
    # `_is_dark()` trata um tipo ainda desconhecido como claro; guardamos o
    # mesmo fallback para detectar a correção no próximo ciclo do fragmento.
    theme = st.context.theme.type or "light"
    previous = st.session_state.get("_theme_type")
    if previous is None:
        st.session_state["_theme_type"] = theme
    elif theme != previous:
        st.session_state["_theme_type"] = theme
        st.rerun(scope="app")


_sync_theme()


def _clear_session() -> None:
    st.session_state.clear()


def _current_user() -> dict | None:
    user = st.session_state.get("auth_user")
    started = st.session_state.get("auth_started_at")
    if not user or not started:
        return None
    try:
        started_at = datetime.fromisoformat(started)
    except ValueError:
        _clear_session()
        return None
    if datetime.now() - started_at > timedelta(hours=SESSION_HOURS):
        _clear_session()
        return None

    # Recarrega perfis e permissões a cada execução para que alterações feitas
    # por um administrador valham sem exigir um novo login.
    access = acl.get_access(int(user["id"]))
    if access is None or not access["active"]:
        _clear_session()
        return None
    refreshed = {**user, **access}
    st.session_state["auth_user"] = refreshed
    return refreshed


def _logout() -> None:
    _clear_session()
    st.rerun()


user = _current_user()
if not user:
    login_page = st.Page(
        "app_pages/login.py",
        title="Entrar",
        icon=":material/login:",
        default=True,
    )
    st.navigation([login_page], position="hidden").run()
    st.stop()

# Valida a empresa selecionada na sessão.
from lib import companies as _companies
_company = st.session_state.get("auth_company")
if _company is not None:
    if not _companies.user_has_company(
        int(user["id"]), int(_company["id"]), is_superuser=bool(user.get("is_superuser"))
    ):
        st.session_state.pop("auth_company", None)

st.logo(
    _BRANDING["icon_path"],
    icon_image=_BRANDING["icon_path"],
    size="large",
)

st.markdown(
    """
    <style>
      [data-testid="stSidebar"] [data-testid="stNavSectionHeader"] {
        background-color: rgba(255, 255, 255, 0.10);
        border-radius: 8px;
        padding: 0.35rem 0.6rem;
        margin: 0.6rem 0 0.25rem 0;
        border-left: 3px solid var(--primary-color, #4F46E5);
        transition: background-color 0.15s ease;
      }
      [data-testid="stSidebar"] [data-testid="stNavSectionHeader"]:hover {
        background-color: rgba(255, 255, 255, 0.18);
      }
      [data-testid="stSidebar"] [data-testid="stNavSectionHeader"] span {
        color: var(--text-color, #E6EAF2);
        font-weight: 600;
      }
      [data-testid="stSidebar"] [data-testid="stNavSectionHeader"] [data-testid="stMarkdownContainer"] {
        margin: 0;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

section_specs: dict[str, list[tuple[str, str, str]]] = {
    "": [],
    ":material/local_shipping: **Operação**": [],
    ":material/inventory_2: **Cadastros**": [],
    ":material/analytics: **Análise**": [],
    ":material/admin_panel_settings: **Administração**": [],
    ":material/palette: **Identidade**": [],
}
if acl.has_perm(user, "dashboard.view_dashboard"):
    section_specs[""].append(
        ("app_pages/dashboard.py", "Visão geral", ":material/space_dashboard:")
    )
if acl.has_perm(user, "orders.view_order"):
    section_specs[":material/local_shipping: **Operação**"].append(
        ("app_pages/orders.py", "Pedidos", ":material/receipt_long:")
    )
if acl.has_perm(user, "logistics.view_shipment"):
    section_specs[":material/local_shipping: **Operação**"].append(
        ("app_pages/logistics.py", "Logística", ":material/local_shipping:")
    )
    section_specs[":material/local_shipping: **Operação**"].append(
        ("app_pages/branches.py", "Filiais", ":material/storefront:")
    )
if acl.has_perm(user, "products.view_product"):
    section_specs[":material/inventory_2: **Cadastros**"].append(
        ("app_pages/products.py", "Produtos", ":material/inventory_2:")
    )
if acl.has_perm(user, "customers.view_customer"):
    section_specs[":material/inventory_2: **Cadastros**"].append(
        ("app_pages/customers.py", "Clientes", ":material/group:")
    )
if acl.has_perm(user, "products.view_product"):
    section_specs[":material/inventory_2: **Cadastros**"].append(
        ("app_pages/companies.py", "Empresas", ":material/apartment:")
    )
if acl.has_perm(user, "logistics.view_shipment"):
    section_specs[":material/inventory_2: **Cadastros**"].append(
        ("app_pages/suppliers.py", "Fornecedores", ":material/local_shipping:")
    )
if acl.has_perm(user, "reports.view_report"):
    section_specs[":material/analytics: **Análise**"].append(
        ("app_pages/reports.py", "Relatórios", ":material/analytics:")
    )
if acl.has_any(user, "auth.view_user", "auth.view_group"):
    section_specs[":material/admin_panel_settings: **Administração**"].append(
        ("app_pages/access.py", "Acessos", ":material/admin_panel_settings:")
    )
section_specs[":material/admin_panel_settings: **Administração**"].append(
    ("app_pages/settings.py", "Configurações", ":material/settings:")
)
section_specs[":material/palette: **Identidade**"].append(
    ("app_pages/branding.py", "Tema e identidade", ":material/palette:")
)

default_path = next(
    (spec[0] for specs in section_specs.values() for spec in specs), None
)
navigation: dict[str, list[st.Page]] = {}
for section, specs in section_specs.items():
    if not specs:
        continue
    navigation[section] = [
        st.Page(path, title=title, icon=icon, default=(path == default_path))
        for path, title, icon in specs
    ]
page = st.navigation(navigation, position="sidebar")

with st.sidebar:
    st.space("medium")
    st.caption("Sua conta")
    st.markdown(f"**{user['name']}**")
    st.caption(user["email"])
    profiles = user.get("profiles") or []
    if profiles:
        for profile in profiles:
            st.badge(
                profile["name"],
                color="primary",
                icon=":material/shield_person:",
            )
    else:
        st.badge("Sem perfil", color="gray", icon=":material/person:")
    if user.get("is_superuser"):
        st.badge(
            "Superusuário",
            color="violet",
            icon=":material/verified_user:",
        )
    st.space("small")
    theme_toggle.theme_toggle_button()
    if st.button(
        "Sair",
        icon=":material/logout:",
        type="tertiary",
        width="stretch",
        key="sidebar_logout",
    ):
        _logout()
    st.space("small")
    st.caption(f"{_BRANDING['company_name']} · v1.5")

ui.show_flash()
page.run()
