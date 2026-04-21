from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def normalize_repository_path(raw_path: str | Path) -> str:
    return str(Path(raw_path).expanduser().resolve())


@dataclass(slots=True)
class RepositoryRecord:
    path: str
    selected: bool = True
    name: str = ""
    branch: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    last_commit: str = ""
    last_commit_age: str = ""
    status_message: str = "未刷新"
    last_operation_status: str = "idle"
    last_error_message: str = ""
    log_lines: list[str] = field(default_factory=list)
    log_entries: list["GitLogEntry"] = field(default_factory=list)
    log_message: str = "请选择一个仓库以查看日志树。"
    selected_commit_hash: str = ""
    commit_detail_text: str = ""
    commit_changed_files: list["GitChangedFile"] = field(default_factory=list)
    commit_views: dict[str, "GitCommitView"] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path = normalize_repository_path(self.path)
        if not self.name:
            self.name = Path(self.path).name or self.path

    def to_store_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "selected": self.selected,
        }

    @classmethod
    def from_store_dict(cls, payload: dict[str, object]) -> "RepositoryRecord":
        return cls(
            path=str(payload["path"]),
            selected=bool(payload.get("selected", True)),
        )


@dataclass(slots=True)
class RepositorySnapshot:
    branch: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    last_commit: str = ""
    last_commit_age: str = ""
    status_message: str = ""
    log_lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OperationResult:
    repository_path: str
    repository_name: str
    action: str
    status: str
    message: str


@dataclass(slots=True)
class GitLogEntry:
    graph: str
    commit_hash: str
    short_hash: str
    date: str
    author: str
    refs: str
    subject: str
    current_ref: str = ""
    remote_refs: str = ""
    tag_refs: str = ""
    is_head: bool = False
    has_tag: bool = False
    has_remote_ref: bool = False


@dataclass(slots=True)
class GitLogResult:
    entries: list[GitLogEntry] = field(default_factory=list)
    message: str = ""


@dataclass(slots=True)
class GitChangedFile:
    path: str
    status: str
    additions: str
    deletions: str


@dataclass(slots=True)
class GitCommitView:
    detail_text: str = ""
    files: list[GitChangedFile] = field(default_factory=list)
