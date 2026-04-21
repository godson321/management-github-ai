from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from github_batch_manager.windows_shell import (
    WindowsExplorerShell,
    normalize_shell_menu_label,
    parse_context_menu_items,
)


class FakeRunner:
    def __init__(self, *, stdout: str = "[]", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


class WindowsShellTests(unittest.TestCase):
    def test_normalize_shell_menu_label_removes_accelerators_and_shortcuts(self) -> None:
        normalized = normalize_shell_menu_label("&Open in Terminal\tShift+Right Click\r\n")
        self.assertEqual(normalized, "Open in Terminal")

    def test_parse_context_menu_items_compacts_blank_separators(self) -> None:
        items = parse_context_menu_items(
            '[{"index":0,"name":"&Open"},{"index":1,"name":""},{"index":2,"name":"   "},{"index":3,"name":"Open in &Terminal"}]'
        )

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].label, "Open")
        self.assertEqual(items[0].verb_index, 0)
        self.assertTrue(items[1].is_separator)
        self.assertEqual(items[2].label, "Open in Terminal")
        self.assertEqual(items[2].verb_index, 3)

    def test_list_folder_menu_items_uses_powershell_with_target_path_env(self) -> None:
        runner = FakeRunner(stdout='[{"index":0,"name":"&Open"}]')
        shell = WindowsExplorerShell(runner=runner)

        with patch("github_batch_manager.windows_shell.sys.platform", "win32"):
            items = shell.list_folder_menu_items(Path(r"C:\demo"))

        self.assertEqual([item.label for item in items], ["Open"])
        self.assertEqual(len(runner.calls), 1)
        command, kwargs = runner.calls[0]
        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("-Command", command)
        self.assertEqual(kwargs["env"]["GBM_TARGET_PATH"], r"C:\demo")
        self.assertNotIn("GBM_VERB_INDEX", kwargs["env"])

    def test_invoke_folder_menu_item_passes_verb_index(self) -> None:
        runner = FakeRunner()
        shell = WindowsExplorerShell(runner=runner)

        with patch("github_batch_manager.windows_shell.sys.platform", "win32"):
            shell.invoke_folder_menu_item(Path(r"C:\demo"), 7)

        self.assertEqual(len(runner.calls), 1)
        _command, kwargs = runner.calls[0]
        self.assertEqual(kwargs["env"]["GBM_TARGET_PATH"], r"C:\demo")
        self.assertEqual(kwargs["env"]["GBM_VERB_INDEX"], "7")

    def test_invoke_folder_menu_item_raises_when_powershell_fails(self) -> None:
        runner = FakeRunner(stderr="Access denied.", returncode=1)
        shell = WindowsExplorerShell(runner=runner)

        with patch("github_batch_manager.windows_shell.sys.platform", "win32"):
            with self.assertRaises(OSError):
                shell.invoke_folder_menu_item(Path(r"C:\demo"), 1)


if __name__ == "__main__":
    unittest.main()
