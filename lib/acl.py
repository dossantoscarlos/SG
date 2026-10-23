"""Controle de acesso baseado em perfis e permissões, no estilo Django.

O modelo segue a mesma ideia do Django:

* cada recurso possui permissões no formato ``app.acao_recurso``;
* perfis (equivalentes aos grupos do Django) reúnem permissões;
* um usuário pode ter vários perfis e permissões concedidas diretamente;
* superusuários ignoram a verificação e têm acesso total.

As permissões são declaradas em código. Os vínculos ficam no SQLite, o que
permite criar e editar perfis sem alterar o esquema do banco.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from lib.database import connection, transaction
from lib.errors import DomainError
from lib.security import hash_password, validate_password_strength
from lib import crypto

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SYSTEM_PROFILE_NAME = "Administradores"


@dataclass(frozen=True)
class Permission:
    codename: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class PermissionModule:
    key: str
    label: str
    description: str
    permissions: tuple[Permission, ...]


@dataclass(frozen=True)
class DefaultProfile:
    name: str
    description: str
    is_system: bool
    permissions: frozenset[str]


PERMISSION_MODULES: tuple[PermissionModule, ...] = (
    PermissionModule(
        key="dashboard",
        label="Visão geral",
        description="Indicadores, gráficos e alertas do painel.",
        permissions=(
            Permission(
                "dashboard.view_dashboard",
                "Acessar a visão geral",
                "Ver indicadores, gráficos, pedidos recentes e alertas de estoque.",
            ),
        ),
    ),
    PermissionModule(
        key="orders",
        label="Pedidos",
        description="Vendas, status e histórico de pedidos.",
        permissions=(
            Permission(
                "orders.view_order",
                "Ver pedidos",
                "Consultar a lista, os detalhes e o histórico de pedidos.",
            ),
            Permission(
                "orders.add_order",
                "Criar pedidos",
                "Registrar novos pedidos e reservar itens do estoque.",
            ),
            Permission(
                "orders.change_order",
                "Alterar status",
                "Atualizar o status dos pedidos.",
            ),
            Permission(
                "orders.delete_order",
                "Excluir pedidos",
                "Remover pedidos e devolver os itens ao estoque.",
            ),
        ),
    ),
    PermissionModule(
        key="logistics",
        label="Logística",
        description="Expedição, transportadoras, rastreio e movimentações de estoque.",
        permissions=(
            Permission(
                "logistics.view_shipment",
                "Ver logística",
                "Consultar a fila de expedição, envios, transportadoras e estoque.",
            ),
            Permission(
                "logistics.change_shipment",
                "Gerenciar envios",
                "Criar e editar envios, informar rastreio e registrar entregas.",
            ),
            Permission(
                "logistics.manage_carrier",
                "Gerenciar transportadoras",
                "Cadastrar, editar e ativar ou desativar transportadoras.",
            ),
            Permission(
                "logistics.adjust_stock",
                "Movimentar estoque",
                "Criar documentos de entrada, saída e transferência de estoque.",
            ),
            Permission(
                "logistics.receive_stock",
                "Receber estoque",
                "Confirmar o recebimento de itens em trânsito e tratar divergências.",
            ),
            Permission(
                "logistics.reverse_stock",
                "Estornar movimentações",
                "Estornar documentos manuais sem apagar o histórico.",
            ),
        ),
    ),
    PermissionModule(
        key="products",
        label="Produtos",
        description="Catálogo, preços, estoque e disponibilidade.",
        permissions=(
            Permission(
                "products.view_product",
                "Ver produtos",
                "Consultar o catálogo, os preços e o estoque.",
            ),
            Permission(
                "products.add_product",
                "Cadastrar produtos",
                "Criar novos itens no catálogo.",
            ),
            Permission(
                "products.change_product",
                "Editar produtos",
                "Alterar dados, preços, estoque e ativar ou desativar itens.",
            ),
            Permission(
                "products.delete_product",
                "Excluir produtos",
                "Remover produtos sem pedidos vinculados.",
            ),
        ),
    ),
    PermissionModule(
        key="customers",
        label="Clientes",
        description="Cadastro, contatos e histórico de compras.",
        permissions=(
            Permission(
                "customers.view_customer",
                "Ver clientes",
                "Consultar a lista, a ficha e o histórico de clientes.",
            ),
            Permission(
                "customers.add_customer",
                "Cadastrar clientes",
                "Criar novos cadastros de clientes.",
            ),
            Permission(
                "customers.change_customer",
                "Editar clientes",
                "Alterar dados, observações e situação dos clientes.",
            ),
            Permission(
                "customers.delete_customer",
                "Excluir clientes",
                "Remover clientes sem pedidos vinculados.",
            ),
        ),
    ),
    PermissionModule(
        key="reports",
        label="Relatórios",
        description="Análises por período e exportação de arquivos.",
        permissions=(
            Permission(
                "reports.view_report",
                "Ver relatórios",
                "Acessar relatórios, gráficos e detalhamentos por período.",
            ),
            Permission(
                "reports.export_report",
                "Exportar relatórios",
                "Baixar relatórios em Excel e CSV.",
            ),
        ),
    ),
    PermissionModule(
        key="auth",
        label="Acessos",
        description="Contas, perfis e permissões do painel.",
        permissions=(
            Permission(
                "auth.view_user",
                "Ver usuários",
                "Consultar as contas que acessam o painel.",
            ),
            Permission(
                "auth.add_user",
                "Criar usuários",
                "Criar novas contas de acesso.",
            ),
            Permission(
                "auth.change_user",
                "Editar usuários",
                "Alterar dados, perfis, situação e senha de usuários.",
            ),
            Permission(
                "auth.delete_user",
                "Excluir usuários",
                "Remover contas de acesso.",
            ),
            Permission(
                "auth.view_group",
                "Ver perfis",
                "Consultar os perfis e suas permissões.",
            ),
            Permission(
                "auth.add_group",
                "Criar perfis",
                "Criar novos perfis de acesso.",
            ),
            Permission(
                "auth.change_group",
                "Editar perfis",
                "Alterar o nome, a descrição e as permissões de um perfil.",
            ),
            Permission(
                "auth.delete_group",
                "Excluir perfis",
                "Remover perfis sem usuários vinculados.",
            ),
        ),
    ),
)

ALL_PERMISSIONS: tuple[str, ...] = tuple(
    permission.codename
    for module in PERMISSION_MODULES
    for permission in module.permissions
)
_PERMISSION_MAP = {
    permission.codename: permission
    for module in PERMISSION_MODULES
    for permission in module.permissions
}
_PERMISSION_SET = frozenset(ALL_PERMISSIONS)

_ALL_AUTH = frozenset(
    permission.codename
    for module in PERMISSION_MODULES
    if module.key == "auth"
    for permission in module.permissions
)

DEFAULT_PROFILES: tuple[DefaultProfile, ...] = (
    DefaultProfile(
        name=SYSTEM_PROFILE_NAME,
        description="Acesso total ao painel e à gestão de acessos.",
        is_system=True,
        permissions=frozenset(ALL_PERMISSIONS),
    ),
    DefaultProfile(
        name="Gerentes",
        description="Vendas, catálogo, logística, clientes e relatórios, sem acessos.",
        is_system=False,
        permissions=frozenset(_PERMISSION_SET - _ALL_AUTH),
    ),
    DefaultProfile(
        name="Vendas",
        description="Cria pedidos, acompanha a expedição e mantém clientes, sem exclusões.",
        is_system=False,
        permissions=frozenset(
            {
                "dashboard.view_dashboard",
                "orders.view_order",
                "orders.add_order",
                "orders.change_order",
                "logistics.view_shipment",
                "logistics.change_shipment",
                "products.view_product",
                "customers.view_customer",
                "customers.add_customer",
                "customers.change_customer",
            }
        ),
    ),
    DefaultProfile(
        name="Consulta",
        description="Somente leitura de pedidos, produtos e clientes.",
        is_system=False,
        permissions=frozenset(
            {
                "dashboard.view_dashboard",
                "orders.view_order",
                "logistics.view_shipment",
                "products.view_product",
                "customers.view_customer",
                "reports.view_report",
            }
        ),
    ),
)


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def normalize_permissions(codenames) -> list[str]:
    """Mantém apenas permissões conhecidas, na ordem do registro."""
    chosen = {str(codename) for codename in codenames if codename}
    return [codename for codename in ALL_PERMISSIONS if codename in chosen]


def permission_label(codename: str) -> str:
    permission = _PERMISSION_MAP.get(codename)
    return permission.label if permission else codename


def permission_description(codename: str) -> str:
    permission = _PERMISSION_MAP.get(codename)
    return permission.description if permission else ""


def has_perm(user: dict | None, codename: str) -> bool:
    """Equivalente a ``user.has_perm()`` do Django."""
    if not user:
        return False
    if user.get("is_superuser"):
        return True
    return codename in set(user.get("permissions") or ())


def has_any(user: dict | None, *codenames: str) -> bool:
    return any(has_perm(user, codename) for codename in codenames)


def has_all(user: dict | None, *codenames: str) -> bool:
    return all(has_perm(user, codename) for codename in codenames)


def current_user() -> dict:
    return st.session_state.get("auth_user") or {}


def can_current(codename: str) -> bool:
    return has_perm(current_user(), codename)


def require(codename: str, message: str | None = None) -> dict:
    """Interrompe a página quando a permissão não está disponível."""
    user = current_user()
    if not user:
        st.error(
            "Sessão expirada. Entre novamente para continuar.",
            icon=":material/lock:",
        )
        st.stop()
    if not has_perm(user, codename):
        st.error(
            message or "Seu perfil de acesso não permite visualizar esta página.",
            icon=":material/lock:",
        )
        st.caption("Solicite a um administrador a permissão necessária.")
        st.stop()
    return user


def require_any(*codenames: str) -> dict:
    user = current_user()
    if not user:
        st.error(
            "Sessão expirada. Entre novamente para continuar.",
            icon=":material/lock:",
        )
        st.stop()
    if not has_any(user, *codenames):
        st.error(
            "Seu perfil de acesso não permite visualizar esta página.",
            icon=":material/lock:",
        )
        st.caption("Solicite a um administrador a permissão necessária.")
        st.stop()
    return user


def _permissions_for_user(conn: sqlite3.Connection, user_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT codename
        FROM profile_permissions pp
        JOIN user_profiles up ON up.profile_id = pp.profile_id
        WHERE up.user_id = ?
        UNION
        SELECT codename FROM user_permissions WHERE user_id = ?
        """,
        (user_id, user_id),
    ).fetchall()
    return normalize_permissions(row["codename"] for row in rows)


def get_access(user_id: int) -> dict | None:
    """Carrega dados da conta, perfis e permissões efetivas."""
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, email, active, is_superuser, must_change_password
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None

        profiles = conn.execute(
            """
            SELECT p.id, p.name, p.is_system
            FROM profiles p
            JOIN user_profiles up ON up.profile_id = p.id
            WHERE up.user_id = ?
            ORDER BY p.name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()

        if row["is_superuser"]:
            permissions = list(ALL_PERMISSIONS)
        else:
            permissions = _permissions_for_user(conn, user_id)

    return {
        "id": int(row["id"]),
        "name": row["name"],
        "email": crypto.decrypt(row["email"]),
        "active": bool(row["active"]),
        "is_superuser": bool(row["is_superuser"]),
        "must_change_password": bool(row["must_change_password"]),
        "profiles": [
            {
                "id": int(profile["id"]),
                "name": profile["name"],
                "is_system": bool(profile["is_system"]),
            }
            for profile in profiles
        ],
        "permissions": permissions,
    }


def list_users() -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.name, u.email, u.active, u.is_superuser,
                   u.must_change_password, u.created_at, u.last_login,
                   COALESCE(GROUP_CONCAT(p.name, ', '), '') AS profile_names
            FROM users u
            LEFT JOIN user_profiles up ON up.user_id = u.id
            LEFT JOIN profiles p ON p.id = up.profile_id
            GROUP BY u.id
            ORDER BY u.name COLLATE NOCASE
            """
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "email": crypto.decrypt(row["email"]),
            "active": bool(row["active"]),
            "is_superuser": bool(row["is_superuser"]),
            "must_change_password": bool(row["must_change_password"]),
            "created_at": row["created_at"],
            "last_login": row["last_login"],
            "profile_names": row["profile_names"] or "",
        }
        for row in rows
    ]


def get_user(user_id: int) -> dict | None:
    """Dados completos de um usuário para a tela de administração."""
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, email, active, is_superuser,
                   must_change_password, created_at, last_login
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None

        profile_rows = conn.execute(
            """
            SELECT p.id, p.name, p.is_system
            FROM profiles p
            JOIN user_profiles up ON up.profile_id = p.id
            WHERE up.user_id = ?
            ORDER BY p.name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
        direct_rows = conn.execute(
            "SELECT codename FROM user_permissions WHERE user_id = ?",
            (user_id,),
        ).fetchall()

    profile_ids = [int(profile["id"]) for profile in profile_rows]
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "email": crypto.decrypt(row["email"]),
        "active": bool(row["active"]),
        "is_superuser": bool(row["is_superuser"]),
        "must_change_password": bool(row["must_change_password"]),
        "created_at": row["created_at"],
        "last_login": row["last_login"],
        "profiles": [
            {
                "id": int(profile["id"]),
                "name": profile["name"],
                "is_system": bool(profile["is_system"]),
            }
            for profile in profile_rows
        ],
        "profile_ids": profile_ids,
        "direct_permissions": normalize_permissions(
            direct["codename"] for direct in direct_rows
        ),
    }


def list_profiles() -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.is_system,
                   (SELECT COUNT(*) FROM user_profiles up
                    WHERE up.profile_id = p.id) AS members,
                   (SELECT COUNT(*) FROM profile_permissions pp
                    WHERE pp.profile_id = p.id) AS permission_count
            FROM profiles p
            ORDER BY p.is_system DESC, p.name COLLATE NOCASE
            """
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "description": row["description"] or "",
            "is_system": bool(row["is_system"]),
            "members": int(row["members"]),
            "permission_count": int(row["permission_count"]),
        }
        for row in rows
    ]


def get_profile(profile_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, description, is_system, created_at, updated_at
            FROM profiles WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        permission_rows = conn.execute(
            "SELECT codename FROM profile_permissions WHERE profile_id = ?",
            (profile_id,),
        ).fetchall()

    return {
        "id": int(row["id"]),
        "name": row["name"],
        "description": row["description"] or "",
        "is_system": bool(row["is_system"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "permissions": normalize_permissions(
            permission["codename"] for permission in permission_rows
        ),
    }


def _actor_row(conn: sqlite3.Connection, actor_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, is_superuser, active FROM users WHERE id = ?",
        (actor_id,),
    ).fetchone()
    if row is None or not row["active"]:
        raise DomainError("Sua sessão não é mais válida. Entre novamente.")
    return row


def _require_actor_perm(
    conn: sqlite3.Connection, actor: sqlite3.Row, codename: str
) -> None:
    if actor["is_superuser"]:
        return
    if codename not in _permissions_for_user(conn, int(actor["id"])):
        raise DomainError("Seu perfil não permite executar esta ação.")


def _validate_user_fields(name: str, email: str) -> tuple[str, str]:
    name = name.strip()
    email = email.strip().lower()
    if len(name) < 3:
        raise DomainError("Informe o nome completo do usuário.")
    if not _EMAIL_RE.match(email):
        raise DomainError("Informe um e-mail válido.")
    return name, email


def _valid_profile_ids(
    conn: sqlite3.Connection, profile_ids: list[int] | tuple[int, ...]
) -> list[int]:
    ids = sorted({int(profile_id) for profile_id in profile_ids})
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id FROM profiles WHERE id IN ({placeholders})", ids
    ).fetchall()
    if len(rows) != len(ids):
        raise DomainError("Um dos perfis selecionados não existe mais.")
    return ids


def _set_user_profiles(
    conn: sqlite3.Connection, user_id: int, profile_ids: list[int]
) -> None:
    conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO user_profiles (user_id, profile_id) VALUES (?, ?)",
        [(user_id, profile_id) for profile_id in profile_ids],
    )


def _set_user_permissions(
    conn: sqlite3.Connection, user_id: int, codenames
) -> None:
    permissions = normalize_permissions(codenames)
    conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO user_permissions (user_id, codename) VALUES (?, ?)",
        [(user_id, codename) for codename in permissions],
    )


def _ensure_other_active_superuser(
    conn: sqlite3.Connection, excluded_user_id: int
) -> None:
    remaining = conn.execute(
        """
        SELECT COUNT(*) FROM users
        WHERE is_superuser = 1 AND active = 1 AND id <> ?
        """,
        (excluded_user_id,),
    ).fetchone()[0]
    if remaining == 0:
        raise DomainError(
            "É preciso manter pelo menos um superusuário ativo no sistema."
        )


def create_user(
    *,
    name: str,
    email: str,
    password: str,
    profile_ids: list[int] | tuple[int, ...],
    direct_permissions,
    active: bool,
    is_superuser: bool,
    force_password_change: bool,
    actor_id: int,
) -> int:
    name, email = _validate_user_fields(name, email)
    problems = validate_password_strength(password)
    if problems:
        raise DomainError(" ".join(problems))

    with transaction() as conn:
        actor = _actor_row(conn, actor_id)
        _require_actor_perm(conn, actor, "auth.add_user")
        if is_superuser and not actor["is_superuser"]:
            raise DomainError(
                "Apenas superusuários podem criar outra conta de superusuário."
            )
        valid_profiles = _valid_profile_ids(conn, profile_ids)
        direct = normalize_permissions(direct_permissions)

        try:
            cursor = conn.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, role, is_superuser, active,
                     must_change_password, created_at)
                VALUES (?, ?, ?, 'Colaborador', ?, ?, ?, ?)
                """,
                (
                    name,
                    email,
                    hash_password(password),
                    int(is_superuser),
                    int(active),
                    int(force_password_change),
                    _now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DomainError("Já existe uma conta com este e-mail.") from exc

        user_id = int(cursor.lastrowid)
        _set_user_profiles(conn, user_id, valid_profiles)
        _set_user_permissions(conn, user_id, direct)
    return user_id


def update_user(
    *,
    user_id: int,
    name: str,
    email: str,
    profile_ids: list[int] | tuple[int, ...],
    direct_permissions,
    active: bool,
    is_superuser: bool,
    actor_id: int,
) -> None:
    name, email = _validate_user_fields(name, email)

    with transaction() as conn:
        actor = _actor_row(conn, actor_id)
        _require_actor_perm(conn, actor, "auth.change_user")

        target = conn.execute(
            "SELECT id, is_superuser, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise DomainError("Usuário não encontrado.")
        if target["is_superuser"] and not actor["is_superuser"]:
            raise DomainError(
                "Apenas superusuários podem alterar contas de superusuário."
            )
        if is_superuser and not actor["is_superuser"]:
            raise DomainError(
                "Apenas superusuários podem conceder acesso de superusuário."
            )
        if user_id == actor_id:
            if not active:
                raise DomainError("Você não pode desativar sua própria conta.")
            if target["is_superuser"] and not is_superuser:
                raise DomainError(
                    "Você não pode remover seu próprio acesso de superusuário."
                )
        if target["is_superuser"] and (not is_superuser or not active):
            _ensure_other_active_superuser(conn, user_id)

        valid_profiles = _valid_profile_ids(conn, profile_ids)
        direct = normalize_permissions(direct_permissions)

        try:
            conn.execute(
                """
                UPDATE users
                SET name = ?, email = ?, active = ?, is_superuser = ?
                WHERE id = ?
                """,
                (name, email, int(active), int(is_superuser), user_id),
            )
        except sqlite3.IntegrityError as exc:
            raise DomainError("Já existe uma conta com este e-mail.") from exc

        _set_user_profiles(conn, user_id, valid_profiles)
        _set_user_permissions(conn, user_id, direct)


def set_user_active(user_id: int, active: bool, actor_id: int) -> None:
    with transaction() as conn:
        actor = _actor_row(conn, actor_id)
        _require_actor_perm(conn, actor, "auth.change_user")

        target = conn.execute(
            "SELECT id, is_superuser, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise DomainError("Usuário não encontrado.")
        if target["is_superuser"] and not actor["is_superuser"]:
            raise DomainError(
                "Apenas superusuários podem alterar contas de superusuário."
            )
        if user_id == actor_id and not active:
            raise DomainError("Você não pode desativar sua própria conta.")
        if target["is_superuser"] and not active:
            _ensure_other_active_superuser(conn, user_id)

        conn.execute(
            "UPDATE users SET active = ? WHERE id = ?",
            (int(active), user_id),
        )


def delete_user(user_id: int, actor_id: int) -> None:
    with transaction() as conn:
        actor = _actor_row(conn, actor_id)
        _require_actor_perm(conn, actor, "auth.delete_user")

        target = conn.execute(
            "SELECT id, is_superuser FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise DomainError("Usuário não encontrado.")
        if user_id == actor_id:
            raise DomainError("Você não pode excluir sua própria conta.")
        if target["is_superuser"] and not actor["is_superuser"]:
            raise DomainError(
                "Apenas superusuários podem excluir contas de superusuário."
            )
        if target["is_superuser"]:
            _ensure_other_active_superuser(conn, user_id)

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def reset_password(
    user_id: int,
    new_password: str,
    force_change: bool,
    actor_id: int,
) -> None:
    problems = validate_password_strength(new_password)
    if problems:
        raise DomainError(" ".join(problems))

    with transaction() as conn:
        actor = _actor_row(conn, actor_id)
        _require_actor_perm(conn, actor, "auth.change_user")

        target = conn.execute(
            "SELECT id, is_superuser FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise DomainError("Usuário não encontrado.")
        if user_id == actor_id:
            raise DomainError(
                "Para alterar sua própria senha, use a página Configurações."
            )
        if target["is_superuser"] and not actor["is_superuser"]:
            raise DomainError(
                "Apenas superusuários podem redefinir a senha de um superusuário."
            )

        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
            (hash_password(new_password), int(force_change), user_id),
        )


def save_profile(
    profile_id: int | None,
    name: str,
    description: str,
    permissions,
    actor_id: int,
) -> int:
    name = name.strip()
    if len(name) < 2:
        raise DomainError("Informe um nome para o perfil.")
    selected = normalize_permissions(permissions)
    if not selected:
        raise DomainError("Selecione pelo menos uma permissão para o perfil.")

    with transaction() as conn:
        actor = _actor_row(conn, actor_id)

        if profile_id is None:
            _require_actor_perm(conn, actor, "auth.add_group")
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO profiles
                        (name, description, is_system, created_at, updated_at)
                    VALUES (?, ?, 0, ?, ?)
                    """,
                    (name, description.strip(), _now(), _now()),
                )
            except sqlite3.IntegrityError as exc:
                raise DomainError("Já existe um perfil com este nome.") from exc
            new_id = int(cursor.lastrowid)
            _replace_profile_permissions(conn, new_id, selected)
            return new_id

        _require_actor_perm(conn, actor, "auth.change_group")
        target = conn.execute(
            "SELECT id, name, is_system FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if target is None:
            raise DomainError("Perfil não encontrado.")
        if target["is_system"] or target["name"].casefold() == SYSTEM_PROFILE_NAME.casefold():
            raise DomainError(
                "O perfil Administradores é protegido e não pode ser editado."
            )

        try:
            conn.execute(
                """
                UPDATE profiles
                SET name = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, description.strip(), _now(), profile_id),
            )
        except sqlite3.IntegrityError as exc:
            raise DomainError("Já existe um perfil com este nome.") from exc

        _replace_profile_permissions(conn, profile_id, selected)
    return profile_id


def delete_profile(profile_id: int, actor_id: int) -> None:
    with transaction() as conn:
        actor = _actor_row(conn, actor_id)
        _require_actor_perm(conn, actor, "auth.delete_group")

        target = conn.execute(
            """
            SELECT p.id, p.name, p.is_system,
                   (SELECT COUNT(*) FROM user_profiles up
                    WHERE up.profile_id = p.id) AS members
            FROM profiles p WHERE p.id = ?
            """,
            (profile_id,),
        ).fetchone()
        if target is None:
            raise DomainError("Perfil não encontrado.")
        if target["is_system"] or target["name"].casefold() == SYSTEM_PROFILE_NAME.casefold():
            raise DomainError("O perfil Administradores é protegido e não pode ser excluído.")
        if int(target["members"]) > 0:
            raise DomainError(
                "Este perfil está atribuído a "
                f"{int(target['members'])} usuário(s). Remova-o dos usuários antes de excluir."
            )

        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


def _replace_profile_permissions(
    conn: sqlite3.Connection, profile_id: int, codenames
) -> None:
    selected = normalize_permissions(codenames)
    conn.execute(
        "DELETE FROM profile_permissions WHERE profile_id = ?", (profile_id,)
    )
    conn.executemany(
        "INSERT INTO profile_permissions (profile_id, codename) VALUES (?, ?)",
        [(profile_id, codename) for codename in selected],
    )


def bootstrap() -> None:
    """Cria os perfis padrão e mantém o perfil de sistema sincronizado."""
    now = _now()
    with transaction() as conn:
        count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if count == 0:
            for profile in DEFAULT_PROFILES:
                cursor = conn.execute(
                    """
                    INSERT INTO profiles
                        (name, description, is_system, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        profile.name,
                        profile.description,
                        int(profile.is_system),
                        now,
                        now,
                    ),
                )
                _replace_profile_permissions(
                    conn, int(cursor.lastrowid), profile.permissions
                )

        system = conn.execute(
            "SELECT id FROM profiles WHERE name = ? COLLATE NOCASE",
            (SYSTEM_PROFILE_NAME,),
        ).fetchone()
        if system is None:
            cursor = conn.execute(
                """
                INSERT INTO profiles
                    (name, description, is_system, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (
                    SYSTEM_PROFILE_NAME,
                    "Acesso total ao painel. Perfil protegido pelo sistema.",
                    now,
                    now,
                ),
            )
            system_id = int(cursor.lastrowid)
        else:
            system_id = int(system["id"])
            conn.execute(
                "UPDATE profiles SET is_system = 1 WHERE id = ?", (system_id,)
            )

        _replace_profile_permissions(conn, system_id, ALL_PERMISSIONS)

        # Superusuários sem perfil recebem o perfil de administração para
        # que a interface mostre corretamente a origem do acesso.
        conn.execute(
            """
            INSERT OR IGNORE INTO user_profiles (user_id, profile_id)
            SELECT u.id, ?
            FROM users u
            WHERE u.is_superuser = 1
              AND NOT EXISTS (
                  SELECT 1 FROM user_profiles up WHERE up.user_id = u.id
              )
            """,
            (system_id,),
        )


def migrate_legacy_access() -> None:
    """Migra bancos anteriores à ACL preservando o acesso existente.

    Antes deste recurso todos os usuários tinham acesso completo. Na primeira
    execução, cada usuário sem perfil recebe o perfil Administradores e quem
    tinha o papel antigo ``Administrador`` vira superusuário.
    """
    with transaction() as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= 1:
            return

        conn.execute(
            "UPDATE users SET is_superuser = 1 WHERE role = 'Administrador'"
        )

        system = conn.execute(
            "SELECT id FROM profiles WHERE name = ? COLLATE NOCASE",
            (SYSTEM_PROFILE_NAME,),
        ).fetchone()
        if system is not None:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_profiles (user_id, profile_id)
                SELECT u.id, ?
                FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM user_profiles up WHERE up.user_id = u.id
                )
                """,
                (int(system["id"]),),
            )

        conn.execute("PRAGMA user_version = 1")
