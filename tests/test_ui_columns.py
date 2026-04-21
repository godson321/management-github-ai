from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from github_batch_manager.ui import (
    merge_visible_repo_columns,
    normalize_repo_column_order,
    normalize_repo_hidden_columns,
)


class RepositoryColumnLayoutTests(unittest.TestCase):
    def test_normalize_repo_column_order_preserves_known_columns_and_appends_missing(self) -> None:
        columns = ("selected", "name", "branch", "path")

        order = normalize_repo_column_order(columns, ["name", "path", "unknown"])

        self.assertEqual(order, ["name", "path", "selected", "branch"])

    def test_normalize_repo_hidden_columns_filters_unknown_and_duplicates(self) -> None:
        columns = ("selected", "name", "branch", "path")

        hidden = normalize_repo_hidden_columns(columns, ["path", "path", "missing", "branch"])

        self.assertEqual(hidden, ["path", "branch"])

    def test_merge_visible_repo_columns_keeps_hidden_slots_while_reordering_visible_columns(self) -> None:
        column_order = ["selected", "name", "branch", "status", "path"]
        hidden_columns = {"branch"}

        merged = merge_visible_repo_columns(
            column_order,
            hidden_columns,
            ["status", "selected", "name", "path"],
        )

        self.assertEqual(merged, ["status", "selected", "branch", "name", "path"])


if __name__ == "__main__":
    unittest.main()
