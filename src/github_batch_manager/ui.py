from __future__ import annotations

import concurrent.futures
import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from github_batch_manager.discovery import RepositoryDiscoveryService
from github_batch_manager.git_service import GitRepositoryService
from github_batch_manager.models import GitCommitView, GitLogEntry, GitLogResult, OperationResult, RepositoryRecord, RepositorySnapshot
from github_batch_manager.store import RepositoryStore
from github_batch_manager.windows_shell import WindowsContextMenuItem, WindowsExplorerShell


PULL_STRATEGY_OPTIONS: list[tuple[str, str]] = [
    ("merge", "合并拉取"),
    ("ff_only", "仅快进"),
    ("rebase", "变基拉取"),
]

PULL_STRATEGY_LABEL_TO_KEY = {label: key for key, label in PULL_STRATEGY_OPTIONS}
PULL_STRATEGY_KEY_TO_LABEL = {key: label for key, label in PULL_STRATEGY_OPTIONS}
REPO_HEADER_DRAG_THRESHOLD = 8


def normalize_repo_column_order(columns: tuple[str, ...], raw_order: object) -> list[str]:
    if not isinstance(raw_order, list):
        return list(columns)

    normalized = [column for column in raw_order if isinstance(column, str) and column in columns]
    missing = [column for column in columns if column not in normalized]
    return normalized + missing


def normalize_repo_hidden_columns(columns: tuple[str, ...], raw_hidden: object) -> list[str]:
    if not isinstance(raw_hidden, list):
        return []

    hidden: list[str] = []
    for column in raw_hidden:
        if isinstance(column, str) and column in columns and column not in hidden:
            hidden.append(column)
    return hidden


def merge_visible_repo_columns(
    column_order: list[str],
    hidden_columns: set[str],
    visible_order: list[str],
) -> list[str]:
    normalized_visible = [
        column
        for column in visible_order
        if column in column_order and column not in hidden_columns
    ]
    remaining_visible = [
        column
        for column in column_order
        if column not in hidden_columns and column not in normalized_visible
    ]
    merged_visible = normalized_visible + remaining_visible
    visible_iter = iter(merged_visible)
    merged: list[str] = []
    for column in column_order:
        if column in hidden_columns:
            merged.append(column)
        else:
            merged.append(next(visible_iter))
    return merged


class MultilineInputDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, title: str, prompt: str) -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        self.geometry("720x360")
        self.result: str | None = None

        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text=prompt).pack(anchor="w")
        self.text = tk.Text(container, height=14, wrap="word")
        self.text.pack(fill="both", expand=True, pady=(8, 12))
        self.text.focus_set()

        button_row = ttk.Frame(container)
        button_row.pack(fill="x")
        ttk.Button(button_row, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(button_row, text="导入", command=self._confirm).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _event: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _confirm(self) -> None:
        self.result = self.text.get("1.0", "end").strip()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class GitBatchManagerApp:
    def __init__(self) -> None:
        enable_windows_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("GitHub 批量仓库管理工具")
        self.root.minsize(1240, 720)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.font_family = "Microsoft YaHei UI" if sys.platform == "win32" else "TkDefaultFont"
        self.mono_font_family = "Consolas" if sys.platform == "win32" else "TkFixedFont"
        self._configure_fonts()

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("TLabel", font=self.ui_font)
        self.style.configure("TButton", font=self.ui_font)
        self.style.configure("TLabelframe.Label", font=self.ui_bold_font)
        self.style.configure("Treeview", font=self.ui_font, rowheight=self.tree_rowheight)
        self.style.configure("Treeview.Heading", font=self.ui_bold_font)
        self.style.configure("Accent.TButton", font=self.ui_bold_font)
        self.style.configure("LogTree.Treeview", font=self.mono_font, rowheight=self.tree_rowheight)
        self.style.configure("LogTree.Treeview.Heading", font=self.ui_bold_font)

        self.repo_columns = ("selected", "name", "branch", "dirty", "ahead", "behind", "last_commit", "status", "path")
        self.repo_column_headings = {
            "selected": "选择",
            "name": "仓库",
            "branch": "分支",
            "dirty": "改动",
            "ahead": "领先",
            "behind": "落后",
            "last_commit": "最新提交",
            "status": "状态",
            "path": "路径",
        }
        self.repo_column_widths = self._build_repository_column_widths(self.repo_column_headings)
        self.repo_column_order = list(self.repo_columns)
        self.repo_hidden_columns: set[str] = set()
        self.repo_displaycolumns = list(self.repo_columns)
        self.log_columns = ("graph", "current", "remote", "tag", "subject", "author", "date")
        self.log_column_headings = {
            "graph": "版本树",
            "current": "当前",
            "remote": "远端",
            "tag": "标签",
            "subject": "提交信息",
            "author": "作者",
            "date": "日期",
        }
        self.log_column_widths = self._build_log_column_widths(self.log_column_headings)
        self.log_column_order = list(self.log_columns)
        self.log_hidden_columns: set[str] = set()
        self.log_displaycolumns = list(self.log_columns)
        self.commit_file_columns = ("path", "status", "additions", "deletions")
        self.commit_file_column_headings = {
            "path": "路径",
            "status": "状态",
            "additions": "新增行",
            "deletions": "删除行",
        }
        self.commit_file_column_widths = self._build_commit_file_column_widths(self.commit_file_column_headings)
        self.commit_file_column_order = list(self.commit_file_columns)
        self.commit_file_hidden_columns: set[str] = set()
        self.commit_file_displaycolumns = list(self.commit_file_columns)
        self.repo_sort_column = "name"
        self.repo_sort_descending = False
        self.saved_window_geometry = ""
        self.saved_split_ratio = 0.7
        self.pull_strategy = "merge"
        self.context_menu_repository_path: str | None = None
        self.context_menu_column: str | None = None
        self.context_menu_selection_suppressed_path: str | None = None
        self.windows_explorer_shell = WindowsExplorerShell()
        self.windows_explorer_menu_cache: dict[str, list[WindowsContextMenuItem]] = {}
        self.windows_explorer_menu_errors: dict[str, str] = {}
        self.pending_windows_explorer_menu_paths: set[str] = set()
        self.repo_header_drag_column: str | None = None
        self.repo_header_drag_start_x = 0
        self.repo_header_drag_active = False
        self.log_header_drag_column: str | None = None
        self.log_header_drag_start_x = 0
        self.log_header_drag_active = False
        self.commit_file_header_drag_column: str | None = None
        self.commit_file_header_drag_start_x = 0
        self.commit_file_header_drag_active = False
        self.detail_value_labels: list[ttk.Label] = []

        self.store = RepositoryStore()
        self.discovery_service = RepositoryDiscoveryService()
        self.git_service = GitRepositoryService()
        self.repositories, self.ui_state = self.store.load_app_state()
        self.repository_index = {repository.path: repository for repository in self.repositories}

        self.status_var = tk.StringVar(value="准备就绪")
        self.detail_name_var = tk.StringVar(value="未选择仓库")
        self.detail_path_var = tk.StringVar(value="-")
        self.detail_branch_var = tk.StringVar(value="-")
        self.detail_sync_var = tk.StringVar(value="-")
        self.detail_status_var = tk.StringVar(value="-")
        self.failed_only_var = tk.BooleanVar(value=False)
        self.log_summary_var = tk.StringVar(value="请选择一个仓库以查看日志树。")
        self.pull_strategy_var = tk.StringVar(value=PULL_STRATEGY_KEY_TO_LABEL[self.pull_strategy])

        self.worker_queue: queue.Queue[
            tuple[str, object, Callable[[object], None] | None, str]
        ] = queue.Queue()
        self.busy = False
        self.selected_row_path: str | None = None
        self.current_log_repository_path: str | None = None
        self.pending_store_save_id: str | None = None
        self.pending_commit_view_requests: set[tuple[str, str]] = set()
        self.action_buttons: list[ttk.Button] = []
        self._restore_ui_state()

        self._build_layout()
        self._render_repository_table()
        self._apply_startup_window_state()
        self.root.after(150, self._poll_worker_queue)
        self.root.after(300, self._refresh_startup_state)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(
            header,
            text="GitHub 批量仓库管理工具",
            font=self.title_font,
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="集中管理多个本地 GitHub 仓库，批量刷新、拉取、提交、推送，并查看日志树。",
        ).pack(anchor="w", pady=(4, 0))

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 12))
        self._add_toolbar_button(toolbar, "扫描目录", self._scan_folder, accent=True)
        self._add_toolbar_button(toolbar, "导入路径", self._import_paths)
        self._add_toolbar_button(toolbar, "移除选中", self._remove_selected)
        self._add_toolbar_button(toolbar, "全选", self._select_all)
        self._add_toolbar_button(toolbar, "清空选择", self._clear_selection)
        self._add_toolbar_button(toolbar, "刷新状态", self._refresh_selected)
        self._add_toolbar_button(toolbar, "批量拉取", self._pull_selected)
        self._add_toolbar_button(toolbar, "批量提交", self._commit_selected)
        self._add_toolbar_button(toolbar, "批量推送", self._push_selected)
        ttk.Label(toolbar, text="拉取策略").pack(side="left", padx=(8, 4))
        self.pull_strategy_combo = ttk.Combobox(
            toolbar,
            state="readonly",
            width=10,
            values=[label for _key, label in PULL_STRATEGY_OPTIONS],
            textvariable=self.pull_strategy_var,
        )
        self.pull_strategy_combo.pack(side="left")
        self.pull_strategy_combo.bind("<<ComboboxSelected>>", self._on_pull_strategy_changed, add="+")
        ttk.Checkbutton(
            toolbar,
            text="只看失败项",
            variable=self.failed_only_var,
            command=self._on_failed_filter_changed,
        ).pack(side="left", padx=(8, 0))

        split = ttk.Panedwindow(outer, orient="horizontal")
        split.pack(fill="both", expand=True)
        self.main_split = split

        left_panel = ttk.Frame(split, padding=(0, 0, 12, 0))
        right_panel = ttk.Frame(split)
        split.add(left_panel, weight=7)
        split.add(right_panel, weight=3)

        repository_frame = ttk.LabelFrame(left_panel, text="仓库列表", padding=12)
        repository_frame.pack(fill="both", expand=True)

        tree_container = ttk.Frame(repository_frame)
        tree_container.pack(fill="both", expand=True)
        tree_container.columnconfigure(0, weight=1)
        tree_container.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_container, columns=self.repo_columns, show="headings", selectmode="browse")
        for column in self.repo_columns:
            self.tree.heading(column, text=self.repo_column_headings[column], command=lambda c=column: self._sort_repository_table(c))
            anchor = "center" if column in {"selected", "dirty", "ahead", "behind"} else "w"
            self.tree.column(column, width=self.repo_column_widths[column], anchor=anchor, stretch=column in {"last_commit", "status", "path"})
        self.tree["displaycolumns"] = self.repo_displaycolumns
        self._update_repository_heading_texts()

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        tree_x_scroll = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(
            xscrollcommand=tree_x_scroll.set,
            yscrollcommand=tree_scroll.set,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        tree_x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("repo_failed", foreground="#991b1b", background="#fee2e2")
        self.tree.tag_configure("repo_running", foreground="#92400e", background="#fef3c7")

        self.tree.bind("<ButtonPress-1>", self._on_tree_button_press, add="+")
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<B1-Motion>", self._on_tree_drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_button_release, add="+")
        self.tree.bind("<Button-3>", self._on_tree_right_click, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected, add="+")

        activity_frame = ttk.LabelFrame(left_panel, text="操作日志", padding=12)
        activity_frame.pack(fill="both", expand=False, pady=(12, 0))
        activity_container = ttk.Frame(activity_frame)
        activity_container.pack(fill="both", expand=True)
        activity_container.columnconfigure(0, weight=1)
        activity_container.rowconfigure(0, weight=1)
        self.activity_text = tk.Text(activity_container, height=10, wrap="none")
        self.activity_text.configure(font=self.mono_font)
        self.activity_text.configure(state="disabled")
        activity_y_scroll = ttk.Scrollbar(activity_container, orient="vertical", command=self.activity_text.yview)
        activity_x_scroll = ttk.Scrollbar(activity_container, orient="horizontal", command=self.activity_text.xview)
        self.activity_text.configure(
            xscrollcommand=activity_x_scroll.set,
            yscrollcommand=activity_y_scroll.set,
        )
        self.activity_text.grid(row=0, column=0, sticky="nsew")
        activity_y_scroll.grid(row=0, column=1, sticky="ns")
        activity_x_scroll.grid(row=1, column=0, sticky="ew")

        notebook = ttk.Notebook(right_panel)
        notebook.pack(fill="both", expand=True)
        self.right_notebook = notebook

        detail_tab = ttk.Frame(notebook, padding=12)
        detail_tab.bind("<Configure>", self._on_detail_tab_configure, add="+")
        notebook.add(detail_tab, text="仓库详情")
        self._add_detail_row(detail_tab, "仓库", self.detail_name_var)
        self._add_detail_row(detail_tab, "路径", self.detail_path_var)
        self._add_detail_row(detail_tab, "分支", self.detail_branch_var)
        self._add_detail_row(detail_tab, "同步", self.detail_sync_var)
        self._add_detail_row(detail_tab, "状态", self.detail_status_var)

        log_tab = ttk.Frame(notebook, padding=12)
        notebook.add(log_tab, text="日志树")
        ttk.Label(log_tab, textvariable=self.log_summary_var).pack(anchor="w", pady=(0, 8))
        log_container = ttk.Frame(log_tab)
        log_container.pack(fill="both", expand=True)
        log_container.columnconfigure(0, weight=1)
        log_container.rowconfigure(0, weight=1)

        self.log_tree = ttk.Treeview(
            log_container,
            columns=self.log_columns,
            show="headings",
            selectmode="browse",
            style="LogTree.Treeview",
        )
        for column in self.log_columns:
            self.log_tree.heading(column, text=self.log_column_headings[column])
            self.log_tree.column(
                column,
                width=self.log_column_widths[column],
                anchor="w",
                stretch=column == "subject",
            )
        self.log_tree["displaycolumns"] = self.log_displaycolumns

        log_y_scroll = ttk.Scrollbar(log_container, orient="vertical", command=self.log_tree.yview)
        log_x_scroll = ttk.Scrollbar(log_container, orient="horizontal", command=self.log_tree.xview)
        self.log_tree.configure(
            xscrollcommand=log_x_scroll.set,
            yscrollcommand=log_y_scroll.set,
        )
        self.log_tree.grid(row=0, column=0, sticky="nsew")
        log_y_scroll.grid(row=0, column=1, sticky="ns")
        log_x_scroll.grid(row=1, column=0, sticky="ew")
        self.log_tree.tag_configure("log_head", background="#dbeafe", foreground="#1d4ed8", font=self.ui_bold_font)
        self.log_tree.tag_configure("log_tagged", background="#fef3c7", foreground="#92400e")
        self.log_tree.tag_configure("log_remote", background="#dcfce7", foreground="#166534")
        self.log_tree.bind("<ButtonPress-1>", lambda event, kind="log": self._on_aux_tree_button_press(kind, event), add="+")
        self.log_tree.bind("<B1-Motion>", lambda event, kind="log": self._on_aux_tree_drag_motion(kind, event), add="+")
        self.log_tree.bind("<ButtonRelease-1>", lambda event, kind="log": self._on_aux_tree_button_release(kind, event), add="+")
        self.log_tree.bind("<Button-3>", lambda event, kind="log": self._on_aux_tree_right_click(kind, event), add="+")
        self.log_tree.bind("<<TreeviewSelect>>", self._on_log_entry_selected, add="+")

        commit_tab = ttk.Frame(notebook, padding=12)
        notebook.add(commit_tab, text="提交详情")
        commit_split = ttk.Panedwindow(commit_tab, orient="vertical")
        commit_split.pack(fill="both", expand=True)

        commit_text_frame = ttk.LabelFrame(commit_split, text="提交说明", padding=12)
        commit_split.add(commit_text_frame, weight=3)
        self.commit_detail_text = tk.Text(
            commit_text_frame,
            wrap="none",
            font=self.mono_font,
            background="#111827",
            foreground="#f9fafb",
            insertbackground="#f9fafb",
        )
        commit_y_scroll = ttk.Scrollbar(commit_text_frame, orient="vertical", command=self.commit_detail_text.yview)
        commit_x_scroll = ttk.Scrollbar(commit_text_frame, orient="horizontal", command=self.commit_detail_text.xview)
        self.commit_detail_text.configure(
            yscrollcommand=commit_y_scroll.set,
            xscrollcommand=commit_x_scroll.set,
        )
        self.commit_detail_text.grid(row=0, column=0, sticky="nsew")
        commit_y_scroll.grid(row=0, column=1, sticky="ns")
        commit_x_scroll.grid(row=1, column=0, sticky="ew")
        commit_text_frame.columnconfigure(0, weight=1)
        commit_text_frame.rowconfigure(0, weight=1)

        commit_files_frame = ttk.LabelFrame(commit_split, text="文件变更列表", padding=12)
        commit_split.add(commit_files_frame, weight=2)
        commit_files_container = ttk.Frame(commit_files_frame)
        commit_files_container.pack(fill="both", expand=True)
        commit_files_container.columnconfigure(0, weight=1)
        commit_files_container.rowconfigure(0, weight=1)
        self.commit_files_tree = ttk.Treeview(
            commit_files_container,
            columns=self.commit_file_columns,
            show="headings",
            selectmode="browse",
        )
        for column in self.commit_file_columns:
            anchor = "center" if column in {"status", "additions", "deletions"} else "w"
            self.commit_files_tree.heading(column, text=self.commit_file_column_headings[column])
            self.commit_files_tree.column(
                column,
                width=self.commit_file_column_widths[column],
                anchor=anchor,
                stretch=column == "path",
            )
        self.commit_files_tree["displaycolumns"] = self.commit_file_displaycolumns

        files_y_scroll = ttk.Scrollbar(commit_files_container, orient="vertical", command=self.commit_files_tree.yview)
        files_x_scroll = ttk.Scrollbar(commit_files_container, orient="horizontal", command=self.commit_files_tree.xview)
        self.commit_files_tree.configure(
            xscrollcommand=files_x_scroll.set,
            yscrollcommand=files_y_scroll.set,
        )
        self.commit_files_tree.grid(row=0, column=0, sticky="nsew")
        files_y_scroll.grid(row=0, column=1, sticky="ns")
        files_x_scroll.grid(row=1, column=0, sticky="ew")
        self.commit_files_tree.bind("<ButtonPress-1>", lambda event, kind="commit_files": self._on_aux_tree_button_press(kind, event), add="+")
        self.commit_files_tree.bind("<B1-Motion>", lambda event, kind="commit_files": self._on_aux_tree_drag_motion(kind, event), add="+")
        self.commit_files_tree.bind("<ButtonRelease-1>", lambda event, kind="commit_files": self._on_aux_tree_button_release(kind, event), add="+")
        self.commit_files_tree.bind("<Button-3>", lambda event, kind="commit_files": self._on_aux_tree_right_click(kind, event), add="+")

        self._render_log_entries(None)

        status_bar = ttk.Frame(outer)
        status_bar.pack(fill="x", pady=(12, 0))
        ttk.Label(status_bar, textvariable=self.status_var).pack(side="left")

    def _add_toolbar_button(
        self,
        container: ttk.Frame,
        text: str,
        command: Callable[[], None],
        accent: bool = False,
    ) -> None:
        style_name = "Accent.TButton" if accent else "TButton"
        button = ttk.Button(container, text=text, command=command, style=style_name)
        button.pack(side="left", padx=(0, 8))
        self.action_buttons.append(button)

    def _debug_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[调试 {timestamp}] {message}"
        print(line)
        if hasattr(self, "activity_text") and threading.current_thread() is threading.main_thread():
            self._append_activity(line)

    def _debug_timing(self, label: str, started_at: float, detail: str = "") -> None:
        duration_ms = (time.perf_counter() - started_at) * 1000
        suffix = f" | {detail}" if detail else ""
        self._debug_log(f"{label} 用时 {duration_ms:.1f}ms{suffix}")

    def _add_detail_row(self, container: ttk.Frame, label: str, variable: tk.StringVar) -> None:
        row = ttk.Frame(container)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=f"{label}：", width=7).pack(side="left")
        value_label = ttk.Label(
            row,
            textvariable=variable,
            wraplength=460,
            justify="left",
        )
        value_label.pack(side="left", fill="x", expand=True)
        self.detail_value_labels.append(value_label)

    def _on_detail_tab_configure(self, event: tk.Event) -> None:
        wraplength = max(int(event.width) - 120, 180)
        for label in self.detail_value_labels:
            label.configure(wraplength=wraplength)

    def _configure_fonts(self) -> None:
        self.ui_font = tkfont.Font(root=self.root, family=self.font_family, size=10)
        self.ui_bold_font = tkfont.Font(root=self.root, family=self.font_family, size=10, weight="bold")
        self.title_font = tkfont.Font(root=self.root, family=self.font_family, size=20, weight="bold")
        self.mono_font = tkfont.Font(root=self.root, family=self.mono_font_family, size=10)
        self.tree_rowheight = max(self.ui_font.metrics("linespace") + 14, 32)

        font_sizes = {
            "TkDefaultFont": 10,
            "TkTextFont": 10,
            "TkMenuFont": 10,
            "TkHeadingFont": 10,
            "TkCaptionFont": 11,
            "TkSmallCaptionFont": 9,
            "TkIconFont": 10,
            "TkTooltipFont": 9,
            "TkFixedFont": 10,
        }
        for font_name, font_size in font_sizes.items():
            named_font = tkfont.nametofont(font_name)
            family = self.mono_font_family if font_name == "TkFixedFont" else self.font_family
            named_font.configure(family=family, size=font_size)

    def _refresh_startup_state(self) -> None:
        if self.repositories:
            self._refresh_paths([repository.path for repository in self.repositories], "启动时刷新仓库状态")

    def _apply_startup_window_state(self) -> None:
        if self.saved_window_geometry:
            self.root.geometry(self.saved_window_geometry)
            self.root.after(120, self._set_initial_split_ratio)
            return

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(max(int(screen_width * 0.82), 1440), 1920)
        height = min(max(int(screen_height * 0.84), 840), 1180)
        offset_x = max((screen_width - width) // 2, 0)
        offset_y = max((screen_height - height) // 2, 0)
        self.root.geometry(f"{width}x{height}+{offset_x}+{offset_y}")
        self.root.after(120, self._set_initial_split_ratio)

    def _set_initial_split_ratio(self) -> None:
        split_width = self.main_split.winfo_width() or self.root.winfo_width()
        if split_width < 400:
            self.root.after(120, self._set_initial_split_ratio)
            return

        try:
            self.main_split.sashpos(0, int(split_width * self.saved_split_ratio))
        except tk.TclError:
            pass

    def _build_repository_column_widths(self, headings: dict[str, str]) -> dict[str, int]:
        examples = {
            "selected": "[x]",
            "name": "transmission-web-control-ai",
            "branch": "001-thumbnail-manual-crop",
            "dirty": "有",
            "ahead": "88",
            "behind": "88",
            "last_commit": "88888888 feat: use custom dbus_id to fix Linux startup crash (#12)",
            "status": "拉取失败：Not possible to fast-forward, aborting.",
            "path": r"G:\04 AI\transmission-web-control-ai",
        }

        padding = {
            "selected": 32,
            "name": 48,
            "branch": 48,
            "dirty": 36,
            "ahead": 32,
            "behind": 32,
            "last_commit": 56,
            "status": 56,
            "path": 72,
        }

        widths: dict[str, int] = {}
        for column, heading in headings.items():
            sample_text = examples[column]
            text_width = max(
                self.ui_bold_font.measure(heading),
                self.ui_font.measure(sample_text),
            )
            widths[column] = text_width + padding[column]

        widths["status"] = max(widths["status"], 520)
        widths["path"] = min(widths["path"], 360)
        return widths

    def _build_log_column_widths(self, headings: dict[str, str]) -> dict[str, int]:
        examples = {
            "graph": "* |/",
            "current": "HEAD -> main",
            "remote": "origin/main, origin/HEAD",
            "tag": "v7.3.9",
            "subject": "feat: use custom dbus_id to fix Linux startup crash (#12)",
            "author": "catalog22",
            "date": "2026-04-21 11:11:15",
        }

        padding = {
            "graph": 32,
            "current": 48,
            "remote": 48,
            "tag": 48,
            "subject": 56,
            "author": 40,
            "date": 40,
        }

        widths: dict[str, int] = {}
        for column, heading in headings.items():
            text_width = max(
                self.ui_bold_font.measure(heading),
                self.ui_font.measure(examples[column]),
            )
            widths[column] = text_width + padding[column]

        return widths

    def _build_commit_file_column_widths(self, headings: dict[str, str]) -> dict[str, int]:
        examples = {
            "path": r"src/github_batch_manager/ui.py",
            "status": "重命名",
            "additions": "128",
            "deletions": "64",
        }

        padding = {
            "path": 64,
            "status": 48,
            "additions": 40,
            "deletions": 40,
        }

        widths: dict[str, int] = {}
        for column, heading in headings.items():
            widths[column] = max(
                self.ui_bold_font.measure(heading),
                self.ui_font.measure(examples[column]),
            ) + padding[column]

        return widths

    def _restore_ui_state(self) -> None:
        repo_table_state = self.ui_state.get("repo_table", {})
        if isinstance(repo_table_state, dict):
            column_order = repo_table_state.get("column_order")
            self.repo_column_order = normalize_repo_column_order(self.repo_columns, column_order)

            displaycolumns = repo_table_state.get("displaycolumns")
            if isinstance(displaycolumns, list):
                normalized = [column for column in displaycolumns if column in self.repo_columns]
                if normalized:
                    self.repo_column_order = normalize_repo_column_order(self.repo_columns, normalized)
                    self.repo_hidden_columns = {
                        column for column in self.repo_columns if column not in normalized
                    }

            hidden_columns = normalize_repo_hidden_columns(
                self.repo_columns,
                repo_table_state.get("hidden_columns"),
            )
            if hidden_columns:
                if len(hidden_columns) >= len(self.repo_columns):
                    hidden_columns = hidden_columns[:-1]
                self.repo_hidden_columns = set(hidden_columns)

            raw_widths = repo_table_state.get("column_widths", {})
            if isinstance(raw_widths, dict):
                for column in self.repo_columns:
                    raw_value = raw_widths.get(column)
                    if isinstance(raw_value, int) and raw_value >= 40:
                        self.repo_column_widths[column] = raw_value

            sort_column = repo_table_state.get("sort_column")
            if isinstance(sort_column, str) and sort_column in self.repo_columns:
                self.repo_sort_column = sort_column
            self.repo_sort_descending = bool(repo_table_state.get("sort_descending", False))
            self.saved_split_ratio = float(repo_table_state.get("split_ratio", 0.7)) if isinstance(repo_table_state.get("split_ratio"), (int, float)) else 0.7
            self.failed_only_var.set(bool(repo_table_state.get("failed_only", False)))
            raw_pull_strategy = repo_table_state.get("pull_strategy")
            if isinstance(raw_pull_strategy, str) and raw_pull_strategy in PULL_STRATEGY_KEY_TO_LABEL:
                self.pull_strategy = raw_pull_strategy
                self.pull_strategy_var.set(PULL_STRATEGY_KEY_TO_LABEL[self.pull_strategy])

        self.repo_displaycolumns = self._visible_repo_columns()
        self._restore_aux_table_state("log", self.ui_state.get("log_table", {}))
        self._restore_aux_table_state("commit_files", self.ui_state.get("commit_files_table", {}))

        window_state = self.ui_state.get("window", {})
        if isinstance(window_state, dict):
            geometry = window_state.get("geometry")
            if isinstance(geometry, str):
                self.saved_window_geometry = geometry

    def _collect_ui_state(self) -> dict[str, object]:
        displaycolumns = self._tree_displaycolumns() if hasattr(self, "tree") else list(self.repo_displaycolumns)
        return {
            "repo_table": {
                "displaycolumns": displaycolumns,
                "column_order": list(self.repo_column_order),
                "hidden_columns": [column for column in self.repo_column_order if column in self.repo_hidden_columns],
                "column_widths": {
                    column: int(self.tree.column(column, "width")) if hasattr(self, "tree") else width
                    for column, width in self.repo_column_widths.items()
                },
                "sort_column": self.repo_sort_column,
                "sort_descending": self.repo_sort_descending,
                "split_ratio": self._current_split_ratio(),
                "failed_only": self.failed_only_var.get(),
                "pull_strategy": self.pull_strategy,
            },
            "log_table": self._collect_aux_table_state("log"),
            "commit_files_table": self._collect_aux_table_state("commit_files"),
            "window": {
                "geometry": self.root.geometry(),
            },
        }

    def _current_split_ratio(self) -> float:
        split_width = self.main_split.winfo_width() if hasattr(self, "main_split") else 0
        if split_width <= 0:
            return self.saved_split_ratio
        try:
            return max(min(self.main_split.sashpos(0) / split_width, 0.9), 0.1)
        except tk.TclError:
            return self.saved_split_ratio

    def _visible_repo_columns(self) -> list[str]:
        visible = [column for column in self.repo_column_order if column not in self.repo_hidden_columns]
        return visible or [self.repo_column_order[0]]

    def _tree_displaycolumns(self) -> list[str]:
        if not hasattr(self, "tree"):
            return list(self.repo_displaycolumns)
        return list(self.tree["displaycolumns"])

    def _hidden_repo_columns_in_order(self) -> list[str]:
        return [column for column in self.repo_column_order if column in self.repo_hidden_columns]

    def _apply_repo_column_visibility(self) -> None:
        self.repo_displaycolumns = self._visible_repo_columns()
        if hasattr(self, "tree"):
            self.tree["displaycolumns"] = self.repo_displaycolumns

    def _set_repo_column_visible(self, column: str, visible: bool) -> None:
        if column not in self.repo_columns:
            return

        visible_columns = self._visible_repo_columns()
        if visible:
            if column not in self.repo_hidden_columns:
                return
            self.repo_hidden_columns.discard(column)
        else:
            if column not in visible_columns:
                return
            if len(visible_columns) <= 1:
                messagebox.showinfo("提示", "至少保留一列可见。")
                return
            self.repo_hidden_columns.add(column)

        self._apply_repo_column_visibility()
        self._schedule_store_save()
        self._debug_log(
            f"仓库列表列可见性已更新：{column} -> {'显示' if visible else '隐藏'}"
        )

    def _toggle_repo_column_visibility(self, column: str) -> None:
        self._set_repo_column_visible(column, column in self.repo_hidden_columns)

    def _show_all_repo_columns(self) -> None:
        if not self.repo_hidden_columns:
            return
        self.repo_hidden_columns.clear()
        self._apply_repo_column_visibility()
        self._schedule_store_save()
        self._debug_log("仓库列表列已全部显示")

    def _aux_table_meta(self, kind: str) -> dict[str, object]:
        mapping = {
            "log": {
                "tree_attr": "log_tree",
                "columns_attr": "log_columns",
                "headings_attr": "log_column_headings",
                "widths_attr": "log_column_widths",
                "order_attr": "log_column_order",
                "hidden_attr": "log_hidden_columns",
                "display_attr": "log_displaycolumns",
                "drag_column_attr": "log_header_drag_column",
                "drag_start_attr": "log_header_drag_start_x",
                "drag_active_attr": "log_header_drag_active",
                "builder": self._build_log_column_widths,
                "label": "日志树",
            },
            "commit_files": {
                "tree_attr": "commit_files_tree",
                "columns_attr": "commit_file_columns",
                "headings_attr": "commit_file_column_headings",
                "widths_attr": "commit_file_column_widths",
                "order_attr": "commit_file_column_order",
                "hidden_attr": "commit_file_hidden_columns",
                "display_attr": "commit_file_displaycolumns",
                "drag_column_attr": "commit_file_header_drag_column",
                "drag_start_attr": "commit_file_header_drag_start_x",
                "drag_active_attr": "commit_file_header_drag_active",
                "builder": self._build_commit_file_column_widths,
                "label": "文件变更列表",
            },
        }
        return mapping[kind]

    def _restore_aux_table_state(self, kind: str, raw_state: object) -> None:
        meta = self._aux_table_meta(kind)
        columns = getattr(self, meta["columns_attr"])
        order = normalize_repo_column_order(columns, [])
        hidden: set[str] = set()
        widths = getattr(self, meta["widths_attr"])

        if isinstance(raw_state, dict):
            order = normalize_repo_column_order(columns, raw_state.get("column_order"))

            displaycolumns = raw_state.get("displaycolumns")
            if isinstance(displaycolumns, list):
                normalized = [column for column in displaycolumns if column in columns]
                if normalized:
                    order = normalize_repo_column_order(columns, normalized)
                    hidden = {column for column in columns if column not in normalized}

            hidden_columns = normalize_repo_hidden_columns(columns, raw_state.get("hidden_columns"))
            if hidden_columns:
                if len(hidden_columns) >= len(columns):
                    hidden_columns = hidden_columns[:-1]
                hidden = set(hidden_columns)

            raw_widths = raw_state.get("column_widths", {})
            if isinstance(raw_widths, dict):
                for column in columns:
                    raw_value = raw_widths.get(column)
                    if isinstance(raw_value, int) and raw_value >= 40:
                        widths[column] = raw_value

        setattr(self, meta["order_attr"], order)
        setattr(self, meta["hidden_attr"], hidden)
        setattr(self, meta["display_attr"], self._visible_aux_columns(kind))

    def _collect_aux_table_state(self, kind: str) -> dict[str, object]:
        meta = self._aux_table_meta(kind)
        order = getattr(self, meta["order_attr"])
        hidden = getattr(self, meta["hidden_attr"])
        widths = getattr(self, meta["widths_attr"])
        tree_attr = str(meta["tree_attr"])
        display_attr = str(meta["display_attr"])

        if hasattr(self, tree_attr):
            tree = getattr(self, tree_attr)
            displaycolumns = list(tree["displaycolumns"])
            width_state = {
                column: int(tree.column(column, "width"))
                for column in getattr(self, meta["columns_attr"])
            }
        else:
            displaycolumns = list(getattr(self, display_attr))
            width_state = dict(widths)

        return {
            "displaycolumns": displaycolumns,
            "column_order": list(order),
            "hidden_columns": [column for column in order if column in hidden],
            "column_widths": width_state,
        }

    def _visible_aux_columns(self, kind: str) -> list[str]:
        meta = self._aux_table_meta(kind)
        order = getattr(self, meta["order_attr"])
        hidden = getattr(self, meta["hidden_attr"])
        visible = [column for column in order if column not in hidden]
        return visible or [order[0]]

    def _aux_tree_displaycolumns(self, kind: str) -> list[str]:
        meta = self._aux_table_meta(kind)
        tree_attr = str(meta["tree_attr"])
        display_attr = str(meta["display_attr"])
        if not hasattr(self, tree_attr):
            return list(getattr(self, display_attr))
        return list(getattr(self, tree_attr)["displaycolumns"])

    def _apply_aux_column_visibility(self, kind: str) -> None:
        meta = self._aux_table_meta(kind)
        visible = self._visible_aux_columns(kind)
        setattr(self, meta["display_attr"], visible)
        tree_attr = str(meta["tree_attr"])
        if hasattr(self, tree_attr):
            getattr(self, tree_attr)["displaycolumns"] = visible

    def _set_aux_column_visible(self, kind: str, column: str, visible: bool) -> None:
        meta = self._aux_table_meta(kind)
        columns = getattr(self, meta["columns_attr"])
        if column not in columns:
            return

        hidden = getattr(self, meta["hidden_attr"])
        visible_columns = self._visible_aux_columns(kind)
        if visible:
            if column not in hidden:
                return
            hidden.discard(column)
        else:
            if column not in visible_columns:
                return
            if len(visible_columns) <= 1:
                messagebox.showinfo("提示", "至少保留一列可见。")
                return
            hidden.add(column)

        self._apply_aux_column_visibility(kind)
        self._schedule_store_save()
        self._debug_log(f"{meta['label']}列可见性已更新：{column} -> {'显示' if visible else '隐藏'}")

    def _toggle_aux_column_visibility(self, kind: str, column: str) -> None:
        meta = self._aux_table_meta(kind)
        hidden = getattr(self, meta["hidden_attr"])
        self._set_aux_column_visible(kind, column, column in hidden)

    def _show_all_aux_columns(self, kind: str) -> None:
        meta = self._aux_table_meta(kind)
        hidden = getattr(self, meta["hidden_attr"])
        if not hidden:
            return
        hidden.clear()
        self._apply_aux_column_visibility(kind)
        self._schedule_store_save()
        self._debug_log(f"{meta['label']}已显示全部列")

    def _capture_aux_table_layout(self, kind: str) -> None:
        meta = self._aux_table_meta(kind)
        tree = getattr(self, meta["tree_attr"])
        displaycolumns = self._aux_tree_displaycolumns(kind)
        order = getattr(self, meta["order_attr"])
        hidden = getattr(self, meta["hidden_attr"])
        widths = getattr(self, meta["widths_attr"])

        setattr(
            self,
            meta["order_attr"],
            merge_visible_repo_columns(order, hidden, displaycolumns),
        )
        setattr(self, meta["display_attr"], displaycolumns)
        for column in getattr(self, meta["columns_attr"]):
            widths[column] = int(tree.column(column, "width"))
        self._schedule_store_save()
        self._debug_log(f"已捕获{meta['label']}布局变更")

    def _aux_tree_column_from_display_id(self, kind: str, display_id: str) -> str | None:
        if not display_id.startswith("#"):
            return None
        try:
            index = int(display_id[1:]) - 1
        except ValueError:
            return None

        displaycolumns = self._aux_tree_displaycolumns(kind)
        if index < 0 or index >= len(displaycolumns):
            return None
        return displaycolumns[index]

    def _reorder_aux_column_to_target(self, kind: str, source_column: str, target_column: str) -> None:
        if source_column == target_column:
            return

        meta = self._aux_table_meta(kind)
        started_at = time.perf_counter()
        displaycolumns = self._aux_tree_displaycolumns(kind)
        if source_column not in displaycolumns or target_column not in displaycolumns:
            return

        source_index = displaycolumns.index(source_column)
        target_index = displaycolumns.index(target_column)
        displaycolumns.pop(source_index)
        displaycolumns.insert(target_index, source_column)
        order = getattr(self, meta["order_attr"])
        hidden = getattr(self, meta["hidden_attr"])
        setattr(
            self,
            meta["order_attr"],
            merge_visible_repo_columns(order, hidden, displaycolumns),
        )
        self._apply_aux_column_visibility(kind)
        self._schedule_store_save()
        self._debug_timing("拖拽调整列顺序", started_at, f"{meta['label']} | {source_column} -> {target_column}")

    def _clear_aux_header_drag_state(self, kind: str) -> None:
        meta = self._aux_table_meta(kind)
        setattr(self, meta["drag_column_attr"], None)
        setattr(self, meta["drag_start_attr"], 0)
        setattr(self, meta["drag_active_attr"], False)
        tree_attr = str(meta["tree_attr"])
        if hasattr(self, tree_attr):
            getattr(self, tree_attr).configure(cursor="")

    def _on_aux_tree_button_press(self, kind: str, event: tk.Event) -> None:
        meta = self._aux_table_meta(kind)
        tree = getattr(self, meta["tree_attr"])
        region = tree.identify("region", event.x, event.y)
        if region != "heading":
            self._clear_aux_header_drag_state(kind)
            return

        column = self._aux_tree_column_from_display_id(kind, tree.identify_column(event.x))
        if column is None:
            self._clear_aux_header_drag_state(kind)
            return

        setattr(self, meta["drag_column_attr"], column)
        setattr(self, meta["drag_start_attr"], int(event.x))
        setattr(self, meta["drag_active_attr"], False)

    def _on_aux_tree_drag_motion(self, kind: str, event: tk.Event) -> str | None:
        meta = self._aux_table_meta(kind)
        tree = getattr(self, meta["tree_attr"])
        drag_column = getattr(self, meta["drag_column_attr"])
        if drag_column is None:
            return None

        if not getattr(self, meta["drag_active_attr"]):
            drag_start_x = int(getattr(self, meta["drag_start_attr"]))
            if abs(int(event.x) - drag_start_x) < REPO_HEADER_DRAG_THRESHOLD:
                return None
            setattr(self, meta["drag_active_attr"], True)
            tree.configure(cursor="sb_h_double_arrow")
            self._debug_log(f"开始拖拽{meta['label']}列头：{drag_column}")

        return "break"

    def _on_aux_tree_button_release(self, kind: str, event: tk.Event) -> str | None:
        meta = self._aux_table_meta(kind)
        tree = getattr(self, meta["tree_attr"])
        drag_column = getattr(self, meta["drag_column_attr"])
        drag_active = bool(getattr(self, meta["drag_active_attr"]))
        if drag_column is not None and drag_active:
            target_column = self._aux_tree_column_from_display_id(kind, tree.identify_column(event.x))
            self._clear_aux_header_drag_state(kind)
            if target_column is not None:
                self._reorder_aux_column_to_target(kind, drag_column, target_column)
            return "break"

        self._clear_aux_header_drag_state(kind)
        region = tree.identify("region", event.x, event.y)
        if region in {"separator", "heading"}:
            self._capture_aux_table_layout(kind)
        return None

    def _on_aux_tree_right_click(self, kind: str, event: tk.Event) -> str | None:
        meta = self._aux_table_meta(kind)
        tree = getattr(self, meta["tree_attr"])
        region = tree.identify("region", event.x, event.y)
        if region != "heading":
            return None

        column = self._aux_tree_column_from_display_id(kind, tree.identify_column(event.x))
        if column is None:
            return "break"

        self._show_aux_heading_context_menu(kind, column, event.x_root, event.y_root)
        return "break"

    def _show_aux_heading_context_menu(self, kind: str, column: str, x_root: int, y_root: int) -> None:
        meta = self._aux_table_meta(kind)
        headings = getattr(self, meta["headings_attr"])
        order = getattr(self, meta["order_attr"])
        hidden = getattr(self, meta["hidden_attr"])
        menu = tk.Menu(self.root, tearoff=False)
        visibility_menu = tk.Menu(menu, tearoff=False)
        for option_column in order:
            marker = "✓" if option_column not in hidden else "□"
            visibility_menu.add_command(
                label=f"{marker} {headings[option_column]}",
                command=lambda c=option_column: self._toggle_aux_column_visibility(kind, c),
            )
        menu.add_cascade(label="显示/隐藏列", menu=visibility_menu)
        hide_state = "disabled" if len(self._visible_aux_columns(kind)) <= 1 else "normal"
        menu.add_command(
            label=f"隐藏“{headings[column]}”",
            state=hide_state,
            command=lambda: self._set_aux_column_visible(kind, column, False),
        )
        menu.add_command(label="显示全部列", command=lambda: self._show_all_aux_columns(kind))
        menu.add_separator()
        menu.add_command(label="当前列左移", command=lambda: self._move_aux_column(kind, column, -1))
        menu.add_command(label="当前列右移", command=lambda: self._move_aux_column(kind, column, 1))
        menu.add_command(label="自动适应当前列", command=lambda: self._auto_fit_aux_column(kind, column))
        menu.add_separator()
        menu.add_command(label="恢复默认列布局", command=lambda: self._reset_aux_table_layout(kind))
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _move_aux_column(self, kind: str, column: str, direction: int) -> None:
        meta = self._aux_table_meta(kind)
        started_at = time.perf_counter()
        displaycolumns = self._aux_tree_displaycolumns(kind)
        if column not in displaycolumns:
            return

        current_index = displaycolumns.index(column)
        target_index = max(0, min(len(displaycolumns) - 1, current_index + direction))
        if target_index == current_index:
            return

        displaycolumns.insert(target_index, displaycolumns.pop(current_index))
        order = getattr(self, meta["order_attr"])
        hidden = getattr(self, meta["hidden_attr"])
        setattr(
            self,
            meta["order_attr"],
            merge_visible_repo_columns(order, hidden, displaycolumns),
        )
        self._apply_aux_column_visibility(kind)
        self._schedule_store_save()
        self._debug_timing("调整列顺序", started_at, f"{meta['label']} | {column} -> 位置 {target_index + 1}")

    def _auto_fit_aux_column(self, kind: str, column: str) -> None:
        meta = self._aux_table_meta(kind)
        tree = getattr(self, meta["tree_attr"])
        columns = getattr(self, meta["columns_attr"])
        headings = getattr(self, meta["headings_attr"])
        widths = getattr(self, meta["widths_attr"])
        started_at = time.perf_counter()
        column_index = columns.index(column)
        measure_font = self.mono_font if kind == "log" else self.ui_font
        max_width = self.ui_bold_font.measure(headings[column])
        for item_id in tree.get_children():
            values = tree.item(item_id, "values")
            if column_index < len(values):
                max_width = max(max_width, measure_font.measure(str(values[column_index])))

        width = max_width + 48
        tree.column(column, width=width)
        widths[column] = width
        self._schedule_store_save()
        self._debug_timing("自动适应列宽", started_at, f"{meta['label']} | {column} -> {width}px")

    def _reset_aux_table_layout(self, kind: str) -> None:
        meta = self._aux_table_meta(kind)
        started_at = time.perf_counter()
        headings = getattr(self, meta["headings_attr"])
        width_builder = meta["builder"]
        widths = width_builder(headings)
        setattr(self, meta["widths_attr"], widths)
        setattr(self, meta["order_attr"], list(getattr(self, meta["columns_attr"])))
        getattr(self, meta["hidden_attr"]).clear()
        setattr(self, meta["display_attr"], list(getattr(self, meta["columns_attr"])))
        tree = getattr(self, meta["tree_attr"])
        for column in getattr(self, meta["columns_attr"]):
            tree.column(column, width=widths[column])
        self._apply_aux_column_visibility(kind)
        self._schedule_store_save()
        self._debug_timing("重置表格布局", started_at, str(meta["label"]))

    def _sorted_repositories(self, repositories: list[RepositoryRecord]) -> list[RepositoryRecord]:
        return sorted(
            repositories,
            key=self._repository_sort_key,
            reverse=self.repo_sort_descending,
        )

    def _repository_sort_key(self, repository: RepositoryRecord) -> tuple[object, str]:
        column = self.repo_sort_column
        if column == "selected":
            return (0 if repository.selected else 1, repository.name.lower())
        if column == "dirty":
            return (0 if repository.dirty else 1, repository.name.lower())
        if column == "ahead":
            return (repository.ahead, repository.name.lower())
        if column == "behind":
            return (repository.behind, repository.name.lower())

        value = getattr(repository, {
            "name": "name",
            "branch": "branch",
            "last_commit": "last_commit",
            "status": "status_message",
            "path": "path",
        }.get(column, "name"), "")
        return (str(value).lower(), repository.name.lower())

    def _sort_repository_table(self, column: str, descending: bool | None = None) -> None:
        started_at = time.perf_counter()
        if descending is None:
            if self.repo_sort_column == column:
                self.repo_sort_descending = not self.repo_sort_descending
            else:
                self.repo_sort_column = column
                self.repo_sort_descending = False
        else:
            self.repo_sort_column = column
            self.repo_sort_descending = descending

        self._update_repository_heading_texts()
        self._render_repository_table()
        self._schedule_store_save()
        self._debug_timing(
            "仓库表排序",
            started_at,
            f"{column} | {'降序' if self.repo_sort_descending else '升序'}",
        )

    def _update_repository_heading_texts(self) -> None:
        if not hasattr(self, "tree"):
            return

        for column in self.repo_columns:
            heading_text = self.repo_column_headings[column]
            if column == self.repo_sort_column:
                heading_text += " ▼" if self.repo_sort_descending else " ▲"
            self.tree.heading(column, text=heading_text, command=lambda c=column: self._sort_repository_table(c))

    def _on_tree_button_press(self, event: tk.Event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "heading":
            self._clear_repo_header_drag_state()
            return

        column = self._tree_column_from_display_id(self.tree.identify_column(event.x))
        if column is None:
            self._clear_repo_header_drag_state()
            return

        self.repo_header_drag_column = column
        self.repo_header_drag_start_x = int(event.x)
        self.repo_header_drag_active = False

    def _on_tree_drag_motion(self, event: tk.Event) -> str | None:
        if self.repo_header_drag_column is None:
            return None

        if not self.repo_header_drag_active:
            if abs(int(event.x) - self.repo_header_drag_start_x) < REPO_HEADER_DRAG_THRESHOLD:
                return None
            self.repo_header_drag_active = True
            self.tree.configure(cursor="sb_h_double_arrow")
            self._debug_log(f"开始拖拽仓库列表列头：{self.repo_header_drag_column}")

        return "break"

    def _on_tree_button_release(self, event: tk.Event) -> str | None:
        if self.repo_header_drag_column is not None and self.repo_header_drag_active:
            source_column = self.repo_header_drag_column
            target_column = self._tree_column_from_display_id(self.tree.identify_column(event.x))
            self._clear_repo_header_drag_state()
            if target_column is not None:
                self._reorder_repo_column_to_target(source_column, target_column)
            return "break"

        self._clear_repo_header_drag_state()
        region = self.tree.identify("region", event.x, event.y)
        if region in {"separator", "heading"}:
            self._capture_repo_table_layout()
        return None

    def _capture_repo_table_layout(self) -> None:
        if not hasattr(self, "tree"):
            return

        self.repo_displaycolumns = self._tree_displaycolumns()
        self.repo_column_order = merge_visible_repo_columns(
            self.repo_column_order,
            self.repo_hidden_columns,
            self.repo_displaycolumns,
        )
        for column in self.repo_columns:
            self.repo_column_widths[column] = int(self.tree.column(column, "width"))
        self._schedule_store_save()
        self._debug_log("已捕获仓库表格布局变更")

    def _tree_column_from_display_id(self, display_id: str) -> str | None:
        if not display_id.startswith("#"):
            return None
        try:
            index = int(display_id[1:]) - 1
        except ValueError:
            return None

        displaycolumns = list(self.tree["displaycolumns"])
        if index < 0 or index >= len(displaycolumns):
            return None
        return displaycolumns[index]

    def _reorder_repo_column_to_target(self, source_column: str, target_column: str) -> None:
        if source_column == target_column:
            return

        started_at = time.perf_counter()
        displaycolumns = self._tree_displaycolumns()
        if source_column not in displaycolumns or target_column not in displaycolumns:
            return

        source_index = displaycolumns.index(source_column)
        target_index = displaycolumns.index(target_column)
        displaycolumns.pop(source_index)
        displaycolumns.insert(target_index, source_column)
        self.repo_column_order = merge_visible_repo_columns(
            self.repo_column_order,
            self.repo_hidden_columns,
            displaycolumns,
        )
        self._apply_repo_column_visibility()
        self._schedule_store_save()
        self._debug_timing("拖拽调整列顺序", started_at, f"{source_column} -> {target_column}")

    def _clear_repo_header_drag_state(self) -> None:
        self.repo_header_drag_column = None
        self.repo_header_drag_start_x = 0
        self.repo_header_drag_active = False
        if hasattr(self, "tree"):
            self.tree.configure(cursor="")

    def _on_tree_right_click(self, event: tk.Event) -> str:
        started_at = time.perf_counter()
        region = self.tree.identify("region", event.x, event.y)
        if region == "heading":
            column = self._tree_column_from_display_id(self.tree.identify_column(event.x))
            if column:
                self.context_menu_column = column
                self.context_menu_repository_path = None
                self._debug_log(f"context_menu heading | column={column}")
                self._show_heading_context_menu(column, event.x_root, event.y_root)
                self._debug_timing("context_menu heading", started_at, f"column={column}")
                return "break"

        repository_path = self.tree.identify_row(event.y)
        if repository_path:
            self.context_menu_repository_path = repository_path
            self.context_menu_column = None
            self._debug_log(
                f"context_menu row | path={repository_path} | selection={list(self.tree.selection())}"
            )
            self._prefetch_windows_explorer_menu_items(repository_path)
            if tuple(self.tree.selection()) != (repository_path,):
                self.context_menu_selection_suppressed_path = repository_path
                self.tree.selection_set(repository_path)
            self.tree.focus(repository_path)
            self._show_row_context_menu(repository_path, event.x_root, event.y_root)
            self._debug_timing("context_menu row", started_at, repository_path)
            return "break"

        self._debug_timing("context_menu empty", started_at, f"region={region}")
        return "break"

    def _show_row_context_menu(self, repository_path: str, x_root: int, y_root: int) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return

        menu = tk.Menu(self.root, tearoff=False)
        toggle_label = "取消勾选" if repository.selected else "勾选仓库"
        menu.add_command(label=toggle_label, command=lambda: self._toggle_repository(repository_path))
        menu.add_separator()
        menu.add_command(label="刷新", command=lambda: self._refresh_single_repository(repository_path))
        menu.add_command(label=f"拉取（{self._current_pull_strategy_label()}）", command=lambda: self._pull_single_repository(repository_path))
        menu.add_command(label="提交...", command=lambda: self._commit_single_repository(repository_path))
        menu.add_command(label="推送", command=lambda: self._push_single_repository(repository_path))
        menu.add_separator()
        self._attach_windows_explorer_submenu(menu, repository_path)
        menu.add_command(label="打开文件夹", command=lambda: self._open_repository_folder(repository_path))
        menu.add_command(label="复制仓库路径", command=lambda: self._copy_repository_path(repository_path))
        menu.add_separator()
        menu.add_command(label="全选全部仓库", command=self._select_all)
        menu.add_command(label="清空全部勾选", command=self._clear_selection)
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _show_heading_context_menu(self, column: str, x_root: int, y_root: int) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label=f"按“{self.repo_column_headings[column]}”升序", command=lambda: self._sort_repository_table(column, False))
        menu.add_command(label=f"按“{self.repo_column_headings[column]}”降序", command=lambda: self._sort_repository_table(column, True))
        menu.add_separator()
        visibility_menu = tk.Menu(menu, tearoff=False)
        for option_column in self.repo_column_order:
            marker = "✓" if option_column not in self.repo_hidden_columns else "□"
            visibility_menu.add_command(
                label=f"{marker} {self.repo_column_headings[option_column]}",
                command=lambda c=option_column: self._toggle_repo_column_visibility(c),
            )
        menu.add_cascade(label="显示/隐藏列", menu=visibility_menu)
        hide_state = "disabled" if len(self._visible_repo_columns()) <= 1 else "normal"
        menu.add_command(label=f"隐藏“{self.repo_column_headings[column]}”", state=hide_state, command=lambda: self._set_repo_column_visible(column, False))
        menu.add_command(label="显示全部列", command=self._show_all_repo_columns)
        menu.add_separator()
        menu.add_command(label="当前列左移", command=lambda: self._move_repo_column(column, -1))
        menu.add_command(label="当前列右移", command=lambda: self._move_repo_column(column, 1))
        menu.add_command(label="自动适应当前列", command=lambda: self._auto_fit_repo_column(column))
        menu.add_separator()
        menu.add_command(label="恢复默认列布局", command=self._reset_repo_table_layout)
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _move_repo_column(self, column: str, direction: int) -> None:
        started_at = time.perf_counter()
        displaycolumns = self._tree_displaycolumns()
        if column not in displaycolumns:
            return

        current_index = displaycolumns.index(column)
        target_index = max(0, min(len(displaycolumns) - 1, current_index + direction))
        if target_index == current_index:
            return

        displaycolumns.insert(target_index, displaycolumns.pop(current_index))
        self.repo_column_order = merge_visible_repo_columns(
            self.repo_column_order,
            self.repo_hidden_columns,
            displaycolumns,
        )
        self._apply_repo_column_visibility()
        self._schedule_store_save()
        self._debug_timing("调整列顺序", started_at, f"{column} -> 位置 {target_index + 1}")

    def _auto_fit_repo_column(self, column: str) -> None:
        started_at = time.perf_counter()
        heading_width = self.ui_bold_font.measure(self.repo_column_headings[column])
        max_width = heading_width
        for repository in self.repositories:
            value = self._repository_value_for_column(repository, column)
            max_width = max(max_width, self.ui_font.measure(value))

        width = max_width + 48
        self.tree.column(column, width=width)
        self.repo_column_widths[column] = width
        self._schedule_store_save()
        self._debug_timing("自动适应列宽", started_at, f"{column} -> {width}px")

    def _reset_repo_table_layout(self) -> None:
        started_at = time.perf_counter()
        self.repo_column_widths = self._build_repository_column_widths(self.repo_column_headings)
        self.repo_column_order = list(self.repo_columns)
        self.repo_hidden_columns.clear()
        self.repo_displaycolumns = list(self.repo_columns)
        self.repo_sort_column = "name"
        self.repo_sort_descending = False
        for column in self.repo_columns:
            self.tree.column(column, width=self.repo_column_widths[column])
        self._apply_repo_column_visibility()
        self._update_repository_heading_texts()
        self._render_repository_table()
        self._schedule_store_save()
        self._debug_timing("重置表格布局", started_at)

    def _repository_value_for_column(self, repository: RepositoryRecord, column: str) -> str:
        return {
            "selected": "[x]" if repository.selected else "[ ]",
            "name": repository.name,
            "branch": repository.branch or "-",
            "dirty": "有" if repository.dirty else "无",
            "ahead": str(repository.ahead),
            "behind": str(repository.behind),
            "last_commit": repository.last_commit or "-",
            "status": repository.status_message or "-",
            "path": repository.path,
        }[column]

    def _copy_repository_path(self, repository_path: str) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(repository.path)
        self.status_var.set(f"已复制路径：{repository.path}")
        self._debug_log(f"已复制仓库路径：{repository.path}")

    def _on_pull_strategy_changed(self, _event: tk.Event | None = None) -> None:
        selected_label = self.pull_strategy_var.get()
        strategy = PULL_STRATEGY_LABEL_TO_KEY.get(selected_label, "merge")
        self.pull_strategy = strategy
        self._schedule_store_save()
        self.status_var.set(f"拉取策略已切换为：{selected_label}")
        self._debug_log(f"拉取策略已切换：{selected_label}")

    def _current_pull_strategy_label(self) -> str:
        return PULL_STRATEGY_KEY_TO_LABEL.get(self.pull_strategy, "合并拉取")

    def _attach_windows_explorer_submenu(self, menu: tk.Menu, repository_path: str) -> None:
        explorer_menu = tk.Menu(
            menu,
            tearoff=False,
            postcommand=lambda: self._populate_windows_explorer_submenu(repository_path, explorer_menu),
        )
        explorer_menu.add_command(label="加载中...", state="disabled")
        menu.add_cascade(label="WINDOWS资源管理", menu=explorer_menu)

    def _populate_windows_explorer_submenu_legacy_unused(self, repository_path: str, explorer_menu: tk.Menu) -> None:
        started_at = time.perf_counter()
        explorer_menu.delete(0, "end")
        if sys.platform != "win32":
            explorer_menu.add_command(label="仅支持 Windows", state="disabled")
            return

        self._debug_log(f"context_menu explorer_submenu open | path={repository_path}")
        menu_items = self.windows_explorer_menu_cache.get(repository_path)
        if menu_items is None:
            self._prefetch_windows_explorer_menu_items(repository_path)
            if repository_path in self.windows_explorer_menu_errors:
                explorer_menu.add_command(label="资源管理器菜单加载失败", state="disabled")
                self._debug_timing("context_menu explorer_submenu", started_at, f"failed | {repository_path}")
                return
            explorer_menu.add_command(label="加载中...", state="disabled")
            self._debug_timing("context_menu explorer_submenu", started_at, f"pending | {repository_path}")
            return
            explorer_menu.add_command(label="加载资源管理器菜单失败", state="disabled")
            self._debug_log(f"加载 Windows 资源管理器菜单失败：{repository_path} | {exc}")
            return

        self._debug_timing(
            "context_menu explorer_submenu",
            started_at,
            f"{repository_path} | items={len(menu_items)}",
        )
        if not menu_items:
            explorer_menu.add_command(label="没有可用菜单项", state="disabled")
            return

        for item in menu_items:
            if item.is_separator:
                explorer_menu.add_separator()
                continue
            if item.verb_index is None:
                continue
            explorer_menu.add_command(
                label=item.label,
                command=lambda idx=item.verb_index, label=item.label: self._invoke_windows_explorer_menu_item(
                    repository_path,
                    idx,
                    label,
                ),
            )

    def _load_windows_explorer_menu_items(self, repository_path: str) -> list[WindowsContextMenuItem]:
        cached_items = self.windows_explorer_menu_cache.get(repository_path)
        if cached_items is not None:
            self._debug_log(
                f"context_menu explorer cache_hit | path={repository_path} | items={len(cached_items)}"
            )
            return cached_items

        self.windows_explorer_menu_errors.pop(repository_path, None)
        started_at = time.perf_counter()
        menu_items = self.windows_explorer_shell.list_folder_menu_items(Path(repository_path))
        self.windows_explorer_menu_cache[repository_path] = menu_items
        self._debug_timing(
            "context_menu explorer_load",
            started_at,
            f"{repository_path} | items={len(menu_items)}",
        )
        return menu_items

    def _prefetch_windows_explorer_menu_items(self, repository_path: str) -> None:
        if sys.platform != "win32":
            return
        if repository_path in self.windows_explorer_menu_cache:
            return
        if repository_path in self.pending_windows_explorer_menu_paths:
            return

        self.pending_windows_explorer_menu_paths.add(repository_path)
        self.windows_explorer_menu_errors.pop(repository_path, None)
        started_at = time.perf_counter()
        self._debug_log(f"context_menu explorer_prefetch start | path={repository_path}")

        def worker() -> None:
            try:
                menu_items = self.windows_explorer_shell.list_folder_menu_items(Path(repository_path))
            except OSError as exc:
                self.worker_queue.put(
                    (
                        "progress",
                        {
                            "kind": "explorer_menu_prefetch_failed",
                            "repository_path": repository_path,
                            "error": str(exc),
                            "started_at": started_at,
                        },
                        None,
                        "预热 Windows 资源管理菜单",
                    )
                )
                return

            self.worker_queue.put(
                (
                    "progress",
                    {
                        "kind": "explorer_menu_prefetched",
                        "repository_path": repository_path,
                        "menu_items": menu_items,
                        "started_at": started_at,
                    },
                    None,
                    "预热 Windows 资源管理菜单",
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _populate_windows_explorer_submenu(self, repository_path: str, explorer_menu: tk.Menu) -> None:
        started_at = time.perf_counter()
        explorer_menu.delete(0, "end")
        if sys.platform != "win32":
            explorer_menu.add_command(label="仅支持 Windows", state="disabled")
            self._debug_timing("context_menu explorer_submenu", started_at, "non_windows")
            return

        self._debug_log(f"context_menu explorer_submenu open | path={repository_path}")
        menu_items = self.windows_explorer_menu_cache.get(repository_path)
        if menu_items is None:
            self._prefetch_windows_explorer_menu_items(repository_path)
            if repository_path in self.windows_explorer_menu_errors:
                explorer_menu.add_command(label="资源管理器菜单加载失败", state="disabled")
                self._debug_timing("context_menu explorer_submenu", started_at, f"failed | {repository_path}")
                return

            explorer_menu.add_command(label="加载中...", state="disabled")
            self._debug_timing("context_menu explorer_submenu", started_at, f"pending | {repository_path}")
            return

        self._debug_timing(
            "context_menu explorer_submenu",
            started_at,
            f"{repository_path} | items={len(menu_items)}",
        )
        if not menu_items:
            explorer_menu.add_command(label="没有可用菜单项", state="disabled")
            return

        for item in menu_items:
            if item.is_separator:
                explorer_menu.add_separator()
                continue
            if item.verb_index is None:
                continue
            explorer_menu.add_command(
                label=item.label,
                command=lambda idx=item.verb_index, label=item.label: self._invoke_windows_explorer_menu_item(
                    repository_path,
                    idx,
                    label,
                ),
            )

    def _invoke_windows_explorer_menu_item(self, repository_path: str, verb_index: int, label: str) -> None:
        try:
            self.windows_explorer_shell.invoke_folder_menu_item(Path(repository_path), verb_index)
        except OSError as exc:
            messagebox.showerror("执行失败", f"无法执行 Windows 资源管理器菜单项：{exc}")
            self._debug_log(f"执行 Windows 资源管理器菜单项失败：{repository_path} | {label} | {exc}")
            return

        self.status_var.set(f"已执行 Windows 资源管理器菜单项：{label}")
        self._debug_log(f"已执行 Windows 资源管理器菜单项：{repository_path} | {label}")

    def _open_repository_folder(self, repository_path: str) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return

        folder_path = Path(repository.path)
        if not folder_path.exists():
            messagebox.showerror("打开失败", f"仓库目录不存在：{folder_path}")
            self._debug_log(f"打开仓库文件夹失败：目录不存在 | {folder_path}")
            return

        try:
            if sys.platform == "win32":
                os.startfile(str(folder_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder_path)])
            else:
                subprocess.Popen(["xdg-open", str(folder_path)])
        except OSError as exc:
            messagebox.showerror("打开失败", f"无法打开仓库目录：{exc}")
            self._debug_log(f"打开仓库文件夹失败：{folder_path} | {exc}")
            return

        self.status_var.set(f"已打开仓库目录：{folder_path}")
        self._debug_log(f"已打开仓库文件夹：{folder_path}")

    def _refresh_single_repository(self, repository_path: str) -> None:
        self._refresh_paths([repository_path], "刷新单个仓库状态")

    def _pull_single_repository(self, repository_path: str) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return
        strategy = self.pull_strategy
        self._run_batch_operation("拉取", [repository], lambda record: self.git_service.pull(Path(record.path), record.name, strategy))

    def _commit_single_repository(self, repository_path: str) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return
        commit_message = simpledialog.askstring("提交仓库", f"请输入 {repository.name} 的提交说明：", parent=self.root)
        if commit_message is None:
            return
        self._run_batch_operation(
            "提交",
            [repository],
            lambda record: self.git_service.commit_all(Path(record.path), record.name, commit_message),
        )

    def _push_single_repository(self, repository_path: str) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return
        self._run_batch_operation("推送", [repository], lambda record: self.git_service.push(Path(record.path), record.name))

    def _render_repository_table(self) -> None:
        started_at = time.perf_counter()
        current_selection = self.tree.selection()
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        visible_repositories = self._visible_repositories()
        visible_paths = {repository.path for repository in visible_repositories}

        for repository in self._sorted_repositories(visible_repositories):
            self.tree.insert(
                "",
                "end",
                iid=repository.path,
                values=self._repository_values(repository),
                tags=self._repository_tags(repository),
            )

        if current_selection:
            existing = [item for item in current_selection if self.tree.exists(item)]
            if existing:
                self.tree.selection_set(existing)
                self._debug_timing(
                    "重绘仓库表格",
                    started_at,
                    f"可见 {len(visible_repositories)} 项 | 失败筛选={self.failed_only_var.get()}",
                )
                return

        if self.selected_row_path and self.selected_row_path not in visible_paths:
            self.selected_row_path = None
            self._clear_details()

        self._debug_timing(
            "重绘仓库表格",
            started_at,
            f"可见 {len(visible_repositories)} 项 | 失败筛选={self.failed_only_var.get()}",
        )

    def _repository_values(self, repository: RepositoryRecord) -> tuple[str, ...]:
        return (
            "[x]" if repository.selected else "[ ]",
            repository.name,
            repository.branch or "-",
            "有" if repository.dirty else "无",
            str(repository.ahead),
            str(repository.behind),
            repository.last_commit or "-",
            repository.status_message or "-",
            repository.path,
        )

    def _repository_tags(self, repository: RepositoryRecord) -> tuple[str, ...]:
        tags: list[str] = []
        if repository.last_operation_status == "failed":
            tags.append("repo_failed")
        elif repository.last_operation_status == "running":
            tags.append("repo_running")
        return tuple(tags)

    def _visible_repositories(self) -> list[RepositoryRecord]:
        if not self.failed_only_var.get():
            return list(self.repositories)
        return [repository for repository in self.repositories if repository.last_operation_status == "failed"]

    def _on_tree_click(self, event: tk.Event) -> str | None:
        started_at = time.perf_counter()
        region = self.tree.identify("region", event.x, event.y)
        column = self.tree.identify_column(event.x)
        item_id = self.tree.identify_row(event.y)
        if region == "cell" and column == "#1" and item_id:
            self._toggle_repository(item_id)
            self._debug_timing("点击仓库勾选框", started_at, f"path={item_id}")
            return "break"

        self._debug_timing("点击仓库表格", started_at, f"region={region} column={column}")
        return None

    def _on_row_selected(self, _event: tk.Event) -> None:
        started_at = time.perf_counter()
        selected = self.tree.selection()
        if not selected:
            self._debug_timing("切换仓库选中行", started_at, "无选中项")
            return

        repository = self.repository_index.get(selected[0])
        if repository is None:
            self._debug_timing("切换仓库选中行", started_at, "仓库未命中索引")
            return

        if self.context_menu_selection_suppressed_path == repository.path:
            self.context_menu_selection_suppressed_path = None
            self.selected_row_path = repository.path
            self._show_repository_details(repository, load_log_view=False)
            self._debug_timing(
                "repo selection",
                started_at,
                f"{repository.name} | context_menu_skip_log_load",
            )
            return

        if self.context_menu_selection_suppressed_path is not None:
            self._debug_log(
                "context_menu selection suppression reset "
                f"| expected={self.context_menu_selection_suppressed_path} | actual={repository.path}"
            )
            self.context_menu_selection_suppressed_path = None

        self.selected_row_path = repository.path
        self._show_repository_details(repository)
        if repository.log_entries:
            self._render_log_entries(repository)
            self._debug_timing("切换仓库选中行", started_at, f"{repository.name} | 使用缓存日志")
        elif not self.busy:
            self._load_log_for_repository(repository.path)
            self._debug_timing("切换仓库选中行", started_at, f"{repository.name} | 触发日志加载")
        else:
            self._debug_timing("切换仓库选中行", started_at, f"{repository.name} | busy={self.busy}")

    def _toggle_repository(self, repository_path: str) -> None:
        started_at = time.perf_counter()
        repository = self.repository_index.get(repository_path)
        if repository is None:
            self._debug_timing("切换仓库勾选状态", started_at, "仓库未命中索引")
            return

        repository.selected = not repository.selected
        self.tree.item(
            repository.path,
            values=self._repository_values(repository),
            tags=self._repository_tags(repository),
        )
        self._schedule_store_save()
        self._debug_timing(
            "切换仓库勾选状态",
            started_at,
            f"{repository.name} -> {'选中' if repository.selected else '取消'}",
        )

    def _on_failed_filter_changed(self) -> None:
        started_at = time.perf_counter()
        self._render_repository_table()
        self._debug_timing("切换失败项筛选", started_at, f"failed_only={self.failed_only_var.get()}")

    def _refresh_repository_selection_rows(self) -> None:
        started_at = time.perf_counter()
        updated_count = 0
        for repository in self._visible_repositories():
            if self.tree.exists(repository.path):
                self.tree.item(
                    repository.path,
                    values=self._repository_values(repository),
                    tags=self._repository_tags(repository),
                )
                updated_count += 1
        self._debug_timing("刷新仓库勾选列", started_at, f"更新 {updated_count} 行")

    def _schedule_store_save(self) -> None:
        if self.pending_store_save_id is not None:
            self.root.after_cancel(self.pending_store_save_id)

        self.pending_store_save_id = self.root.after(180, self._flush_store_save)
        self._debug_log("已安排仓库列表延迟保存（180ms）")

    def _flush_store_save(self) -> None:
        started_at = time.perf_counter()
        self.pending_store_save_id = None
        try:
            self.store.save_app_state(self.repositories, self._collect_ui_state())
        except OSError as exc:
            self.status_var.set("保存仓库列表失败")
            self._debug_log(f"保存仓库列表失败：{exc}")
            return
        self._debug_timing("写入仓库列表文件", started_at, f"仓库数 {len(self.repositories)}")

    def _save_repositories_now(self) -> None:
        started_at = time.perf_counter()
        if self.pending_store_save_id is not None:
            self.root.after_cancel(self.pending_store_save_id)
            self.pending_store_save_id = None
        try:
            self.store.save_app_state(self.repositories, self._collect_ui_state())
        except OSError as exc:
            self.status_var.set("保存仓库列表失败")
            self._debug_log(f"保存仓库列表失败：{exc}")
            return
        self._debug_timing("立即写入仓库列表文件", started_at, f"仓库数 {len(self.repositories)}")

    def _on_close(self) -> None:
        self._capture_repo_table_layout()
        self._save_repositories_now()
        self.root.destroy()

    def _on_log_entry_selected(self, _event: tk.Event) -> None:
        if not self.selected_row_path:
            return

        selected = self.log_tree.selection()
        if not selected:
            return

        repository = self.repository_index.get(self.selected_row_path)
        if repository is None:
            return

        commit_hash = selected[0]
        self._show_commit_details(repository, commit_hash)

    def _scan_folder(self) -> None:
        chosen_path = filedialog.askdirectory(title="选择需要扫描的根目录")
        if not chosen_path:
            return
        self._run_discovery([chosen_path], "扫描目录并导入仓库")

    def _import_paths(self) -> None:
        dialog = MultilineInputDialog(
            self.root,
            "导入多个路径",
            "每行填写一个目录路径。可以直接填写仓库目录，也可以填写包含多个仓库的父目录。",
        )
        self.root.wait_window(dialog)
        if not dialog.result:
            return

        raw_paths = [line.strip() for line in dialog.result.splitlines() if line.strip()]
        if not raw_paths:
            return
        self._run_discovery(raw_paths, "导入多个仓库路径")

    def _remove_selected(self) -> None:
        selected = [repository for repository in self.repositories if repository.selected]
        if not selected:
            messagebox.showinfo("提示", "请先勾选需要移除的仓库。")
            return

        confirmed = messagebox.askyesno("确认移除", f"确定移除 {len(selected)} 个已勾选仓库吗？")
        if not confirmed:
            return

        selected_paths = {repository.path for repository in selected}
        self.repositories = [repository for repository in self.repositories if repository.path not in selected_paths]
        self.repository_index = {repository.path: repository for repository in self.repositories}
        self._save_repositories_now()
        self._render_repository_table()
        self._append_activity(f"已移除 {len(selected)} 个仓库。")
        self.status_var.set(f"已移除 {len(selected)} 个仓库")
        if self.selected_row_path in selected_paths:
            self.selected_row_path = None
            self._clear_details()

    def _select_all(self) -> None:
        started_at = time.perf_counter()
        for repository in self.repositories:
            repository.selected = True
        self._refresh_repository_selection_rows()
        self._schedule_store_save()
        self.status_var.set("已全选所有仓库")
        self._debug_timing("全选仓库", started_at, f"仓库数 {len(self.repositories)}")

    def _clear_selection(self) -> None:
        started_at = time.perf_counter()
        for repository in self.repositories:
            repository.selected = False
        self._refresh_repository_selection_rows()
        self._schedule_store_save()
        self.status_var.set("已清空所有勾选")
        self._debug_timing("清空仓库选择", started_at, f"仓库数 {len(self.repositories)}")

    def _refresh_selected(self) -> None:
        selected_paths = self._selected_paths()
        if not selected_paths:
            messagebox.showinfo("提示", "请先勾选至少一个仓库。")
            return
        self._refresh_paths(selected_paths, "刷新仓库状态")

    def _pull_selected(self) -> None:
        selected_records = self._selected_records()
        if not selected_records:
            messagebox.showinfo("提示", "请先勾选至少一个仓库。")
            return
        strategy = self.pull_strategy
        self._run_batch_operation(
            "拉取",
            selected_records,
            lambda record: self.git_service.pull(Path(record.path), record.name, strategy),
            parallelism=min(6, len(selected_records)),
        )

    def _commit_selected(self) -> None:
        selected_records = self._selected_records()
        if not selected_records:
            messagebox.showinfo("提示", "请先勾选至少一个仓库。")
            return

        commit_message = simpledialog.askstring("批量提交", "请输入提交说明：", parent=self.root)
        if commit_message is None:
            return

        self._run_batch_operation(
            "提交",
            selected_records,
            lambda record: self.git_service.commit_all(Path(record.path), record.name, commit_message),
        )

    def _push_selected(self) -> None:
        selected_records = self._selected_records()
        if not selected_records:
            messagebox.showinfo("提示", "请先勾选至少一个仓库。")
            return
        self._run_batch_operation("推送", selected_records, lambda record: self.git_service.push(Path(record.path), record.name))

    def _run_discovery(self, raw_paths: list[str], description: str) -> None:
        started_at = time.perf_counter()
        def job() -> list[Path]:
            return self.discovery_service.discover(raw_paths)

        def callback(result: object) -> None:
            repositories = result
            assert isinstance(repositories, list)
            new_count = 0
            for repository_path in repositories:
                normalized = str(repository_path)
                if normalized in self.repository_index:
                    continue
                record = RepositoryRecord(path=normalized)
                self.repositories.append(record)
                self.repository_index[record.path] = record
                new_count += 1

            self._save_repositories_now()
            self._render_repository_table()
            self._append_activity(f"{description}完成：新增 {new_count} 个仓库，当前共 {len(self.repositories)} 个。")
            self.status_var.set(f"{description}完成：新增 {new_count} 个仓库")
            self._debug_timing(description, started_at, f"新增 {new_count} 个仓库")

        self._run_async(description, job, callback)

    def _refresh_paths(self, paths: list[str], description: str) -> None:
        started_at = time.perf_counter()
        def job() -> dict[str, RepositorySnapshot]:
            snapshots: dict[str, RepositorySnapshot] = {}
            for repository_path in paths:
                snapshots[repository_path] = self.git_service.get_snapshot(Path(repository_path))
            return snapshots

        def callback(result: object) -> None:
            snapshots = result
            assert isinstance(snapshots, dict)
            self._apply_snapshots(snapshots)
            self._append_activity(f"{description}完成：已刷新 {len(snapshots)} 个仓库。")
            self.status_var.set(f"{description}完成")
            self._debug_timing(description, started_at, f"刷新 {len(snapshots)} 个仓库")

        self._run_async(description, job, callback)

    def _run_batch_operation(
        self,
        action_name: str,
        records: list[RepositoryRecord],
        handler: Callable[[RepositoryRecord], OperationResult],
        parallelism: int = 1,
    ) -> None:
        started_at = time.perf_counter()
        def job() -> tuple[list[OperationResult], dict[str, RepositorySnapshot]]:
            results: list[OperationResult] = []
            snapshots: dict[str, RepositorySnapshot] = {}
            total = len(records)

            def execute_record(index: int, record: RepositoryRecord) -> tuple[OperationResult, RepositorySnapshot]:
                self.worker_queue.put(
                    (
                        "progress",
                        {
                            "kind": "batch_item_started",
                            "action_name": action_name,
                            "repository_path": record.path,
                            "repository_name": record.name,
                            "index": index,
                            "total": total,
                        },
                        None,
                        f"批量{action_name}",
                    )
                )
                result = handler(record)
                snapshot = self.git_service.get_snapshot(Path(record.path))
                self.worker_queue.put(
                    (
                        "progress",
                        {
                            "kind": "batch_item_finished",
                            "action_name": action_name,
                            "repository_path": record.path,
                            "repository_name": record.name,
                            "index": index,
                            "total": total,
                            "result": result,
                            "snapshot": snapshot,
                        },
                        None,
                        f"批量{action_name}",
                    )
                )
                return result, snapshot

            if parallelism <= 1:
                for index, record in enumerate(records, start=1):
                    result, snapshot = execute_record(index, record)
                    results.append(result)
                    snapshots[record.path] = snapshot
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as executor:
                    future_map = {
                        executor.submit(execute_record, index, record): record
                        for index, record in enumerate(records, start=1)
                    }
                    for future in concurrent.futures.as_completed(future_map):
                        record = future_map[future]
                        result, snapshot = future.result()
                        results.append(result)
                        snapshots[record.path] = snapshot

            return results, snapshots

        def callback(result: object) -> None:
            results, snapshots = result
            assert isinstance(results, list)
            assert isinstance(snapshots, dict)
            summary = self._summarize_operation(results)
            self._append_activity(f"[{action_name}] 全部完成：{summary}")
            self.status_var.set(f"{action_name}完成：{summary}")
            self._debug_timing(
                f"批量{action_name}",
                started_at,
                f"仓库 {len(records)} 个 | 并发 {parallelism} | {summary}",
            )

        self._run_async(f"批量{action_name}", job, callback)

    def _load_log_for_repository(self, repository_path: str) -> None:
        started_at = time.perf_counter()
        def job() -> GitLogResult:
            return self.git_service.load_log_entries(Path(repository_path))

        def callback(result: object) -> None:
            log_result = result
            assert isinstance(log_result, GitLogResult)
            repository = self.repository_index.get(repository_path)
            if repository is None:
                return

            repository.log_entries = log_result.entries
            repository.log_message = log_result.message
            repository.log_lines = [
                f"{entry.graph} {entry.short_hash} {entry.subject}".strip()
                for entry in log_result.entries
            ]
            if log_result.entries and (
                not repository.selected_commit_hash
                or repository.selected_commit_hash not in {entry.commit_hash for entry in log_result.entries}
            ):
                repository.selected_commit_hash = log_result.entries[0].commit_hash
            repository.commit_changed_files = []
            repository.commit_detail_text = ""
            repository.commit_views = {
                commit_hash: view
                for commit_hash, view in repository.commit_views.items()
                if commit_hash in {entry.commit_hash for entry in log_result.entries}
            }

            if self.selected_row_path == repository_path:
                self._render_log_entries(repository)
            self.status_var.set(log_result.message or "日志树已更新")
            self._debug_timing(
                "加载日志树",
                started_at,
                f"{repository.name} | 提交数 {len(log_result.entries)}",
            )

        self._run_async("读取日志树", job, callback, show_busy_message=False)

    def _apply_snapshots(self, snapshots: dict[str, RepositorySnapshot]) -> None:
        for repository_path, snapshot in snapshots.items():
            self._apply_snapshot_to_repository(repository_path, snapshot, reset_operation_state=True)
        if self.failed_only_var.get():
            self._render_repository_table()

    def _apply_snapshot_to_repository(
        self,
        repository_path: str,
        snapshot: RepositorySnapshot,
        reset_operation_state: bool,
    ) -> None:
        repository = self.repository_index.get(repository_path)
        if repository is None:
            return

        repository.branch = snapshot.branch
        repository.dirty = snapshot.dirty
        repository.ahead = snapshot.ahead
        repository.behind = snapshot.behind
        repository.last_commit = snapshot.last_commit
        repository.last_commit_age = snapshot.last_commit_age
        repository.status_message = snapshot.status_message
        if reset_operation_state:
            repository.last_operation_status = "idle"
            repository.last_error_message = ""
        self._update_repository_row(repository)

        if self.selected_row_path == repository.path:
            self._show_repository_details(repository)

    def _update_repository_row(self, repository: RepositoryRecord) -> None:
        if self.tree.exists(repository.path):
            self.tree.item(
                repository.path,
                values=self._repository_values(repository),
                tags=self._repository_tags(repository),
            )

    def _show_repository_details(self, repository: RepositoryRecord, load_log_view: bool = True) -> None:
        started_at = time.perf_counter()
        sync_bits = [f"领先 {repository.ahead}", f"落后 {repository.behind}", f"改动 {'有' if repository.dirty else '无'}"]
        self.detail_name_var.set(repository.name)
        self.detail_path_var.set(repository.path)
        self.detail_branch_var.set(repository.branch or "-")
        self.detail_sync_var.set(" | ".join(sync_bits))
        detail_status = repository.status_message or "-"
        if repository.last_error_message:
            detail_status = f"{detail_status}\n{repository.last_error_message}"
        elif repository.last_commit:
            tail = repository.last_commit
            if repository.last_commit_age:
                tail = f"{tail} ({repository.last_commit_age})"
            detail_status = f"{detail_status} | {tail}"
        self.detail_status_var.set(detail_status)
        if load_log_view and repository.log_entries:
            self._render_log_entries(repository)
        elif load_log_view and self.current_log_repository_path != repository.path:
            self._render_log_entries(None, "正在准备该仓库的日志树...")
        self._debug_timing("刷新右侧仓库详情", started_at, f"{repository.name} | load_log_view={load_log_view}")

    def _clear_details(self) -> None:
        self.detail_name_var.set("未选择仓库")
        self.detail_path_var.set("-")
        self.detail_branch_var.set("-")
        self.detail_sync_var.set("-")
        self.detail_status_var.set("-")
        self._render_log_entries(None)

    def _render_log_entries(self, repository: RepositoryRecord | None, empty_message: str | None = None) -> None:
        started_at = time.perf_counter()
        self.current_log_repository_path = repository.path if repository is not None else None
        for item_id in self.log_tree.get_children():
            self.log_tree.delete(item_id)

        if repository is None or not repository.log_entries:
            self.log_summary_var.set(empty_message or "请选择一个仓库以查看日志树。")
            self._set_commit_detail_text(empty_message or "请选择一个仓库以查看日志树。")
            self._set_commit_files([])
            self._debug_timing("渲染提交日志树", started_at, "空状态")
            return

        self.log_summary_var.set(self._format_log_summary(repository))
        total_entries = len(repository.log_entries)
        linear_history = self._is_linear_history(repository.log_entries)
        for index, entry in enumerate(repository.log_entries):
            tags = self._log_row_tags(entry)
            self.log_tree.insert(
                "",
                "end",
                iid=entry.commit_hash,
                values=(
                    self._format_log_graph(entry, index, total_entries, linear_history),
                    entry.current_ref or "-",
                    entry.remote_refs or "-",
                    entry.tag_refs or "-",
                    entry.subject,
                    entry.author,
                    entry.date,
                ),
                tags=tuple(tags),
            )

        commit_hash = repository.selected_commit_hash or repository.log_entries[0].commit_hash
        if self.log_tree.exists(commit_hash):
            self.log_tree.selection_set(commit_hash)
            self.log_tree.see(commit_hash)
            self._show_commit_details(repository, commit_hash)
        else:
            self.log_tree.selection_set(repository.log_entries[0].commit_hash)
            self._show_commit_details(repository, repository.log_entries[0].commit_hash)
        self._debug_timing("渲染提交日志树", started_at, f"{repository.name} | {len(repository.log_entries)} 条")

    def _show_commit_details(self, repository: RepositoryRecord, commit_hash: str) -> None:
        repository.selected_commit_hash = commit_hash
        cached_view = repository.commit_views.get(commit_hash)
        if cached_view is not None:
            repository.commit_detail_text = cached_view.detail_text
            repository.commit_changed_files = cached_view.files
            self._set_commit_detail_text(cached_view.detail_text)
            self._set_commit_files(cached_view.files)
            self._debug_log(f"命中提交详情缓存：{repository.name} | {commit_hash[:8]}")
            return

        self._set_commit_detail_text(f"正在加载提交详情：{commit_hash[:8]} ...")
        self._set_commit_files([])
        self._load_commit_view_async(repository, commit_hash)

    def _load_commit_view_async(self, repository: RepositoryRecord, commit_hash: str) -> None:
        request_key = (repository.path, commit_hash)
        if request_key in self.pending_commit_view_requests:
            self._debug_log(f"提交详情已在加载中：{repository.name} | {commit_hash[:8]}")
            return

        self.pending_commit_view_requests.add(request_key)
        started_at = time.perf_counter()
        self._debug_log(f"开始后台加载提交详情：{repository.name} | {commit_hash[:8]}")

        def worker() -> None:
            try:
                commit_view = self.git_service.load_commit_view(Path(repository.path), commit_hash)
            except Exception as exc:  # pragma: no cover - UI fallback
                self.worker_queue.put(
                    (
                        "progress",
                        {
                            "kind": "commit_view_failed",
                            "repository_path": repository.path,
                            "repository_name": repository.name,
                            "commit_hash": commit_hash,
                            "error": str(exc),
                            "started_at": started_at,
                        },
                        None,
                        "读取提交详情",
                    )
                )
                return

            self.worker_queue.put(
                (
                    "progress",
                    {
                        "kind": "commit_view_loaded",
                        "repository_path": repository.path,
                        "repository_name": repository.name,
                        "commit_hash": commit_hash,
                        "commit_view": commit_view,
                        "started_at": started_at,
                    },
                    None,
                    "读取提交详情",
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _set_commit_files(self, files: list[object]) -> None:
        for item_id in self.commit_files_tree.get_children():
            self.commit_files_tree.delete(item_id)

        for index, item in enumerate(files):
            self.commit_files_tree.insert(
                "",
                "end",
                iid=f"file-{index}",
                values=(item.path, item.status, item.additions, item.deletions),
            )

    def _set_commit_detail_text(self, text: str) -> None:
        self.commit_detail_text.configure(state="normal")
        self.commit_detail_text.delete("1.0", "end")
        self.commit_detail_text.insert("1.0", text)
        self.commit_detail_text.configure(state="disabled")

    def _format_log_summary(self, repository: RepositoryRecord) -> str:
        count = len(repository.log_entries)
        branch = repository.branch or "未知分支"
        tail = f"当前分支：{branch}，已加载 {count} 条提交记录。"
        if repository.last_commit:
            tail += f" 最新提交：{repository.last_commit}"
        return tail

    def _log_row_tags(self, entry: GitLogEntry) -> list[str]:
        if entry.is_head:
            return ["log_head"]
        if entry.has_tag:
            return ["log_tagged"]
        if entry.has_remote_ref:
            return ["log_remote"]
        return []

    def _is_linear_history(self, entries: list[GitLogEntry]) -> bool:
        if not entries:
            return False
        prefixes = {entry.graph.strip() for entry in entries if entry.graph.strip()}
        return prefixes.issubset({"*", "│●", "├●", "└●", "●"})

    def _format_log_graph(
        self,
        entry: GitLogEntry,
        index: int,
        total_entries: int,
        linear_history: bool,
    ) -> str:
        raw_graph = entry.graph.rstrip()
        translated = (
            raw_graph.replace("|", "│")
            .replace("/", "╱")
            .replace("\\", "╲")
            .replace("-", "─")
            .replace("_", "─")
            .replace("*", "●")
        ).strip()

        if linear_history and translated in {"", "●"}:
            if total_entries == 1:
                return "●"
            if index == 0:
                return "●"
            if index == total_entries - 1:
                return "└●"
            return "├●"

        return translated or "●"

    def _append_activity(self, message: str) -> None:
        self.activity_text.configure(state="normal")
        self.activity_text.insert("end", f"{message}\n")
        self.activity_text.see("end")
        self.activity_text.configure(state="disabled")

    def _run_async(
        self,
        description: str,
        job: Callable[[], object],
        callback: Callable[[object], None],
        show_busy_message: bool = True,
    ) -> None:
        if self.busy:
            self._debug_log(f"阻止启动异步任务：{description} | busy={self.busy}")
            if show_busy_message:
                messagebox.showinfo("请稍候", "当前任务仍在执行，请稍后再试。")
            return

        self.busy = True
        self._set_buttons_state("disabled")
        self.status_var.set(f"{description}中，请稍候...")
        self._debug_log(f"启动异步任务：{description}")

        def worker() -> None:
            try:
                result = job()
            except Exception as exc:  # pragma: no cover - UI fallback
                self.worker_queue.put(("error", exc, callback, description))
                return
            self.worker_queue.put(("success", result, callback, description))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                status, payload, callback, description = self.worker_queue.get_nowait()
                if status == "progress":
                    self._handle_worker_progress(payload)
                    continue

                self.busy = False
                self._set_buttons_state("normal")
                if status == "error":
                    self.status_var.set(f"{description}失败")
                    self._debug_log(f"异步任务失败：{description} | {payload}")
                    messagebox.showerror("执行失败", str(payload))
                else:
                    assert callback is not None
                    self._debug_log(f"异步任务完成：{description}")
                    callback(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._poll_worker_queue)

    def _handle_worker_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        kind = payload.get("kind")
        if kind == "batch_item_started":
            self._handle_batch_item_started(payload)
        elif kind == "batch_item_finished":
            self._handle_batch_item_finished(payload)
        elif kind == "commit_view_loaded":
            self._handle_commit_view_loaded(payload)
        elif kind == "commit_view_failed":
            self._handle_commit_view_failed(payload)
        elif kind == "explorer_menu_prefetched":
            self._handle_explorer_menu_prefetched(payload)
        elif kind == "explorer_menu_prefetch_failed":
            self._handle_explorer_menu_prefetch_failed(payload)

    def _handle_batch_item_started(self, payload: dict[str, object]) -> None:
        repository_path = str(payload["repository_path"])
        repository = self.repository_index.get(repository_path)
        action_name = str(payload["action_name"])
        repository_name = str(payload["repository_name"])
        index = int(payload["index"])
        total = int(payload["total"])

        if repository is not None:
            repository.last_operation_status = "running"
            repository.last_error_message = ""
            repository.status_message = f"{action_name}中 ({index}/{total})"
            self._update_repository_row(repository)
            if self.selected_row_path == repository.path:
                self._show_repository_details(repository)

        self._append_activity(f"[{action_name}] 正在处理 {repository_name} ({index}/{total})...")
        self.status_var.set(f"{action_name}中：{repository_name} ({index}/{total})")

    def _handle_batch_item_finished(self, payload: dict[str, object]) -> None:
        repository_path = str(payload["repository_path"])
        action_name = str(payload["action_name"])
        index = int(payload["index"])
        total = int(payload["total"])

        snapshot = payload.get("snapshot")
        if isinstance(snapshot, RepositorySnapshot):
            self._apply_snapshot_to_repository(repository_path, snapshot, reset_operation_state=False)

        result = payload.get("result")
        if isinstance(result, OperationResult):
            self._apply_operation_result(result)
            self._append_activity(
                f"[{action_name}] {result.repository_name} - {self._status_label(result.status)}：{result.message}"
            )

        self.status_var.set(f"{action_name}中：已完成 {index}/{total}")

    def _apply_operation_result(self, result: OperationResult) -> None:
        repository = self.repository_index.get(result.repository_path)
        if repository is None:
            return

        repository.last_operation_status = result.status
        repository.last_error_message = result.message if result.status == "failed" else ""
        repository.status_message = self._summarize_result_message(result)
        if self.failed_only_var.get():
            self._render_repository_table()
        else:
            self._update_repository_row(repository)

        if self.selected_row_path == repository.path:
            self._show_repository_details(repository)

    def _summarize_result_message(self, result: OperationResult) -> str:
        prefix = {
            "success": f"{result.action}成功",
            "failed": f"{result.action}失败",
            "skipped": f"{result.action}跳过",
        }.get(result.status, result.action)
        first_line = result.message.splitlines()[0].strip()
        if len(first_line) > 44:
            first_line = first_line[:44].rstrip() + "..."
        return f"{prefix}：{first_line}"

    def _handle_commit_view_loaded(self, payload: dict[str, object]) -> None:
        repository_path = str(payload["repository_path"])
        repository_name = str(payload["repository_name"])
        commit_hash = str(payload["commit_hash"])
        started_at = float(payload["started_at"])
        request_key = (repository_path, commit_hash)
        self.pending_commit_view_requests.discard(request_key)

        repository = self.repository_index.get(repository_path)
        commit_view = payload.get("commit_view")
        if repository is None or not isinstance(commit_view, GitCommitView):
            self._debug_timing("后台加载提交详情", started_at, f"{repository_name} | 无法应用结果")
            return

        repository.commit_views[commit_hash] = commit_view
        if self.selected_row_path == repository_path and repository.selected_commit_hash == commit_hash:
            repository.commit_detail_text = commit_view.detail_text
            repository.commit_changed_files = commit_view.files
            self._set_commit_detail_text(commit_view.detail_text)
            self._set_commit_files(commit_view.files)

        self._debug_timing(
            "后台加载提交详情",
            started_at,
            f"{repository.name} | {commit_hash[:8]} | 文件 {len(commit_view.files)} 个",
        )

    def _handle_commit_view_failed(self, payload: dict[str, object]) -> None:
        repository_path = str(payload["repository_path"])
        repository_name = str(payload["repository_name"])
        commit_hash = str(payload["commit_hash"])
        started_at = float(payload["started_at"])
        request_key = (repository_path, commit_hash)
        self.pending_commit_view_requests.discard(request_key)

        repository = self.repository_index.get(repository_path)
        error_text = f"加载提交详情失败：{payload['error']}"
        if repository is not None and self.selected_row_path == repository_path and repository.selected_commit_hash == commit_hash:
            self._set_commit_detail_text(error_text)
            self._set_commit_files([])

        self._debug_timing("后台加载提交详情", started_at, f"{repository_name} | 失败 | {error_text}")

    def _handle_explorer_menu_prefetched(self, payload: dict[str, object]) -> None:
        repository_path = str(payload["repository_path"])
        started_at = float(payload["started_at"])
        menu_items = payload.get("menu_items")

        self.pending_windows_explorer_menu_paths.discard(repository_path)
        self.windows_explorer_menu_errors.pop(repository_path, None)
        if not isinstance(menu_items, list):
            self._debug_timing("context_menu explorer_prefetch", started_at, f"{repository_path} | invalid_payload")
            return

        valid_items = [item for item in menu_items if isinstance(item, WindowsContextMenuItem)]
        self.windows_explorer_menu_cache[repository_path] = valid_items
        self._debug_timing(
            "context_menu explorer_prefetch",
            started_at,
            f"{repository_path} | items={len(valid_items)}",
        )

    def _handle_explorer_menu_prefetch_failed(self, payload: dict[str, object]) -> None:
        repository_path = str(payload["repository_path"])
        started_at = float(payload["started_at"])
        error_text = str(payload.get("error", "Unknown Windows shell error."))

        self.pending_windows_explorer_menu_paths.discard(repository_path)
        self.windows_explorer_menu_errors[repository_path] = error_text
        self._debug_log(f"context_menu explorer_prefetch failed | path={repository_path} | {error_text}")
        self._debug_timing("context_menu explorer_prefetch", started_at, f"{repository_path} | failed")

    def _set_buttons_state(self, state: str) -> None:
        for button in self.action_buttons:
            button.configure(state=state)

    def _selected_records(self) -> list[RepositoryRecord]:
        return [repository for repository in self.repositories if repository.selected]

    def _selected_paths(self) -> list[str]:
        return [repository.path for repository in self._selected_records()]

    def _summarize_operation(self, results: list[OperationResult]) -> str:
        counts = {"success": 0, "failed": 0, "skipped": 0}
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return (
            f"成功 {counts['success']} 个，"
            f"跳过 {counts['skipped']} 个，"
            f"失败 {counts['failed']} 个"
        )

    def _status_label(self, status: str) -> str:
        return {
            "success": "成功",
            "failed": "失败",
            "skipped": "跳过",
        }.get(status, status)

    def run(self) -> None:
        self.root.mainloop()


def run_app() -> None:
    app = GitBatchManagerApp()
    app.run()


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
