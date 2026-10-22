"""Montagem da tabela de itens do documento de estoque.

O formulário de movimentação usa ``st.data_editor`` e o estado do widget
chega como um dicionário com ``edited_rows`` (posição -> alterações),
``added_rows`` (linhas incluídas pelo usuário) e ``deleted_rows`` (posições
removidas). Estas funções convertem esse estado na tabela que alimenta o
editor: quando o produto de uma linha muda, a quantidade passa a 1 e o custo
unitário recebe o valor cadastrado do produto.
"""

from __future__ import annotations

import pandas as pd

ITEM_COLUMNS = ("Produto", "Quantidade", "Custo unitário")


def empty_items() -> pd.DataFrame:
    """Tabela sem linhas, pronta para receber itens."""
    return pd.DataFrame(
        {
            "Produto": pd.Series(dtype="object"),
            "Quantidade": pd.Series(dtype="Int64"),
            "Custo unitário": pd.Series(dtype="float64"),
        }
    )


def normalize_items(frame: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas e tipos esperados da tabela de itens."""
    frame = frame.copy()
    for column in ITEM_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame = frame[list(ITEM_COLUMNS)].reset_index(drop=True)
    frame["Quantidade"] = pd.to_numeric(
        frame["Quantidade"], errors="coerce"
    ).astype("Int64")
    frame["Custo unitário"] = pd.to_numeric(
        frame["Custo unitário"], errors="coerce"
    ).astype("float64")
    return frame


def build_items_seed(
    seed: pd.DataFrame,
    state: dict,
    product_costs: dict[str, float],
) -> pd.DataFrame:
    """Aplica o estado do editor sobre a tabela e devolve a nova tabela.

    ``state`` segue o formato do ``st.data_editor``. Linhas adicionadas
    entram no fim da tabela e linhas removidas são descartadas. Quando o
    produto de uma linha muda, a quantidade passa a 1 e o custo unitário
    recebe o valor cadastrado do produto.

    A função não guarda estado: o chamador deve aplicá-la uma única vez por
    alteração do editor.
    """
    base = normalize_items(seed)
    edited_rows = state.get("edited_rows") or {}
    added_rows = state.get("added_rows") or []
    deleted_rows = {
        int(position) for position in (state.get("deleted_rows") or [])
    }

    for position, changes in edited_rows.items():
        row_position = int(position)
        if not 0 <= row_position < len(base):
            continue
        for column, value in changes.items():
            if column in base.columns:
                base.iat[
                    row_position, base.columns.get_loc(column)
                ] = value

    for position, changes in edited_rows.items():
        if "Produto" not in changes:
            continue
        row_position = int(position)
        if not 0 <= row_position < len(base) or row_position in deleted_rows:
            continue
        label = base.iat[row_position, base.columns.get_loc("Produto")]
        if label in product_costs:
            base.iat[
                row_position, base.columns.get_loc("Quantidade")
            ] = 1
            base.iat[
                row_position, base.columns.get_loc("Custo unitário")
            ] = product_costs[label]
        else:
            base.iat[
                row_position, base.columns.get_loc("Quantidade")
            ] = None
            base.iat[
                row_position, base.columns.get_loc("Custo unitário")
            ] = None

    if deleted_rows:
        positions = sorted(
            position for position in deleted_rows if position < len(base)
        )
        if positions:
            base = base.drop(base.index[positions])

    rows = base.to_dict("records")
    for added_row in added_rows:
        row = {column: added_row.get(column) for column in ITEM_COLUMNS}
        label = row.get("Produto")
        if label in product_costs:
            row["Quantidade"] = 1
            row["Custo unitário"] = product_costs[label]
        rows.append(row)

    return normalize_items(pd.DataFrame(rows, columns=list(ITEM_COLUMNS)))
