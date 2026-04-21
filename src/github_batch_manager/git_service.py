from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from github_batch_manager.models import GitChangedFile, GitCommitView, GitLogEntry, GitLogResult, OperationResult, RepositorySnapshot


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class GitCommandRunner(Protocol):
    def run(self, repository_path: Path, args: Sequence[str]) -> CommandResult:
        ...


class SubprocessGitCommandRunner:
    def run(self, repository_path: Path, args: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            ["git", "-C", str(repository_path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class GitRepositoryService:
    def __init__(self, runner: GitCommandRunner | None = None) -> None:
        self.runner = runner or SubprocessGitCommandRunner()

    def get_snapshot(self, repository_path: Path) -> RepositorySnapshot:
        status_result = self.runner.run(repository_path, ["status", "--short", "--branch"])
        if status_result.returncode != 0:
            return RepositorySnapshot(
                status_message=self._format_error(status_result, "无法读取仓库状态"),
            )

        snapshot = parse_status_output(status_result.stdout)
        log_result = self.runner.run(
            repository_path,
            ["log", "-1", "--pretty=%h%x1f%s%x1f%cr"],
        )
        if log_result.returncode == 0 and log_result.stdout.strip():
            summary, age = parse_last_commit_output(log_result.stdout)
            snapshot.last_commit = summary
            snapshot.last_commit_age = age
        else:
            snapshot.last_commit = "尚无提交"
            snapshot.last_commit_age = ""

        return snapshot

    def load_log_graph(self, repository_path: Path, limit: int = 80) -> list[str]:
        result = self.runner.run(
            repository_path,
            ["log", "--graph", "--decorate", "--oneline", "--all", "-n", str(limit)],
        )
        if result.returncode != 0:
            return [self._format_error(result, "无法读取提交日志")]

        lines = [line.rstrip() for line in result.stdout.splitlines() if line.strip()]
        return lines or ["(当前仓库还没有可显示的提交记录)"]

    def load_log_entries(self, repository_path: Path, limit: int = 120) -> GitLogResult:
        result = self.runner.run(
            repository_path,
            [
                "log",
                "--graph",
                "--decorate=short",
                "--date=format:%Y-%m-%d %H:%M:%S",
                "--pretty=format:%x1f%H%x1f%h%x1f%ad%x1f%an%x1f%d%x1f%s",
                "--all",
                "-n",
                str(limit),
            ],
        )
        if result.returncode != 0:
            return GitLogResult(message=self._format_error(result, "无法读取提交日志"))

        entries = parse_log_entries_output(result.stdout)
        if not entries:
            return GitLogResult(message="当前仓库还没有可显示的提交记录。")

        return GitLogResult(entries=entries, message="日志树已更新")

    def load_commit_details(self, repository_path: Path, commit_hash: str) -> str:
        result = self.runner.run(
            repository_path,
            [
                "show",
                "--stat",
                "--decorate=short",
                "--date=format:%Y-%m-%d %H:%M:%S",
                "--format=commit %H%nAuthor: %an%nDate:   %ad%nRefs:   %d%n%n%s%n%n%b",
                "-n",
                "1",
                commit_hash,
            ],
        )
        if result.returncode != 0:
            return self._format_error(result, "无法读取提交详情")

        detail_text = result.stdout.strip()
        return detail_text or f"commit {commit_hash}\n\n(没有更多提交详情)"

    def load_commit_view(self, repository_path: Path, commit_hash: str) -> GitCommitView:
        return GitCommitView(
            detail_text=self.load_commit_details(repository_path, commit_hash),
            files=self.load_commit_files(repository_path, commit_hash),
        )

    def load_commit_files(self, repository_path: Path, commit_hash: str) -> list[GitChangedFile]:
        status_result = self.runner.run(
            repository_path,
            ["show", "--name-status", "--format=", "-n", "1", commit_hash],
        )
        numstat_result = self.runner.run(
            repository_path,
            ["show", "--numstat", "--format=", "-n", "1", commit_hash],
        )

        status_items = parse_name_status_output(status_result.stdout) if status_result.returncode == 0 else []
        numstat_items = parse_numstat_output(numstat_result.stdout) if numstat_result.returncode == 0 else []

        status_map = {path: status for path, status in status_items}
        numstat_map = {path: (additions, deletions) for path, additions, deletions in numstat_items}

        ordered_paths: list[str] = []
        for path, _status in status_items:
            if path not in ordered_paths:
                ordered_paths.append(path)
        for path, _additions, _deletions in numstat_items:
            if path not in ordered_paths:
                ordered_paths.append(path)

        return [
            GitChangedFile(
                path=path,
                status=status_map.get(path, "修改"),
                additions=numstat_map.get(path, ("0", "0"))[0],
                deletions=numstat_map.get(path, ("0", "0"))[1],
            )
            for path in ordered_paths
        ]

    def pull(
        self,
        repository_path: Path,
        repository_name: str,
        strategy: str = "merge",
    ) -> OperationResult:
        result = self.runner.run(repository_path, build_pull_args(strategy))
        if result.returncode != 0:
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="pull",
                status="failed",
                message=self._format_error(result, "拉取失败"),
            )

        message = result.stdout.strip() or "拉取完成"
        return OperationResult(
            repository_path=str(repository_path),
            repository_name=repository_name,
            action="pull",
            status="success",
            message=message,
        )

    def commit_all(
        self,
        repository_path: Path,
        repository_name: str,
        message: str,
    ) -> OperationResult:
        if not message.strip():
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="commit",
                status="failed",
                message="提交说明不能为空。",
            )

        status_result = self.runner.run(repository_path, ["status", "--short"])
        if status_result.returncode != 0:
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="commit",
                status="failed",
                message=self._format_error(status_result, "无法检查变更"),
            )

        if not status_result.stdout.strip():
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="commit",
                status="skipped",
                message="没有可提交的变更，已跳过。",
            )

        add_result = self.runner.run(repository_path, ["add", "-A"])
        if add_result.returncode != 0:
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="commit",
                status="failed",
                message=self._format_error(add_result, "暂存失败"),
            )

        commit_result = self.runner.run(repository_path, ["commit", "-m", message])
        if commit_result.returncode != 0:
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="commit",
                status="failed",
                message=self._format_error(commit_result, "提交失败"),
            )

        return OperationResult(
            repository_path=str(repository_path),
            repository_name=repository_name,
            action="commit",
            status="success",
            message=commit_result.stdout.strip() or "提交完成",
        )

    def push(self, repository_path: Path, repository_name: str) -> OperationResult:
        result = self.runner.run(repository_path, ["push"])
        if result.returncode != 0:
            return OperationResult(
                repository_path=str(repository_path),
                repository_name=repository_name,
                action="push",
                status="failed",
                message=self._format_error(result, "推送失败"),
            )

        message = result.stdout.strip() or "推送完成"
        return OperationResult(
            repository_path=str(repository_path),
            repository_name=repository_name,
            action="push",
            status="success",
            message=message,
        )

    def _format_error(self, result: CommandResult, prefix: str) -> str:
        details = result.stderr.strip() or result.stdout.strip() or "未知 git 错误"
        return f"{prefix}: {details}"


def parse_status_output(output: str) -> RepositorySnapshot:
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    if not lines:
        return RepositorySnapshot(status_message="仓库为空。")

    headline = lines[0]
    branch = "未知分支"
    ahead = 0
    behind = 0

    if headline.startswith("## "):
        headline = headline[3:]

    if headline.startswith("No commits yet on "):
        branch = headline.removeprefix("No commits yet on ").strip()
    elif headline.startswith("Initial commit on "):
        branch = headline.removeprefix("Initial commit on ").strip()
    else:
        branch_section, _, tracking_section = headline.partition("...")
        branch = branch_section.strip()
        if tracking_section:
            bracket_start = tracking_section.find("[")
            bracket_end = tracking_section.find("]")
            if bracket_start != -1 and bracket_end != -1:
                tracking_bits = tracking_section[bracket_start + 1 : bracket_end]
                for piece in tracking_bits.split(","):
                    item = piece.strip()
                    if item.startswith("ahead "):
                        ahead = int(item.removeprefix("ahead ").strip())
                    elif item.startswith("behind "):
                        behind = int(item.removeprefix("behind ").strip())

    return RepositorySnapshot(
        branch=branch,
        dirty=len(lines) > 1,
        ahead=ahead,
        behind=behind,
        status_message="状态已刷新",
    )


def parse_last_commit_output(output: str) -> tuple[str, str]:
    parts = output.strip().split("\x1f")
    if len(parts) < 3:
        return output.strip(), ""
    short_hash, subject, age = parts[:3]
    summary = f"{short_hash} {subject}".strip()
    return summary, age.strip()


def parse_log_entries_output(output: str) -> list[GitLogEntry]:
    entries: list[GitLogEntry] = []
    for raw_line in output.splitlines():
        if "\x1f" not in raw_line:
            continue

        graph_prefix, payload = raw_line.split("\x1f", 1)
        parts = payload.split("\x1f")
        if len(parts) < 6:
            continue

        commit_hash, short_hash, date, author, refs_raw, subject = parts[:6]
        refs = normalize_refs_display(refs_raw)
        current_ref, remote_refs, tag_refs = split_ref_groups(refs_raw)
        entries.append(
            GitLogEntry(
                graph=graph_prefix.rstrip(),
                commit_hash=commit_hash.strip(),
                short_hash=short_hash.strip(),
                date=date.strip(),
                author=author.strip(),
                refs=refs,
                current_ref=current_ref,
                remote_refs=remote_refs,
                tag_refs=tag_refs,
                subject=subject.strip(),
                is_head="HEAD ->" in refs_raw,
                has_tag="tag:" in refs_raw,
                has_remote_ref=bool(remote_refs),
            )
        )

    return entries


def normalize_refs_display(refs_raw: str) -> str:
    refs = refs_raw.strip()
    if refs.startswith("(") and refs.endswith(")"):
        refs = refs[1:-1].strip()

    if not refs:
        return ""

    parts = [part.strip() for part in refs.split(",") if part.strip()]
    normalized = [part.removeprefix("tag: ").strip() for part in parts]
    return ", ".join(normalized)


def split_ref_groups(refs_raw: str) -> tuple[str, str, str]:
    refs = refs_raw.strip()
    if refs.startswith("(") and refs.endswith(")"):
        refs = refs[1:-1].strip()

    if not refs:
        return "", "", ""

    current_parts: list[str] = []
    remote_parts: list[str] = []
    tag_parts: list[str] = []
    other_parts: list[str] = []

    for part in [item.strip() for item in refs.split(",") if item.strip()]:
        if part.startswith("HEAD ->"):
            current_parts.append(part)
        elif part.startswith("tag: "):
            tag_parts.append(part.removeprefix("tag: ").strip())
        elif "/" in part:
            remote_parts.append(part)
        else:
            other_parts.append(part)

    current_ref = ", ".join(current_parts + other_parts)
    remote_refs = ", ".join(remote_parts)
    tag_refs = ", ".join(tag_parts)
    return current_ref, remote_refs, tag_refs


def parse_name_status_output(output: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split("\t")
        status_code = parts[0][:1]
        path = normalize_name_status_path(parts)
        items.append((path, map_status_code(status_code)))

    return items


def normalize_name_status_path(parts: list[str]) -> str:
    if len(parts) >= 3 and parts[0][:1] in {"R", "C"}:
        return f"{parts[1]} -> {parts[2]}"
    if len(parts) >= 2:
        return parts[1]
    return parts[0]


def parse_numstat_output(output: str) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions, deletions, path = parts[0], parts[1], parts[2]
        items.append((path, additions, deletions))

    return items


def map_status_code(status_code: str) -> str:
    return {
        "A": "新增",
        "M": "修改",
        "D": "删除",
        "R": "重命名",
        "C": "复制",
        "T": "类型变更",
        "U": "冲突",
    }.get(status_code, "修改")


def build_pull_args(strategy: str) -> list[str]:
    strategy_map = {
        "merge": ["pull", "--no-rebase"],
        "ff_only": ["pull", "--ff-only"],
        "rebase": ["pull", "--rebase"],
    }
    return strategy_map.get(strategy, strategy_map["merge"])
