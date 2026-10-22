"""Personalização de tema, cores e identidade da empresa."""

from __future__ import annotations

import shutil
from pathlib import Path

import streamlit as st

from lib import acl, branding, ui
from lib.errors import DomainError

user = st.session_state.get("auth_user")
if not user:
    st.error("Sessão expirada. Entre novamente para acessar a personalização.")
    st.stop()

if not acl.has_any(user, "auth.view_user", "auth.view_group"):
    st.error("Você não tem permissão para personalizar o tema e a identidade.")
    st.stop()

current = branding.load_branding()

ui.page_header(
    "Tema e identidade",
    "Personalize o nome da empresa, o ícone e as cores primária, secundária e "
    "terciária usadas no painel.",
    icon=":material/palette:",
)

# Aplica as cores salvas como variáveis CSS para efeito imediato.
st.markdown(
    f"""
    <style>
      :root {{
        --brand-primary: {current['primary_color']};
        --brand-secondary: {current['secondary_color']};
        --brand-tertiary: {current['tertiary_color']};
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(border=True):
    st.subheader("Identidade da empresa")
    st.caption("Nome exibido no painel, na tela de login e na barra lateral.")

    with st.form("branding_identity_form"):
        company_name = st.text_input(
            "Nome da empresa",
            value=current["company_name"],
            placeholder="SG Gestão",
        )
        icon_file = st.file_uploader(
            "Ícone / logo (PNG ou SVG)",
            type=["png", "svg", "ico"],
            help="Substitui o ícone usado na aba do navegador e na barra lateral.",
        )
        identity_saved = st.form_submit_button(
            "Salvar identidade",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if identity_saved:
        updates = {"company_name": company_name.strip() or current["company_name"]}
        if icon_file is not None:
            target = Path("assets") / f"brand_icon{Path(icon_file.name).suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(icon_file.getvalue())
            updates["icon_path"] = str(target).replace("\\", "/")
        branding.save_branding(updates)
        ui.set_flash("Identidade da empresa atualizada.")
        st.rerun()

    st.caption(f"Ícone atual: `{current['icon_path']}`")

with st.container(border=True):
    st.subheader("Cores do tema")
    st.caption(
        "Primária, secundária e terciária. A primária e a secundária também "
        "atualizam o `.streamlit/config.toml`; para o tema nativo do "
        "Streamlit aplicar por completo, reinicie o servidor após salvar."
    )

    with st.form("branding_colors_form"):
        primary = st.color_picker(
            "Cor primária", value=current["primary_color"]
        )
        secondary = st.color_picker(
            "Cor secundária", value=current["secondary_color"]
        )
        tertiary = st.color_picker(
            "Cor terciária", value=current["tertiary_color"]
        )

        st.markdown("**Pré-visualização**")
        preview_cols = st.columns(3)
        for col, label, color in zip(
            preview_cols,
            ("Primária", "Secundária", "Terciária"),
            (primary, secondary, tertiary),
        ):
            with col:
                st.markdown(
                    f"""
                    <div style="background:{color};height:48px;border-radius:8px;
                                display:flex;align-items:center;justify-content:center;
                                color:#fff;font-weight:600;border:1px solid rgba(0,0,0,0.1);">
                        {label}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        colors_saved = st.form_submit_button(
            "Salvar cores",
            type="primary",
            icon=":material/palette:",
            width="stretch",
        )

    if colors_saved:
        branding.save_branding(
            {
                "primary_color": primary,
                "secondary_color": secondary,
                "tertiary_color": tertiary,
            }
        )
        try:
            branding.update_config_theme(primary, secondary, tertiary)
        except Exception as exc:  # pragma: no cover - defensivo
            st.warning(f"Não foi possível atualizar o config.toml: {exc}")
        ui.set_flash(
            "Cores salvas. Reinicie o servidor para aplicar o tema nativo do "
            "Streamlit por completo."
        )
        st.rerun()

with st.container(border=True):
    st.subheader("Resumo da identidade")
    st.markdown(f"- **Empresa:** {current['company_name']}")
    st.markdown(f"- **Ícone:** `{current['icon_path']}`")
    st.markdown(f"- **Primária:** `{current['primary_color']}`")
    st.markdown(f"- **Secundária:** `{current['secondary_color']}`")
    st.markdown(f"- **Terciária:** `{current['tertiary_color']}`")

st.space("small")
st.caption(
    "As cores são persistidas em `data/branding.json` e no "
    "`.streamlit/config.toml`. O nome e o ícone passam a ser usados no painel "
    "após o próximo carregamento da aplicação."
)
