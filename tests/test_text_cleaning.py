"""Focused regression tests for ``geotestmatch.clean_dataframe_text``.

``geotestmatch.py`` is a Streamlit monolith whose module body drives the UI, so
it cannot be imported outside a running app.  These tests therefore extract the
exact production function definitions from the source with ``ast`` and execute
them in an isolated namespace — the test stays tied to the real production code
without launching the app.

Regression covered: pandas 3.0 stores strings in the new ``str`` dtype by
default, so ``select_dtypes(include=["object"])`` no longer selects text
columns and raises a ``Pandas4Warning``.  The production function must select
string columns explicitly (``include=["object", "string"]``) while keeping its
existing text-repair behaviour.
"""

from __future__ import annotations

import ast
import unicodedata
import warnings
from pathlib import Path

import pandas as pd
import pytest
from pandas.errors import Pandas4Warning

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = REPO_ROOT / "geotestmatch.py"


def _load_app_functions(*names: str) -> dict:
    """Extract and execute named top-level functions from geotestmatch.py.

    Returns a namespace dict containing the compiled functions plus the globals
    they need (``pd``, ``unicodedata``).  Raises AssertionError if any requested
    function is not defined at module top level.
    """
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    namespace: dict = {"pd": pd, "unicodedata": unicodedata}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            module = ast.Module(body=[node], type_ignores=[])
            code = compile(module, str(APP_PATH), "exec")
            exec(code, namespace)
    missing = [name for name in names if name not in namespace]
    assert not missing, f"Functions not found in {APP_PATH.name}: {missing}"
    return namespace


class TestCleanDataframeText:
    """clean_dataframe_text must repair text without the pandas 3.0 warning."""

    @classmethod
    @pytest.fixture(scope="class")
    def clean_dataframe_text(cls):
        return _load_app_functions("clean_dataframe_text", "repair_text_value")[
            "clean_dataframe_text"
        ]

    def test_repairs_str_and_object_columns_without_pandas4_warning(self, clean_dataframe_text):
        """String columns (new ``str`` dtype and legacy ``object`` dtype) are
        repaired; numeric columns are untouched; no pandas FutureWarning
        (including the pandas 3.0 ``Pandas4Warning``) is raised."""
        df = pd.DataFrame(
            {
                # pandas 3.0 default: str dtype
                "region": ["  CafÃ©  ", "  MÃ¼nchen  "],
                # legacy object dtype
                "code": pd.Series(["A--B", "C--D"], dtype="object"),
                "kpi": [1.5, 2.5],
            }
        )

        with warnings.catch_warnings():
            # The regression is specifically the pandas 3.0 Pandas4Warning from
            # select_dtypes(include=["object"]) — turn it into an error so a
            # regression to the old pattern fails this test.
            warnings.filterwarnings("error", category=Pandas4Warning)
            out = clean_dataframe_text(df)

        assert list(out["region"]) == ["Café", "München"]
        assert list(out["code"]) == ["A–B", "C–D"]
        assert list(out["kpi"]) == [1.5, 2.5]

    def test_leaves_non_string_columns_untouched(self, clean_dataframe_text):
        df = pd.DataFrame({"kpi": [1.0, 2.0], "ratio": [0.1, 0.2]})
        out = clean_dataframe_text(df)
        assert list(out["kpi"]) == [1.0, 2.0]
        assert list(out["ratio"]) == [0.1, 0.2]
