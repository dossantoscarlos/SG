import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import stock_items


def test_empty_items():
    df = stock_items.empty_items()
    assert len(df) == 0
    assert list(df.columns) == list(stock_items.ITEM_COLUMNS)


def test_normalize_items():
    df = pd.DataFrame({"Produto": ["A"], "Quantidade": [2], "Custo unitário": [10.0]})
    out = stock_items.normalize_items(df)
    assert len(out) == 1
    assert out["Quantidade"].iloc[0] == 2
    assert out["Custo unitário"].iloc[0] == 10.0


def test_normalize_items_missing_columns():
    df = pd.DataFrame({"Produto": ["A"]})
    out = stock_items.normalize_items(df)
    assert "Quantidade" in out.columns
    assert "Custo unitário" in out.columns


def test_build_items_seed_add_row():
    seed = stock_items.empty_items()
    state = {"edited_rows": {}, "added_rows": [{"Produto": None, "Quantidade": None, "Custo unitário": None}], "deleted_rows": []}
    new = stock_items.build_items_seed(seed, state, {"A": 5.0})
    assert len(new) == 1
    assert pd.isna(new["Produto"].iloc[0])


def test_build_items_seed_product_autofill():
    seed = stock_items.empty_items()
    state = {"edited_rows": {0: {"Produto": "A"}}, "added_rows": [], "deleted_rows": []}
    # row 0 doesn't exist in empty seed, so no autofill at position 0
    new = stock_items.build_items_seed(seed, state, {"A": 5.0})
    assert len(new) == 0


def test_build_items_seed_product_on_added_row():
    seed = stock_items.empty_items()
    state = {"edited_rows": {}, "added_rows": [{"Produto": "A", "Quantidade": None, "Custo unitário": None}], "deleted_rows": []}
    new = stock_items.build_items_seed(seed, state, {"A": 5.0})
    assert len(new) == 1
    assert new["Produto"].iloc[0] == "A"
    assert int(new["Quantidade"].iloc[0]) == 1
    assert float(new["Custo unitário"].iloc[0]) == 5.0


def test_build_items_seed_delete_row():
    seed = pd.DataFrame({"Produto": ["A", "B"], "Quantidade": [1, 2], "Custo unitário": [5.0, 6.0]})
    state = {"edited_rows": {}, "added_rows": [], "deleted_rows": [0]}
    new = stock_items.build_items_seed(seed, state, {})
    assert len(new) == 1
    assert new["Produto"].iloc[0] == "B"


def test_build_items_seed_edit_quantity():
    seed = pd.DataFrame({"Produto": ["A"], "Quantidade": [1], "Custo unitário": [5.0]})
    state = {"edited_rows": {0: {"Quantidade": 7}}, "added_rows": [], "deleted_rows": []}
    new = stock_items.build_items_seed(seed, state, {"A": 5.0})
    assert int(new["Quantidade"].iloc[0]) == 7
    assert float(new["Custo unitário"].iloc[0]) == 5.0


def test_build_items_seed_change_product():
    seed = pd.DataFrame({"Produto": ["A"], "Quantidade": [3], "Custo unitário": [5.0]})
    state = {"edited_rows": {0: {"Produto": "B"}}, "added_rows": [], "deleted_rows": []}
    new = stock_items.build_items_seed(seed, state, {"A": 5.0, "B": 9.0})
    assert new["Produto"].iloc[0] == "B"
    assert int(new["Quantidade"].iloc[0]) == 1
    assert float(new["Custo unitário"].iloc[0]) == 9.0
