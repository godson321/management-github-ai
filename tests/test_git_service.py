from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from github_batch_manager.git_service import (
    build_pull_args,
    CommandResult,
    GitRepositoryService,
    map_status_code,
    normalize_refs_display,
    parse_name_status_output,
    parse_numstat_output,
    parse_last_commit_output,
    parse_log_entries_output,
    split_ref_groups,
    parse_status_output,
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def run(self, repository_path: Path, args: list[str] | tuple[str, ...]) -> CommandResult:
        key = tuple(args)
        self.calls.append(key)
        return self.responses[key]


class GitRepositoryServiceTests(unittest.TestCase):
    def test_parse_status_output_extracts_branch_ahead_behind_and_dirty(self) -> None:
        snapshot = parse_status_output(
            "## main...origin/main [ahead 2, behind 1]\n M README.md\n"
        )

        self.assertEqual(snapshot.branch, "main")
        self.assertEqual(snapshot.ahead, 2)
        self.assertEqual(snapshot.behind, 1)
        self.assertTrue(snapshot.dirty)

    def test_parse_last_commit_output_formats_summary(self) -> None:
        summary, age = parse_last_commit_output("abc123\x1f初始化界面\x1f2 hours ago")
        self.assertEqual(summary, "abc123 初始化界面")
        self.assertEqual(age, "2 hours ago")

    def test_get_snapshot_reads_status_and_last_commit(self) -> None:
        runner = FakeRunner(
            {
                ("status", "--short", "--branch"): CommandResult(
                    returncode=0,
                    stdout="## main...origin/main [ahead 1]\n",
                    stderr="",
                ),
                ("log", "-1", "--pretty=%h%x1f%s%x1f%cr"): CommandResult(
                    returncode=0,
                    stdout="abc123\x1f补充测试\x1f5 minutes ago",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        snapshot = service.get_snapshot(Path("demo"))

        self.assertEqual(snapshot.branch, "main")
        self.assertEqual(snapshot.ahead, 1)
        self.assertEqual(snapshot.last_commit, "abc123 补充测试")
        self.assertEqual(snapshot.last_commit_age, "5 minutes ago")

    def test_commit_all_skips_when_no_changes(self) -> None:
        runner = FakeRunner(
            {
                ("status", "--short"): CommandResult(returncode=0, stdout="", stderr=""),
            }
        )
        service = GitRepositoryService(runner)

        result = service.commit_all(Path("demo"), "demo", "提交一次")

        self.assertEqual(result.status, "skipped")
        self.assertEqual(runner.calls, [("status", "--short")])

    def test_commit_all_runs_add_and_commit_when_changes_exist(self) -> None:
        runner = FakeRunner(
            {
                ("status", "--short"): CommandResult(returncode=0, stdout=" M main.py\n", stderr=""),
                ("add", "-A"): CommandResult(returncode=0, stdout="", stderr=""),
                ("commit", "-m", "提交一次"): CommandResult(
                    returncode=0,
                    stdout="[main abc123] 提交一次",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        result = service.commit_all(Path("demo"), "demo", "提交一次")

        self.assertEqual(result.status, "success")
        self.assertEqual(
            runner.calls,
            [
                ("status", "--short"),
                ("add", "-A"),
                ("commit", "-m", "提交一次"),
            ],
        )

    def test_load_log_graph_returns_error_message_when_git_fails(self) -> None:
        runner = FakeRunner(
            {
                ("log", "--graph", "--decorate", "--oneline", "--all", "-n", "80"): CommandResult(
                    returncode=1,
                    stdout="",
                    stderr="fatal: bad revision",
                ),
            }
        )
        service = GitRepositoryService(runner)

        lines = service.load_log_graph(Path("demo"))

        self.assertEqual(lines, ["无法读取提交日志: fatal: bad revision"])

    def test_pull_uses_merge_strategy_by_default(self) -> None:
        runner = FakeRunner(
            {
                ("pull", "--no-rebase"): CommandResult(
                    returncode=0,
                    stdout="Merge made by the 'ort' strategy.",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        result = service.pull(Path("demo"), "demo")

        self.assertEqual(result.status, "success")
        self.assertEqual(runner.calls, [("pull", "--no-rebase")])

    def test_pull_uses_ff_only_strategy(self) -> None:
        runner = FakeRunner(
            {
                ("pull", "--ff-only"): CommandResult(
                    returncode=0,
                    stdout="Already up to date.",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        result = service.pull(Path("demo"), "demo", "ff_only")

        self.assertEqual(result.status, "success")
        self.assertEqual(runner.calls, [("pull", "--ff-only")])

    def test_pull_uses_rebase_strategy(self) -> None:
        runner = FakeRunner(
            {
                ("pull", "--rebase"): CommandResult(
                    returncode=0,
                    stdout="Successfully rebased and updated refs/heads/main.",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        result = service.pull(Path("demo"), "demo", "rebase")

        self.assertEqual(result.status, "success")
        self.assertEqual(runner.calls, [("pull", "--rebase")])

    def test_build_pull_args_falls_back_to_merge(self) -> None:
        self.assertEqual(build_pull_args("unknown"), ["pull", "--no-rebase"])

    def test_parse_log_entries_output_extracts_head_and_tags(self) -> None:
        entries = parse_log_entries_output(
            "* \x1f0123456789abcdef\x1f0123456\x1f2026-04-21 11:11:15\x1fcatalog22\x1f (HEAD -> main, origin/main, tag: v7.3.9)\x1ffeat: 升级版本\n"
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].short_hash, "0123456")
        self.assertEqual(entries[0].refs, "HEAD -> main, origin/main, v7.3.9")
        self.assertEqual(entries[0].current_ref, "HEAD -> main")
        self.assertEqual(entries[0].remote_refs, "origin/main")
        self.assertEqual(entries[0].tag_refs, "v7.3.9")
        self.assertTrue(entries[0].is_head)
        self.assertTrue(entries[0].has_tag)
        self.assertTrue(entries[0].has_remote_ref)

    def test_normalize_refs_display_removes_parentheses_and_tag_prefix(self) -> None:
        refs = normalize_refs_display("(HEAD -> main, origin/main, tag: v1.2.3)")
        self.assertEqual(refs, "HEAD -> main, origin/main, v1.2.3")

    def test_split_ref_groups_separates_current_remote_and_tag(self) -> None:
        current_ref, remote_refs, tag_refs = split_ref_groups("(HEAD -> main, origin/main, tag: v1.2.3)")
        self.assertEqual(current_ref, "HEAD -> main")
        self.assertEqual(remote_refs, "origin/main")
        self.assertEqual(tag_refs, "v1.2.3")

    def test_parse_name_status_output_supports_rename(self) -> None:
        items = parse_name_status_output("M\tsrc/app.py\nR100\told.txt\tnew.txt\n")
        self.assertEqual(items, [("src/app.py", "修改"), ("old.txt -> new.txt", "重命名")])

    def test_parse_numstat_output_extracts_add_delete_counts(self) -> None:
        items = parse_numstat_output("10\t2\tsrc/app.py\n-\t-\tassets/logo.png\n")
        self.assertEqual(items, [("src/app.py", "10", "2"), ("assets/logo.png", "-", "-")])

    def test_map_status_code_returns_human_label(self) -> None:
        self.assertEqual(map_status_code("A"), "新增")
        self.assertEqual(map_status_code("R"), "重命名")

    def test_load_commit_details_returns_show_output(self) -> None:
        runner = FakeRunner(
            {
                (
                    "show",
                    "--stat",
                    "--decorate=short",
                    "--date=format:%Y-%m-%d %H:%M:%S",
                    "--format=commit %H%nAuthor: %an%nDate:   %ad%nRefs:   %d%n%n%s%n%n%b",
                    "-n",
                    "1",
                    "abc123",
                ): CommandResult(
                    returncode=0,
                    stdout="commit abc123\nAuthor: demo\nDate:   2026-04-21 11:11:15\n\nfeat: 补充日志树",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        detail = service.load_commit_details(Path("demo"), "abc123")

        self.assertIn("commit abc123", detail)
        self.assertIn("feat: 补充日志树", detail)

    def test_load_commit_view_returns_detail_and_changed_files(self) -> None:
        runner = FakeRunner(
            {
                (
                    "show",
                    "--stat",
                    "--decorate=short",
                    "--date=format:%Y-%m-%d %H:%M:%S",
                    "--format=commit %H%nAuthor: %an%nDate:   %ad%nRefs:   %d%n%n%s%n%n%b",
                    "-n",
                    "1",
                    "abc123",
                ): CommandResult(
                    returncode=0,
                    stdout="commit abc123\nAuthor: demo\n\nfeat: 补充日志树",
                    stderr="",
                ),
                ("show", "--name-status", "--format=", "-n", "1", "abc123"): CommandResult(
                    returncode=0,
                    stdout="M\tsrc/app.py\nA\tREADME.md\n",
                    stderr="",
                ),
                ("show", "--numstat", "--format=", "-n", "1", "abc123"): CommandResult(
                    returncode=0,
                    stdout="10\t2\tsrc/app.py\n5\t0\tREADME.md\n",
                    stderr="",
                ),
            }
        )
        service = GitRepositoryService(runner)

        commit_view = service.load_commit_view(Path("demo"), "abc123")

        self.assertIn("commit abc123", commit_view.detail_text)
        self.assertEqual(len(commit_view.files), 2)
        self.assertEqual(commit_view.files[0].path, "src/app.py")
        self.assertEqual(commit_view.files[0].status, "修改")
        self.assertEqual(commit_view.files[0].additions, "10")


if __name__ == "__main__":
    unittest.main()
