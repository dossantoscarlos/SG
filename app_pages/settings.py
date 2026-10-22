"""Configurações da conta e informações do sistema."""

from __future__ import annotations

import platform
from datetime import datetime

import streamlit as st

from lib import acl, auth, ui
from lib.database import get_database_path
from lib.errors import DomainError

user = st.session_state.get("auth_user")
if not user:
    st.error("Sessão expirada. Entre novamente para acessar as configurações.")
    st.stop()

fresh_user = auth.get_user(int(user["id"])) or user
must_change = bool(fresh_user.get("must_change_password"))
profiles = user.get("profiles") or []
permissions = set(user.get("permissions") or ())

ui.page_header(
    "Configurações",
    "Atualize seus dados de acesso e consulte as informações do ambiente.",
    icon=":material/settings:",
)

if must_change:
    st.warning(
        "Você ainda está usando a senha inicial de demonstração. Crie uma senha "
        "pessoal para proteger o painel e remover este aviso.",
        title="Proteja sua conta",
        icon=":material/lock_reset:",
    )

profile_col, password_col = st.columns(2, gap="large")

with profile_col:
    with st.container(border=True):
        st.subheader("Seus dados")
        st.caption("Estes dados identificam você no painel e no acesso ao sistema.")
        with st.form("settings_profile_form"):
            name = st.text_input(
                "Nome completo",
                value=fresh_user["name"],
                autocomplete="name",
            )
            email = st.text_input(
                "E-mail de acesso",
                value=fresh_user["email"],
                autocomplete="email",
            )
            st.text_input(
                "Perfis de acesso",
                value=", ".join(profile["name"] for profile in profiles)
                or "Sem perfil",
                disabled=True,
                help=(
                    "Os perfis e as permissões são definidos por um administrador "
                    "na página Acessos."
                ),
            )
            saved = st.form_submit_button(
                "Salvar perfil",
                type="primary",
                icon=":material/save:",
                width="stretch",
            )

        if saved:
            try:
                updated = auth.update_profile(int(user["id"]), name, email)
            except DomainError as exc:
                st.error(str(exc))
            else:
                st.session_state["auth_user"] = {
                    **st.session_state.get("auth_user", user),
                    **updated,
                }
                ui.set_flash("Perfil atualizado com sucesso.")
                st.rerun()

with password_col:
    with st.container(border=True):
        st.subheader("Senha de acesso")
        st.caption(
            "Use pelo menos 8 caracteres, incluindo letras e números. "
            "A senha é armazenada com hash scrypt."
        )
        with st.form("settings_password_form"):
            current_password = st.text_input(
                "Senha atual",
                type="password",
                autocomplete="current-password",
            )
            new_password = st.text_input(
                "Nova senha",
                type="password",
                autocomplete="new-password",
                help="Mínimo de 8 caracteres, com pelo menos uma letra e um número.",
            )
            confirm_password = st.text_input(
                "Confirmar nova senha",
                type="password",
                autocomplete="new-password",
            )
            changed = st.form_submit_button(
                "Alterar senha",
                type="primary",
                icon=":material/key:",
                width="stretch",
            )

        if changed:
            if not current_password or not new_password or not confirm_password:
                st.error("Preencha a senha atual e confirme a nova senha.")
            elif new_password != confirm_password:
                st.error("A confirmação não corresponde à nova senha.")
            else:
                try:
                    auth.change_password(
                        int(user["id"]), current_password, new_password
                    )
                except DomainError as exc:
                    st.error(str(exc))
                else:
                    updated = dict(st.session_state.get("auth_user", user))
                    updated["must_change_password"] = False
                    st.session_state["auth_user"] = updated
                    ui.set_flash("Senha alterada com sucesso.")
                    st.rerun()

if must_change:
    st.info(
        "O aviso de senha inicial desaparece automaticamente depois que você "
        "alterar a senha.",
        icon=":material/info:",
    )

st.space("small")
account_col, system_col = st.columns(2, gap="large")

with account_col:
    with st.container(border=True):
        st.subheader("Sua conta")
        last_login = fresh_user.get("last_login")
        started_at = st.session_state.get("auth_started_at")
        try:
            session_start = (
                datetime.fromisoformat(started_at) if started_at else None
            )
        except (TypeError, ValueError):
            session_start = None

        with st.container(border=True):
            st.caption("Último acesso")
            st.markdown(f"**{ui.datetime_br(last_login)}**")
        with st.container(border=True):
            st.caption("Sessão atual iniciada em")
            st.markdown(
                f"**{session_start.strftime('%d/%m/%Y · %H:%M') if session_start else '—'}**"
            )
        with st.container(border=True):
            st.caption("Nível de acesso")
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
        if acl.has_any(user, "auth.view_user", "auth.view_group"):
            st.page_link(
                "app_pages/access.py",
                label="Gerenciar usuários e perfis",
                icon=":material/admin_panel_settings:",
            )
        st.caption(
            "A sessão expira automaticamente após 12 horas. Use o botão Sair na "
            "barra lateral para encerrar agora."
        )

with system_col:
    with st.container(border=True):
        st.subheader("Sobre o sistema")
        st.caption("Informações do ambiente local do SG Gestão.")
        with st.container(border=True):
            st.caption("Aplicação")
            st.markdown("**SG Gestão v1.5**")
            st.caption(f"Streamlit {st.__version__}")
        with st.container(border=True):
            st.caption("Banco de dados")
            st.markdown("**SQLite local**")
            st.caption(str(get_database_path()))
        with st.container(border=True):
            st.caption("Ambiente")
            st.markdown(f"**Python {platform.python_version()}**")
            st.caption(f"{platform.system()} · {platform.release()}")
        st.caption(
            "Os dados ficam armazenados apenas neste computador. Faça backups "
            "periódicos do arquivo do banco de dados."
        )

st.space("small")
with st.expander(
    f"Permissões efetivas ({len(permissions)})",
    icon=":material/key:",
):
    if user.get("is_superuser"):
        st.info(
            "Como superusuário, você tem acesso total ao painel, independentemente "
            "dos perfis atribuídos.",
            icon=":material/verified_user:",
        )
    else:
        st.caption(
            "Permissões herdadas dos perfis e concedidas diretamente à sua conta."
        )

    permission_cols = st.columns(2)
    for index, module in enumerate(acl.PERMISSION_MODULES):
        granted = [
            permission
            for permission in module.permissions
            if permission.codename in permissions
        ]
        with permission_cols[index % 2]:
            st.markdown(f"**{module.label}**")
            if not granted:
                st.caption("Nenhuma permissão.")
                continue
            for permission in granted:
                st.markdown(f":material/check_circle: {permission.label}")
