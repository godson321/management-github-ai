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

from github_batch_manager.discovery import RepositoryDiscoveryService


class RepositoryDiscoveryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RepositoryDiscoveryService()
        TMP_ROOT.mkdir(exist_ok=True)

    def test_discovers_direct_repository_and_nested_repositories(self) -> None:
        root = TMP_ROOT / "discovery-case"
        shutil.rmtree(root, ignore_errors=True)
        direct_repo = root / "direct"
        nested_repo = root / "nested" / "repo-a"
        plain_dir = root / "plain"

        (direct_repo / ".git").mkdir(parents=True, exist_ok=True)
        (nested_repo / ".git").mkdir(parents=True, exist_ok=True)
        plain_dir.mkdir(parents=True, exist_ok=True)

        discovered = self.service.discover([root, direct_repo, plain_dir])
        discovered_paths = {path.name for path in discovered}

        self.assertEqual(discovered_paths, {"direct", "repo-a"})

    def test_ignores_missing_paths(self) -> None:
        root = TMP_ROOT / "missing-case"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

        discovered = self.service.discover([root / "does-not-exist"])
        self.assertEqual(discovered, [])


if __name__ == "__main__":
    unittest.main()
