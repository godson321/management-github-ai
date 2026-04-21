from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from github_batch_manager.models import RepositoryRecord


def default_store_path() -> Path:
    appdata_dir = os.getenv("APPDATA")
    if appdata_dir:
        return Path(appdata_dir) / "GitHubBatchManager" / "repositories.json"
    return Path.home() / ".github-batch-manager" / "repositories.json"


class RepositoryStore:
    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path or default_store_path()

    def load(self) -> list[RepositoryRecord]:
        repositories, _ui_state = self.load_app_state()
        return repositories

    def load_app_state(self) -> tuple[list[RepositoryRecord], dict[str, object]]:
        if not self.file_path.exists():
            return [], {}

        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return [], {}

        repositories: list[RepositoryRecord] = []
        ui_state: dict[str, object] = {}

        if isinstance(payload, dict):
            repo_items = payload.get("repositories", [])
            raw_ui_state = payload.get("ui_state", {})
            if isinstance(raw_ui_state, dict):
                ui_state = raw_ui_state
        else:
            repo_items = payload if isinstance(payload, list) else []

        for item in repo_items if isinstance(repo_items, list) else []:
            if not isinstance(item, dict) or "path" not in item:
                continue
            repositories.append(RepositoryRecord.from_store_dict(item))

        return repositories, ui_state

    def save(self, repositories: Iterable[RepositoryRecord]) -> None:
        self.save_app_state(repositories, {})

    def save_app_state(
        self,
        repositories: Iterable[RepositoryRecord],
        ui_state: dict[str, object],
    ) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.file_path.with_suffix(".tmp")
        serialized = {
            "repositories": [repository.to_store_dict() for repository in repositories],
            "ui_state": ui_state,
        }
        temp_path.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.file_path)
