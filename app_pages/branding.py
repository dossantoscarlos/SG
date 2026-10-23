"""Personalização de tema, cores e identidade da empresa."""

from __future__ import annotations

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
    "Personalize o nome da empresa, o ícone e as cores primária e secundária "
    "usadas no painel.",
    icon=":material/palette:",
)

# Aplica as cores salvas como variáveis CSS para efeito imediato.
st.markdown(
    f"""
    <style>
      :root {{
        --brand-primary: {current['primary_color']};
        --brand-secondary: {current['secondary_color']};
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Identidade da empresa -------------------------------------------------
with st.container(border=True):
    st.subheader("Identidade da empresa")
    st.caption("Nome exibido no painel, na tela de login e na barra lateral.")

    with st.form("branding_identity_form"):
        company_name = st.text_input(
            "Nome da empresa",
            value=current["company_name"],
            placeholder="SG Gestão",
            autocomplete="organization",
            help="Aparece no título da aba, na tela de login e no rodapé da barra lateral.",
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

st.space("medium")

# --- Cores do tema ---------------------------------------------------------
with st.container(border=True):
    st.subheader("Cores do tema")
    st.caption(
        "Primária e secundária. A primária atualiza a cor de destaque do painel; "
        "a secundária, o fundo secundário. Para o tema nativo do Streamlit "
        "aplicar por completo, reinicie o servidor após salvar."
    )

    with st.form("branding_colors_form"):
        primary = st.color_picker(
            "Cor primária", value=current["primary_color"]
        )
        secondary = st.color_picker(
            "Cor secundária", value=current["secondary_color"]
        )

        st.markdown("**Pré-visualização**")
        preview_cols = st.columns(2, gap="large")
        for col, label, color in zip(
            preview_cols,
            ("Primária", "Secundária"),
            (primary, secondary),
        ):
            with col:
                text_color = branding.contrast_color(color)
                st.markdown(
                    f"""
                    <div style="background:{color};height:56px;border-radius:10px;
                                display:flex;align-items:center;justify-content:center;
                                color:{text_color};font-weight:600;
                                border:1px solid rgba(0,0,0,0.12);
                                box-shadow:0 1px 2px rgba(0,0,0,0.08);">
                        {label}
                    </div>
                    <div style="text-align:center;margin-top:0.35rem;font-size:0.85rem;
                                color:var(--text-color,#64748B);">
                        {color}
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
            }
        )
        try:
            branding.update_config_theme(primary, secondary)
        except Exception as exc:  # pragma: no cover - defensivo
            st.warning(f"Não foi possível atualizar o config.toml: {exc}")
        ui.set_flash(
            "Cores salvas. Reinicie o servidor para aplicar o tema nativo do "
            "Streamlit por completo."
        )
        st.rerun()

st.space("small")

with st.container(border=True):
    st.subheader("Resumo da identidade")
    summary_cols = st.columns(2, gap="large")
    with summary_cols[0]:
        st.markdown(f"- **Empresa:** {current['company_name']}")
        st.markdown(f"- **Ícone:** `{current['icon_path']}`")
    with summary_cols[1]:
        st.markdown(f"- **Primária:** `{current['primary_color']}`")
        st.markdown(f"- **Secundária:** `{current['secondary_color']}`")

st.space("small")
st.caption(
    "As cores são persistidas em `data/branding.json` e no "
    "`.streamlit/config.toml`. O nome e o ícone passam a ser usados no painel "
    "após o próximo carregamento da aplicação."
)
