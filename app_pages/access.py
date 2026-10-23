"""Gestão de usuários, perfis e permissões de acesso."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import acl, companies, ui
from lib.errors import DomainError

actor = acl.require_any("auth.view_user", "auth.view_group")
can_view_users = acl.has_perm(actor, "auth.view_user")
can_view_profiles = acl.has_perm(actor, "auth.view_group")


def _permission_picker(prefix: str, selected) -> set[str]:
    """Matriz compacta de permissões, agrupada por módulo."""
    chosen: set[str] = set()
    selected = set(selected)
    columns = st.columns(2)
    for index, module in enumerate(acl.PERMISSION_MODULES):
        with columns[index % 2]:
            values = st.multiselect(
                module.label,
                options=[permission.codename for permission in module.permissions],
                default=[
                    permission.codename
                    for permission in module.permissions
                    if permission.codename in selected
                ],
                format_func=acl.permission_label,
                help=module.description,
                placeholder="Selecione as permissões",
                key=f"{prefix}_{module.key}",
            )
            chosen.update(values)
    return chosen


@st.dialog("Novo usuário", width="large", icon=":material/person_add:")
def user_dialog(user_id: int | None = None) -> None:
    editing = user_id is not None
    required = "auth.change_user" if editing else "auth.add_user"
    if not acl.can_current(required):
        st.error("Seu perfil não permite esta ação.")
        return

    target = acl.get_user(int(user_id)) if editing else None
    if editing and target is None:
        st.error("Usuário não encontrado.")
        return

    current_actor = acl.current_user()
    actor_is_superuser = bool(current_actor.get("is_superuser"))
    is_self = editing and int(user_id) == int(current_actor["id"])
    target_is_superuser = bool(target and target["is_superuser"])

    if target_is_superuser and not actor_is_superuser:
        st.error("Apenas superusuários podem alterar contas de superusuário.")
        return

    profiles = acl.list_profiles()
    profile_by_name = {profile["name"]: profile for profile in profiles}
    current_profile_names = [
        profile["name"]
        for profile in profiles
        if target and profile["id"] in target["profile_ids"]
    ]
    allow_superuser = actor_is_superuser and not is_self

    with st.form(f"access_user_form_{user_id or 'new'}"):
        name = st.text_input(
            "Nome completo",
            value=target["name"] if target else "",
            placeholder="Ex.: Maria Oliveira",
            autocomplete="name",
        )
        email = st.text_input(
            "E-mail de acesso",
            value=target["email"] if target else "",
            placeholder="maria@empresa.com",
            autocomplete="email",
        )
        active = st.toggle(
            "Conta ativa",
            value=target["active"] if target else True,
            disabled=is_self,
            help=(
                "Você não pode desativar sua própria conta."
                if is_self
                else "Contas inativas não conseguem entrar no painel."
            ),
        )
        is_superuser = st.toggle(
            "Superusuário (acesso total)",
            value=target_is_superuser,
            disabled=not allow_superuser,
            help=(
                "Superusuários ignoram a verificação de permissões."
                if allow_superuser
                else "Somente outro superusuário pode conceder este nível."
            ),
        )

        selected_profile_names = st.multiselect(
            "Perfis de acesso",
            options=list(profile_by_name),
            default=current_profile_names,
            help=(
                "As permissões de cada perfil são somadas. Um usuário pode ter "
                "mais de um perfil."
            ),
            placeholder="Selecione os perfis",
        )

        with st.expander("Permissões adicionais"):
            st.caption(
                "Concessões diretas para esta conta, além das permissões herdadas "
                "dos perfis."
            )
            direct_permissions = _permission_picker(
                f"access_user_direct_{user_id or 'new'}",
                target["direct_permissions"] if target else (),
            )

        if editing:
            password = confirm_password = None
            force_password_change = False
        else:
            st.markdown("**Senha inicial**")
            password = st.text_input(
                "Senha inicial",
                type="password",
                autocomplete="new-password",
                help="Mínimo de 8 caracteres, com pelo menos uma letra e um número.",
            )
            confirm_password = st.text_input(
                "Confirmar senha inicial",
                type="password",
                autocomplete="new-password",
            )
            force_password_change = st.toggle(
                "Exigir troca de senha no próximo acesso",
                value=True,
            )

        if is_self:
            st.caption(
                "Você está editando sua própria conta. Situação e nível de "
                "superusuário não podem ser alterados aqui."
            )

        submitted = st.form_submit_button(
            "Salvar usuário" if editing else "Criar usuário",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if not submitted:
        return

    profile_ids = [
        profile_by_name[name]["id"]
        for name in selected_profile_names
        if name in profile_by_name
    ]
    try:
        if editing:
            acl.update_user(
                user_id=int(user_id),
                name=name,
                email=email,
                profile_ids=profile_ids,
                direct_permissions=direct_permissions,
                active=active,
                is_superuser=is_superuser,
                actor_id=int(current_actor["id"]),
            )
        else:
            if password != confirm_password:
                raise DomainError("A confirmação não corresponde à senha inicial.")
            acl.create_user(
                name=name,
                email=email,
                password=password or "",
                profile_ids=profile_ids,
                direct_permissions=direct_permissions,
                active=active,
                is_superuser=is_superuser,
                force_password_change=force_password_change,
                actor_id=int(current_actor["id"]),
            )
    except DomainError as exc:
        st.error(str(exc))
    else:
        ui.set_flash(
            "Usuário atualizado com sucesso."
            if editing
            else "Usuário criado com sucesso."
        )
        st.rerun()


@st.dialog("Redefinir senha", icon=":material/key:")
def reset_password_dialog(user_id: int, user_name: str) -> None:
    if not acl.can_current("auth.change_user"):
        st.error("Seu perfil não permite redefinir senhas.")
        return

    target = acl.get_user(user_id)
    current_actor = acl.current_user()
    if target is None:
        st.error("Usuário não encontrado.")
        return
    if target["is_superuser"] and not current_actor.get("is_superuser"):
        st.error("Apenas superusuários podem redefinir a senha de um superusuário.")
        return
    if user_id == int(current_actor["id"]):
        st.error("Use Configurações para alterar sua própria senha.")
        return

    st.caption(f"Defina uma nova senha para **{user_name}**.")
    with st.form(f"access_reset_password_{user_id}"):
        password = st.text_input(
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
        force_change = st.toggle(
            "Exigir troca no próximo acesso",
            value=True,
        )
        submitted = st.form_submit_button(
            "Redefinir senha",
            type="primary",
            icon=":material/key:",
            width="stretch",
        )

    if submitted:
        if password != confirm_password:
            st.error("A confirmação não corresponde à nova senha.")
            return
        try:
            acl.reset_password(
                user_id,
                password or "",
                force_change,
                actor_id=int(current_actor["id"]),
            )
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash(f"Senha de {user_name} redefinida com sucesso.")
            st.rerun()


@st.dialog("Excluir usuário", icon=":material/person_remove:")
def delete_user_dialog(user_id: int, user_name: str, is_superuser: bool) -> None:
    if not acl.can_current("auth.delete_user"):
        st.error("Seu perfil não permite excluir usuários.")
        return

    st.write(f"Tem certeza de que deseja excluir a conta de **{user_name}**?")
    st.warning(
        "A exclusão é permanente e encerra o acesso desta pessoa ao painel.",
        icon=":material/warning:",
    )
    if is_superuser:
        st.warning(
            "Esta é uma conta de superusuário. O sistema exige que outro "
            "superusuário ativo permaneça.",
            icon=":material/verified_user:",
        )
    if st.button(
        "Excluir usuário",
        type="primary",
        icon=":material/delete:",
        width="stretch",
        key=f"confirm_delete_user_{user_id}",
    ):
        try:
            acl.delete_user(user_id, actor_id=int(acl.current_user()["id"]))
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash(f"Usuário {user_name} excluído com sucesso.")
            st.rerun()


@st.dialog("Novo perfil", width="large", icon=":material/add_moderator:")
def profile_dialog(profile_id: int | None = None) -> None:
    editing = profile_id is not None
    required = "auth.change_group" if editing else "auth.add_group"
    if not acl.can_current(required):
        st.error("Seu perfil não permite esta ação.")
        return

    target = acl.get_profile(int(profile_id)) if editing else None
    if editing and target is None:
        st.error("Perfil não encontrado.")
        return
    if target and target["is_system"]:
        st.info(
            "O perfil Administradores é protegido e tem acesso total por definição.",
            icon=":material/lock:",
        )
        return

    with st.form(f"access_profile_form_{profile_id or 'new'}"):
        name = st.text_input(
            "Nome do perfil",
            value=target["name"] if target else "",
            placeholder="Ex.: Financeiro",
        )
        description = st.text_area(
            "Descrição (opcional)",
            value=target["description"] if target else "",
            placeholder="Explique para que serve este perfil.",
            height=80,
        )
        st.caption(
            "Selecione as permissões do perfil. As permissões são somadas às "
            "concessões diretas de cada usuário."
        )
        selected_permissions = _permission_picker(
            f"access_profile_perms_{profile_id or 'new'}",
            target["permissions"] if target else (),
        )
        submitted = st.form_submit_button(
            "Salvar perfil" if editing else "Criar perfil",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if not submitted:
        return

    try:
        acl.save_profile(
            int(profile_id) if editing else None,
            name,
            description,
            selected_permissions,
            actor_id=int(acl.current_user()["id"]),
        )
    except DomainError as exc:
        st.error(str(exc))
    else:
        ui.set_flash(
            "Perfil atualizado com sucesso."
            if editing
            else "Perfil criado com sucesso."
        )
        st.rerun()


@st.dialog("Excluir perfil", icon=":material/delete:")
def delete_profile_dialog(profile_id: int, profile_name: str) -> None:
    if not acl.can_current("auth.delete_group"):
        st.error("Seu perfil não permite excluir perfis.")
        return

    st.write(f"Tem certeza de que deseja excluir o perfil **{profile_name}**?")
    st.warning(
        "A exclusão é permanente. Perfis atribuídos a usuários não podem ser "
        "excluídos.",
        icon=":material/warning:",
    )
    if st.button(
        "Excluir perfil",
        type="primary",
        icon=":material/delete:",
        width="stretch",
        key=f"confirm_delete_profile_{profile_id}",
    ):
        try:
            acl.delete_profile(profile_id, actor_id=int(acl.current_user()["id"]))
        except DomainError as exc:
            st.error(str(exc))
        else:
            ui.set_flash(f"Perfil {profile_name} excluído com sucesso.")
            st.rerun()


def _users_tab() -> None:
    st.caption(
        "Contas que podem entrar no painel. As permissões efetivas vêm dos "
        "perfis e das concessões diretas."
    )
    with st.container(horizontal=True, horizontal_alignment="right"):
        if acl.can_current("auth.add_user"):
            if st.button(
                "Novo usuário",
                type="primary",
                icon=":material/person_add:",
                key="access_new_user_button",
            ):
                user_dialog()

    users = acl.list_users()
    total = len(users)
    active_count = sum(1 for user in users if user["active"])
    superuser_count = sum(1 for user in users if user["is_superuser"])
    pending_password = sum(
        1 for user in users if user["must_change_password"]
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric(
        "Usuários",
        ui.number_br(total),
        border=True,
        icon=":material/group:",
        help="Todas as contas cadastradas, incluindo inativas.",
    )
    metric_cols[1].metric(
        "Contas ativas",
        ui.number_br(active_count),
        border=True,
        icon=":material/how_to_reg:",
        help="Contas que podem entrar no painel.",
    )
    metric_cols[2].metric(
        "Superusuários",
        ui.number_br(superuser_count),
        border=True,
        icon=":material/verified_user:",
        help="Contas com acesso total, sem verificação de permissões.",
    )
    metric_cols[3].metric(
        "Senha inicial",
        ui.number_br(pending_password),
        border=True,
        icon=":material/key:",
        help="Contas que ainda precisam trocar a senha no próximo acesso.",
    )

    st.space("small")
    if not users:
        ui.empty_state(
            "Nenhum usuário cadastrado",
            "Crie a primeira conta de acesso ao painel.",
        )
        return

    display = pd.DataFrame(
        {
            "nome": [user["name"] for user in users],
            "email": [user["email"] for user in users],
            "perfis": [
                user["profile_names"] or "Sem perfil" for user in users
            ],
            "situacao": [
                ["Ativo"] if user["active"] else ["Inativo"] for user in users
            ],
            "superusuario": [user["is_superuser"] for user in users],
            "ultimo_acesso": [
                ui.datetime_br(user["last_login"]) for user in users
            ],
            "id": [user["id"] for user in users],
        }
    )

    selection_signature = tuple(int(user["id"]) for user in users)
    event = st.dataframe(
        display,
        hide_index=True,
        height=min(420, 38 + len(display) * 36),
        on_select="rerun",
        selection_mode="single-row",
        key=ui.table_key("access_users_table", selection_signature),
        alt="Usuários do painel com e-mail, perfis, situação e último acesso",
        column_config={
            "nome": st.column_config.TextColumn(
                "Usuário", width=180, pinned=True
            ),
            "email": st.column_config.TextColumn("E-mail", width=220),
            "perfis": st.column_config.TextColumn("Perfis", width=200),
            "situacao": st.column_config.MultiselectColumn(
                "Situação",
                options=["Ativo", "Inativo"],
                color=["#047857", "#64748B"],
                width="small",
            ),
            "superusuario": st.column_config.CheckboxColumn(
                "Superusuário", width="small"
            ),
            "ultimo_acesso": st.column_config.TextColumn(
                "Último acesso", width=150
            ),
            "id": None,
        },
    )

    selected_index = ui.selected_row_index(
        event,
        len(users),
        signature=selection_signature,
        state_key="access_users_selected_row",
    )
    if selected_index is None:
        st.caption("Selecione uma linha da tabela para editar a conta.")
        return

    selected = users[selected_index]
    is_self = selected["id"] == actor["id"]
    target_is_superuser = selected["is_superuser"]
    can_touch_target = bool(actor.get("is_superuser")) or not target_is_superuser
    can_change = acl.has_perm(actor, "auth.change_user") and can_touch_target
    can_delete = acl.has_perm(actor, "auth.delete_user") and can_touch_target

    st.space("small")
    with st.container(border=True):
        info_col, actions_col = st.columns([1.4, 2.8], vertical_alignment="center")
        with info_col:
            st.markdown(f"**{selected['name']}**")
            st.caption(
                f"{selected['email']} · {selected['profile_names'] or 'Sem perfil'}"
            )
            if selected["active"]:
                st.badge("Ativo", color="green", icon=":material/check_circle:")
            else:
                st.badge("Inativo", color="gray", icon=":material/pause_circle:")
            if target_is_superuser:
                st.badge(
                    "Superusuário",
                    color="violet",
                    icon=":material/verified_user:",
                )
            if selected["must_change_password"]:
                st.badge(
                    "Troca de senha pendente",
                    color="orange",
                    icon=":material/key:",
                )
        with actions_col:
            if not can_change and not can_delete:
                st.caption(
                    "Seu perfil permite apenas consultar esta conta."
                    if can_touch_target
                    else "Somente superusuários podem alterar esta conta."
                )
            else:
                with st.container(horizontal=True, horizontal_alignment="right"):
                    if can_change:
                        if st.button(
                            "Editar",
                            icon=":material/edit:",
                            key=f"access_edit_user_{selected['id']}",
                        ):
                            user_dialog(selected["id"])
                        if not is_self:
                            if st.button(
                                "Redefinir senha",
                                icon=":material/key:",
                                key=f"access_reset_user_{selected['id']}",
                            ):
                                reset_password_dialog(
                                    selected["id"], selected["name"]
                                )
                            active_label = (
                                "Desativar" if selected["active"] else "Ativar"
                            )
                            if st.button(
                                active_label,
                                icon=":material/pause_circle:"
                                if selected["active"]
                                else ":material/play_circle:",
                                key=f"access_toggle_user_{selected['id']}",
                            ):
                                try:
                                    acl.set_user_active(
                                        selected["id"],
                                        not selected["active"],
                                        actor_id=int(actor["id"]),
                                    )
                                except DomainError as exc:
                                    st.error(str(exc))
                                else:
                                    ui.set_flash(
                                        f"Conta {'desativada' if selected['active'] else 'ativada'} com sucesso."
                                    )
                                    st.rerun()
                    if can_delete and not is_self:
                        if st.button(
                            "Excluir",
                            icon=":material/delete:",
                            key=f"access_delete_user_{selected['id']}",
                        ):
                            delete_user_dialog(
                                selected["id"],
                                selected["name"],
                                target_is_superuser,
                            )


def _profiles_tab() -> None:
    st.caption(
        "Perfis reúnem permissões e podem ser atribuídos a vários usuários, "
        "como os grupos do Django."
    )
    with st.container(horizontal=True, horizontal_alignment="right"):
        if acl.can_current("auth.add_group"):
            if st.button(
                "Novo perfil",
                type="primary",
                icon=":material/add_moderator:",
                key="access_new_profile_button",
            ):
                profile_dialog()

    profiles = acl.list_profiles()
    total = len(profiles)
    in_use = sum(1 for profile in profiles if profile["members"] > 0)
    system_count = sum(1 for profile in profiles if profile["is_system"])

    metric_cols = st.columns(3)
    metric_cols[0].metric(
        "Perfis",
        ui.number_br(total),
        border=True,
        icon=":material/shield_person:",
        help="Perfis disponíveis para atribuição.",
    )
    metric_cols[1].metric(
        "Perfis em uso",
        ui.number_br(in_use),
        border=True,
        icon=":material/group:",
        help="Perfis atribuídos a pelo menos um usuário.",
    )
    metric_cols[2].metric(
        "Permissões disponíveis",
        ui.number_br(len(acl.ALL_PERMISSIONS)),
        border=True,
        icon=":material/key:",
        help="Permissões declaradas pelo sistema.",
    )

    st.space("small")
    if not profiles:
        ui.empty_state(
            "Nenhum perfil cadastrado",
            "Crie um perfil para agrupar permissões de acesso.",
        )
        return

    display = pd.DataFrame(
        {
            "perfil": [profile["name"] for profile in profiles],
            "descricao": [
                profile["description"] or "—" for profile in profiles
            ],
            "membros": [profile["members"] for profile in profiles],
            "permissoes": [
                profile["permission_count"] for profile in profiles
            ],
            "tipo": [
                ["Sistema"] if profile["is_system"] else ["Personalizado"]
                for profile in profiles
            ],
            "id": [profile["id"] for profile in profiles],
        }
    )

    selection_signature = tuple(int(profile["id"]) for profile in profiles)
    event = st.dataframe(
        display,
        hide_index=True,
        height=min(420, 38 + len(display) * 36),
        on_select="rerun",
        selection_mode="single-row",
        key=ui.table_key("access_profiles_table", selection_signature),
        alt="Perfis de acesso com descrição, membros e quantidade de permissões",
        column_config={
            "perfil": st.column_config.TextColumn(
                "Perfil", width=170, pinned=True
            ),
            "descricao": st.column_config.TextColumn(
                "Descrição", width=380
            ),
            "membros": st.column_config.NumberColumn(
                "Usuários", format="%d", width=90
            ),
            "permissoes": st.column_config.NumberColumn(
                "Permissões", format="%d", width=90
            ),
            "tipo": st.column_config.MultiselectColumn(
                "Tipo",
                options=["Sistema", "Personalizado"],
                color=["#7C3AED", "#0F766E"],
                width="medium",
            ),
            "id": None,
        },
    )

    selected_index = ui.selected_row_index(
        event,
        len(profiles),
        signature=selection_signature,
        state_key="access_profiles_selected_row",
    )
    if selected_index is None:
        st.caption("Selecione uma linha da tabela para editar o perfil.")
        return

    selected = profiles[selected_index]
    can_change = acl.has_perm(actor, "auth.change_group")
    can_delete = acl.has_perm(actor, "auth.delete_group")
    is_system = selected["is_system"]

    st.space("small")
    with st.container(border=True):
        info_col, actions_col = st.columns([1.5, 2.7], vertical_alignment="center")
        with info_col:
            st.markdown(f"**{selected['name']}**")
            st.caption(selected["description"] or "Sem descrição.")
            st.badge(
                "Sistema" if is_system else "Personalizado",
                color="violet" if is_system else "primary",
                icon=":material/lock:" if is_system else ":material/shield_person:",
            )
            st.badge(
                f"{selected['members']} usuário(s)",
                color="gray",
                icon=":material/group:",
            )
            st.badge(
                f"{selected['permission_count']} permissões",
                color="blue",
                icon=":material/key:",
            )
        with actions_col:
            if is_system:
                st.caption(
                    "Perfil protegido: tem acesso total e não pode ser editado "
                    "nem excluído."
                )
            elif not can_change and not can_delete:
                st.caption("Seu perfil permite apenas consultar os perfis.")
            else:
                with st.container(horizontal=True, horizontal_alignment="right"):
                    if can_change:
                        if st.button(
                            "Editar",
                            icon=":material/edit:",
                            key=f"access_edit_profile_{selected['id']}",
                        ):
                            profile_dialog(selected["id"])
                    if can_delete:
                        has_members = selected["members"] > 0
                        if st.button(
                            "Excluir",
                            icon=":material/delete:",
                            key=f"access_delete_profile_{selected['id']}",
                            disabled=has_members,
                            help=(
                                "Remova o perfil dos usuários antes de excluir."
                                if has_members
                                else None
                            ),
                        ):
                            delete_profile_dialog(
                                selected["id"], selected["name"]
                            )


ui.page_header(
    "Acessos",
    "Gerencie contas, perfis e permissões com o mesmo modelo de grupos do Django.",
    icon=":material/admin_panel_settings:",
)

st.caption(
    "As permissões são declaradas por recurso e ação. Perfis (grupos) reúnem "
    "permissões, usuários podem ter vários perfis e receber concessões diretas, "
    "e superusuários têm acesso total."
)

def _companies_tab() -> None:
    st.caption(
        "Vincule empresas (matriz ou filial) aos usuários. Apenas empresas "
        "vinculadas aparecem no login."
    )
    users = acl.list_users()
    companies_list = companies.list_companies(active=True)
    if not users or not companies_list:
        ui.empty_state(
            "Sem dados",
            "Cadastre usuários e empresas antes de vincular.",
        )
        return

    user_options = {f"{u['name']} ({u['email']})": u["id"] for u in users}
    selected_user_label = st.selectbox(
        "Usuário",
        options=list(user_options),
        key="access_company_user",
    )
    selected_user_id = user_options[selected_user_label]

    linked = companies.list_user_companies(selected_user_id)
    linked_ids = {c["company_id"] for c in linked}

    st.space("small")
    st.markdown("**Empresas vinculadas**")
    if linked:
        for item in linked:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f"{'★ ' if item['is_default'] else ''}{item['company_name']} "
                    f"({'Matriz' if item['company_type'] == 'matriz' else 'Filial'})"
                )
            with col2:
                if st.button(
                    "Remover",
                    icon=":material/remove:",
                    key=f"remove_company_{selected_user_id}_{item['company_id']}",
                ):
                    companies.remove_company(selected_user_id, item["company_id"])
                    ui.set_flash("Vínculo removido.")
                    st.rerun()
    else:
        st.caption("Nenhuma empresa vinculada.")

    st.space("small")
    st.markdown("**Vincular nova empresa**")
    available = [c for c in companies_list if c["id"] not in linked_ids]
    if not available:
        st.caption("Todas as empresas já estão vinculadas a este usuário.")
        return
    avail_options = {c["name"]: c["id"] for c in available}
    new_label = st.selectbox("Empresa", options=list(avail_options), key="access_new_company")
    is_default = st.checkbox("Definir como padrão", key="access_company_default")
    if st.button("Vincular", type="primary", icon=":material/add:", key="access_assign_company"):
        companies.assign_company(
            selected_user_id, avail_options[new_label], is_default=is_default
        )
        ui.set_flash("Empresa vinculada ao usuário.")
        st.rerun()


tab_labels: list[str] = []
if can_view_users:
    tab_labels.append("Usuários")
if can_view_profiles:
    tab_labels.append("Perfis")
if can_view_users:
    tab_labels.append("Empresas")
tabs = st.tabs(tab_labels)

tab_index = 0
if can_view_users:
    with tabs[tab_index]:
        _users_tab()
    tab_index += 1
if can_view_profiles:
    with tabs[tab_index]:
        _profiles_tab()
    tab_index += 1
if can_view_users:
    with tabs[tab_index]:
        _companies_tab()
