from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


_POWERSHELL_ENCODING_PREFIX = (
    "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); "
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
    "$OutputEncoding=[Text.UTF8Encoding]::new($false); "
)

_LIST_FOLDER_MENU_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$targetPath = $env:GBM_TARGET_PATH
if ([string]::IsNullOrWhiteSpace($targetPath)) {
    throw 'Missing target path.'
}
if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
    throw "Folder not found: $targetPath"
}
$shell = New-Object -ComObject Shell.Application
$namespace = $shell.Namespace($targetPath)
if ($null -eq $namespace) {
    throw "Unable to access shell namespace: $targetPath"
}
$item = $namespace.Self
if ($null -eq $item) {
    throw "Unable to resolve shell item: $targetPath"
}
$items = @()
$index = 0
foreach ($verb in @($item.Verbs())) {
    $items += [PSCustomObject]@{
        index = $index
        name = [string]$verb.Name
    }
    $index++
}
$items | ConvertTo-Json -Compress
"""

_INVOKE_FOLDER_MENU_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$targetPath = $env:GBM_TARGET_PATH
$verbIndexText = $env:GBM_VERB_INDEX
if ([string]::IsNullOrWhiteSpace($targetPath)) {
    throw 'Missing target path.'
}
if ([string]::IsNullOrWhiteSpace($verbIndexText)) {
    throw 'Missing verb index.'
}
if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
    throw "Folder not found: $targetPath"
}
$verbIndex = [int]$verbIndexText
$shell = New-Object -ComObject Shell.Application
$namespace = $shell.Namespace($targetPath)
if ($null -eq $namespace) {
    throw "Unable to access shell namespace: $targetPath"
}
$item = $namespace.Self
if ($null -eq $item) {
    throw "Unable to resolve shell item: $targetPath"
}
$verbs = @($item.Verbs())
if ($verbIndex -lt 0 -or $verbIndex -ge $verbs.Count) {
    throw "Verb index out of range: $verbIndex"
}
$verbs[$verbIndex].DoIt()
"""


@dataclass(frozen=True)
class WindowsContextMenuItem:
    label: str
    verb_index: int | None = None
    is_separator: bool = False

    @classmethod
    def separator(cls) -> "WindowsContextMenuItem":
        return cls(label="", verb_index=None, is_separator=True)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def normalize_shell_menu_label(raw_label: str) -> str:
    cleaned = raw_label.replace("&", "").replace("\r", " ").replace("\n", " ").strip()
    if "\t" in cleaned:
        cleaned = cleaned.split("\t", 1)[0].strip()
    return " ".join(cleaned.split())


def parse_context_menu_items(stdout: str) -> list[WindowsContextMenuItem]:
    payload = stdout.strip()
    if not payload:
        return []

    decoded = json.loads(payload)
    if isinstance(decoded, dict):
        decoded = [decoded]
    if not isinstance(decoded, list):
        raise ValueError("Unexpected shell menu payload.")

    items: list[WindowsContextMenuItem] = []
    previous_was_separator = True

    for row in decoded:
        if not isinstance(row, dict):
            continue

        normalized_label = normalize_shell_menu_label(str(row.get("name", "")))
        if not normalized_label:
            if not previous_was_separator:
                items.append(WindowsContextMenuItem.separator())
                previous_was_separator = True
            continue

        raw_index = row.get("index")
        try:
            verb_index = int(raw_index)
        except (TypeError, ValueError):
            continue

        items.append(WindowsContextMenuItem(label=normalized_label, verb_index=verb_index))
        previous_was_separator = False

    while items and items[-1].is_separator:
        items.pop()

    return items


class WindowsExplorerShell:
    def __init__(self, runner: Runner | None = None) -> None:
        self._runner = runner or subprocess.run

    def list_folder_menu_items(self, folder_path: Path) -> list[WindowsContextMenuItem]:
        self._require_windows()
        completed = self._run_powershell(
            _LIST_FOLDER_MENU_SCRIPT,
            folder_path=folder_path,
        )
        return parse_context_menu_items(completed.stdout)

    def invoke_folder_menu_item(self, folder_path: Path, verb_index: int) -> None:
        self._require_windows()
        self._run_powershell(
            _INVOKE_FOLDER_MENU_SCRIPT,
            folder_path=folder_path,
            verb_index=verb_index,
        )

    def _run_powershell(
        self,
        script: str,
        *,
        folder_path: Path,
        verb_index: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GBM_TARGET_PATH"] = str(folder_path)
        if verb_index is not None:
            env["GBM_VERB_INDEX"] = str(verb_index)
        else:
            env.pop("GBM_VERB_INDEX", None)

        completed = self._runner(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _POWERSHELL_ENCODING_PREFIX + script,
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "Unknown Windows shell error.").strip()
            raise OSError(stderr)
        return completed

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows Explorer context menu is only available on Windows.")
