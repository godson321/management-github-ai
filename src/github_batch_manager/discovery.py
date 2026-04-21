from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from github_batch_manager.models import normalize_repository_path


class RepositoryDiscoveryService:
    def discover(self, raw_paths: Iterable[str | Path]) -> list[Path]:
        discovered: dict[str, Path] = {}

        for raw_path in raw_paths:
            if not raw_path:
                continue

            candidate = Path(raw_path).expanduser()
            if not candidate.exists():
                continue

            if self._is_git_repository(candidate):
                normalized = normalize_repository_path(candidate)
                discovered[normalized] = Path(normalized)
                continue

            if candidate.is_dir():
                for repository_path in self._walk_for_repositories(candidate):
                    normalized = normalize_repository_path(repository_path)
                    discovered[normalized] = Path(normalized)

        return sorted(discovered.values(), key=lambda item: item.as_posix().lower())

    def _walk_for_repositories(self, root_path: Path) -> list[Path]:
        repositories: list[Path] = []

        for current_root, dirnames, _filenames in os.walk(root_path):
            current_path = Path(current_root)

            if self._is_git_repository(current_path):
                repositories.append(current_path)
                dirnames[:] = []
                continue

            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname not in {".git", "__pycache__", ".venv", "node_modules"}
            ]

        return repositories

    def _is_git_repository(self, candidate: Path) -> bool:
        if not candidate.is_dir():
            return False

        dot_git = candidate / ".git"
        return dot_git.is_dir() or dot_git.is_file()

