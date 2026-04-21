from __future__ import annotations

import sys
import shutil
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
TMP_ROOT = PROJECT_ROOT / ".tmp-tests"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from github_batch_manager.models import RepositoryRecord
from github_batch_manager.store import RepositoryStore


class RepositoryStoreTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        TMP_ROOT.mkdir(exist_ok=True)
        case_dir = TMP_ROOT / "store-round-trip"
        shutil.rmtree(case_dir, ignore_errors=True)
        case_dir.mkdir(parents=True, exist_ok=True)
        store = RepositoryStore(case_dir / "repositories.json")
        repositories = [
            RepositoryRecord(path=case_dir / "repo-one", selected=True),
            RepositoryRecord(path=case_dir / "repo-two", selected=False),
        ]

        store.save(repositories)
        loaded = store.load()

        self.assertEqual([item.path for item in loaded], [item.path for item in repositories])
        self.assertEqual([item.selected for item in loaded], [True, False])

    def test_save_and_load_app_state_round_trip(self) -> None:
        TMP_ROOT.mkdir(exist_ok=True)
        case_dir = TMP_ROOT / "store-app-state"
        shutil.rmtree(case_dir, ignore_errors=True)
        case_dir.mkdir(parents=True, exist_ok=True)
        store = RepositoryStore(case_dir / "repositories.json")
        repositories = [
            RepositoryRecord(path=case_dir / "repo-one", selected=True),
        ]
        ui_state = {
            "repo_table": {
                "sort_column": "name",
                "sort_descending": False,
                "displaycolumns": ["selected", "name", "path"],
                "column_widths": {"name": 320},
            }
        }

        store.save_app_state(repositories, ui_state)
        loaded_repositories, loaded_ui_state = store.load_app_state()

        self.assertEqual([item.path for item in loaded_repositories], [item.path for item in repositories])
        self.assertEqual(loaded_ui_state, ui_state)

    def test_invalid_json_returns_empty_list(self) -> None:
        TMP_ROOT.mkdir(exist_ok=True)
        case_dir = TMP_ROOT / "store-invalid-json"
        shutil.rmtree(case_dir, ignore_errors=True)
        case_dir.mkdir(parents=True, exist_ok=True)
        store_path = case_dir / "repositories.json"
        store_path.write_text("{broken", encoding="utf-8")

        store = RepositoryStore(store_path)
        self.assertEqual(store.load(), [])
        self.assertEqual(store.load_app_state(), ([], {}))


if __name__ == "__main__":
    unittest.main()
