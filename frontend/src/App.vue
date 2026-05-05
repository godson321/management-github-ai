<script setup lang="ts">
import {
  Check,
  Delete,
  DocumentAdd,
  Download,
  FolderOpened,
  Refresh,
  Search,
  Upload,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import type { ComponentPublicInstance } from "vue";
import type {
  VxeColumnPropTypes,
  VxeTableDefines,
  VxeTableInstance,
  VxeTablePropTypes,
} from "vxe-table";
import type {
  ActivityItem,
  AppState,
  AppUiState,
  BatchProgressEvent,
  GitCommitView,
  GitLogEntry,
  GitLogResult,
  OperationStatus,
  RepositoryAccessMode,
  RepositoryOperationResult,
  RepositoryRecord,
  WindowsExplorerMenuItem,
  WindowsExplorerMenuResponse,
} from "./types";

const invoke = window.__TAURI__?.core?.invoke;
const listen = window.__TAURI__?.event?.listen;
const openDialog = window.__TAURI__?.dialog?.open;

const repositories = ref<RepositoryRecord[]>([]);
const selectedPath = ref("");
const selectedCommitHash = ref("");
const activeTab = ref("details");
const statusText = ref("正在启动...");
const searchText = ref("");
const failedOnly = ref(false);
const busy = ref(false);
const importDialogVisible = ref(false);
const importPathsText = ref("");
const activityLog = ref<ActivityItem[]>([]);
const activityLogRef = ref<HTMLElement | null>(null);
const logRowsRef = ref<HTMLElement | null>(null);
const columnSettingsVisible = ref(false);
const repoTableRef = ref<VxeTableInstance<RepositoryRecord> | null>(null);
const workspaceRef = ref<HTMLElement | null>(null);
const contentGridRef = ref<HTMLElement | null>(null);
const repoContextMenuRef = ref<HTMLElement | null>(null);
const repoContextMenuVisible = ref(false);
const repoContextMenuX = ref(0);
const repoContextMenuY = ref(0);
const repoContextMenuRepositoryPath = ref("");
const explorerMenuLoading = ref(false);
const explorerMenuSupported = ref(false);
const explorerMenuItems = ref<WindowsExplorerMenuItem[]>([]);
const repoContextMenuSubmenuSide = ref<"left" | "right">("right");
const repoContextMenuSubmenuVerticalSide = ref<"up" | "down">("down");
let activityId = 0;
let explorerMenuRequestId = 0;

type RepositoryActionKind = "refresh" | "pull" | "commit" | "push";
type PullStrategy = "merge" | "ff_only" | "rebase";
type RepoMenuOptionCode =
  | "toggle-selected"
  | "refresh"
  | "commit"
  | "push"
  | "open-folder"
  | "copy-path"
  | "select-all"
  | "clear-selection"
  | `pull:${PullStrategy}`
  | `explorer:${number}`;

interface ContextMenuOption {
  code?: RepoMenuOptionCode;
  name?: string;
  disabled?: boolean;
  loading?: boolean;
  children?: ContextMenuOption[];
  params?: Record<string, unknown>;
}

type ContextMenuSubmenuStyle = {
  top?: string;
};

type RepositoryColumnKey =
  | "name"
  | "path"
  | "branch"
  | "dirty"
  | "ahead"
  | "behind"
  | "accessMode"
  | "lastCommit"
  | "lastOperationStatus"
  | "statusMessage";

interface RepositoryColumnDefinition {
  key: RepositoryColumnKey;
  title: string;
  width?: number;
  minWidth?: number;
  align?: "left" | "center" | "right";
  sortable?: boolean;
}

const repositoryColumnDefinitions: RepositoryColumnDefinition[] = [
  { key: "name", title: "仓库", minWidth: 150, sortable: true },
  { key: "path", title: "文件夹路径", minWidth: 220, sortable: true },
  { key: "branch", title: "分支", width: 120, minWidth: 72, sortable: true },
  { key: "dirty", title: "改动", width: 76, minWidth: 54, align: "center", sortable: true },
  { key: "ahead", title: "领先", width: 72, minWidth: 54, align: "center", sortable: true },
  { key: "behind", title: "落后", width: 72, minWidth: 54, align: "center", sortable: true },
  { key: "accessMode", title: "权限", width: 108, minWidth: 86, align: "center" },
  { key: "lastCommit", title: "最新提交", minWidth: 150, sortable: true },
  { key: "lastOperationStatus", title: "结果", width: 82, minWidth: 54, align: "center" },
  { key: "statusMessage", title: "状态", minWidth: 150, sortable: true },
];

const requiredRepositoryColumnKeys: RepositoryColumnKey[] = ["name"];
const defaultRepositoryColumnKeys = repositoryColumnDefinitions.map((column) => column.key);
const repositoryColumnOrder = ref<RepositoryColumnKey[]>([...defaultRepositoryColumnKeys]);
const hiddenRepositoryColumns = ref<RepositoryColumnKey[]>([]);
const repositoryColumnWidths = reactive<Record<string, number>>({});
const DEFAULT_LAYOUT_DETAIL_WIDTH = 420;
const DEFAULT_LAYOUT_ACTIVITY_HEIGHT = 158;
const MIN_LAYOUT_REPO_WIDTH = 480;
const MIN_LAYOUT_DETAIL_WIDTH = 320;
const MIN_LAYOUT_CONTENT_HEIGHT = 280;
const MIN_LAYOUT_ACTIVITY_HEIGHT = 112;
const LAYOUT_SPLITTER_SIZE = 12;
const layoutDetailWidth = ref(DEFAULT_LAYOUT_DETAIL_WIDTH);
const layoutActivityHeight = ref(DEFAULT_LAYOUT_ACTIVITY_HEIGHT);

type LayoutResizeState =
  | {
      kind: "detail";
      startX: number;
      startWidth: number;
      minWidth: number;
      maxWidth: number;
    }
  | {
      kind: "activity";
      startY: number;
      startHeight: number;
      minHeight: number;
      maxHeight: number;
    };

let layoutResizeState: LayoutResizeState | null = null;

interface LogGraphSegment {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
}

interface LogGraphNode {
  key: string;
  cx: number;
  cy: number;
  color: string;
}

interface LogGraphView {
  width: number;
  height: number;
  segments: LogGraphSegment[];
  nodes: LogGraphNode[];
}

interface ParsedLogGraphRow {
  laneCount: number;
  activeLanes: number[];
  verticalLanes: number[];
  nodeLanes: number[];
  downRightEdges: Array<{ from: number; to: number }>;
  downLeftEdges: Array<{ from: number; to: number }>;
  horizontalEdges: Array<{ from: number; to: number }>;
}

interface VisualLogGraphRow {
  key: string;
  y: number;
  parsed: ParsedLogGraphRow;
}

const LOG_GRAPH_SLOT_WIDTH = 18;
const LOG_GRAPH_MIN_WIDTH = 82;
const LOG_GRAPH_ROW_MIN_HEIGHT = 46;
const LOG_GRAPH_ROW_FALLBACK_HEIGHT = 62;
const LOG_GRAPH_ROW_GAP = 8;
const LOG_GRAPH_NODE_RADIUS = 5;
const LOG_GRAPH_COLORS = ["#111827", "#ef1b1b", "#0fcf2f", "#2248ff", "#8b8f99", "#f59e0b", "#7c3aed"];
const COLUMN_HIDE_DRAG_THRESHOLD = 42;
const logRowElements = new Map<string, HTMLElement>();
const logGraphLayerView = ref<LogGraphView>({
  width: LOG_GRAPH_MIN_WIDTH,
  height: 0,
  segments: [],
  nodes: [],
});
let columnDragStart:
  | {
      field: RepositoryColumnKey;
      clientX: number;
      clientY: number;
    }
  | null = null;
let lastColumnDragPointer: { clientX: number; clientY: number } | null = null;
let columnDragHiddenDuringNativeDrag = false;

const repositoryColumnMap = new Map(repositoryColumnDefinitions.map((column) => [column.key, column]));
function normalizeRepositoryColumnOrder(rawOrder: unknown[]) {
  const validKeys = new Set(defaultRepositoryColumnKeys);
  const normalizedOrder: RepositoryColumnKey[] = [];
  for (const key of rawOrder) {
    if (
      typeof key === "string" &&
      validKeys.has(key as RepositoryColumnKey) &&
      !normalizedOrder.includes(key as RepositoryColumnKey)
    ) {
      normalizedOrder.push(key as RepositoryColumnKey);
    }
  }
  const completedOrder = [...normalizedOrder];
  for (const key of defaultRepositoryColumnKeys) {
    if (completedOrder.includes(key)) {
      continue;
    }
    const defaultIndex = defaultRepositoryColumnKeys.indexOf(key);
    const previousKey = [...defaultRepositoryColumnKeys]
      .slice(0, defaultIndex)
      .reverse()
      .find((candidate) => completedOrder.includes(candidate));
    if (previousKey) {
      completedOrder.splice(completedOrder.indexOf(previousKey) + 1, 0, key);
      continue;
    }
    const nextKey = defaultRepositoryColumnKeys
      .slice(defaultIndex + 1)
      .find((candidate) => completedOrder.includes(candidate));
    if (nextKey) {
      completedOrder.splice(completedOrder.indexOf(nextKey), 0, key);
      continue;
    }
    completedOrder.push(key);
  }
  return completedOrder;
}

const pullStrategyOptions: Array<{ label: string; value: "merge" | "ff_only" | "rebase" }> = [
  { label: "合并拉取", value: "merge" },
  { label: "仅快进", value: "ff_only" },
  { label: "变基拉取", value: "rebase" },
];

const repositoryAccessModeOptions: Array<{ label: string; value: RepositoryAccessMode }> = [
  { label: "仅拉取", value: "pullOnly" },
  { label: "仅推送", value: "pushOnly" },
  { label: "拉取 + 推送", value: "pullPush" },
];

const selectedRepositories = computed(() =>
  repositories.value.filter((repository) => repository.selected),
);

const selectedRepositoriesCanPull = computed(() => selectedRepositories.value.some(canPull));
const selectedRepositoriesCanPush = computed(() => selectedRepositories.value.some(canPush));

const selectedRepository = computed(
  () => repositories.value.find((repository) => repository.path === selectedPath.value) ?? null,
);

const visibleRepositories = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase();
  return repositories.value.filter((repository) => {
    if (failedOnly.value && repository.lastOperationStatus !== "failed") {
      return false;
    }
    if (!query) {
      return true;
    }
    return [repository.name, repository.branch, repository.path, repository.statusMessage]
      .join("\n")
      .toLocaleLowerCase()
      .includes(query);
  });
});

const repositorySummary = computed(
  () =>
    `${repositories.value.length} 个仓库，当前显示 ${visibleRepositories.value.length} 个，已选择 ${selectedRepositories.value.length} 个`,
);

const orderedRepositoryColumns = computed(() => {
  return normalizeRepositoryColumnOrder(repositoryColumnOrder.value).map((key) => repositoryColumnMap.get(key)!);
});

const visibleRepositoryColumns = computed(() =>
  orderedRepositoryColumns.value.filter((column) => !hiddenRepositoryColumns.value.includes(column.key)),
);

function isRepositoryColumnDragLocked(field: unknown) {
  return field === "selected";
}

const repositoryColumnDragConfig = computed<VxeTablePropTypes.ColumnDragConfig<RepositoryRecord>>(() => ({
  showIcon: true,
  showDragTip: true,
  disabledMethod: ({ column }) => isRepositoryColumnDragLocked(column.field),
  visibleMethod: ({ column }) => !isRepositoryColumnDragLocked(column.field),
}));

const tableUiState = computed<AppUiState>(() => ({
  repositoryColumns: repositoryColumnOrder.value,
  hiddenRepositoryColumns: hiddenRepositoryColumns.value,
  repositoryColumnWidths: { ...repositoryColumnWidths },
  layoutDetailWidth: Math.round(layoutDetailWidth.value),
  layoutActivityHeight: Math.round(layoutActivityHeight.value),
}));

const workspaceStyle = computed(() => ({
  gridTemplateRows: "auto auto minmax(0, 1fr)",
}));

const contentGridStyle = computed(() => ({
  gridTemplateColumns: `minmax(${MIN_LAYOUT_REPO_WIDTH}px, 1fr) ${LAYOUT_SPLITTER_SIZE}px minmax(${MIN_LAYOUT_DETAIL_WIDTH}px, ${layoutDetailWidth.value}px)`,
}));

const branchFilters = computed(() => buildColumnFilters("branch"));
const dirtyFilters = [
  { label: "有改动", value: "dirty" },
  { label: "干净", value: "clean" },
];
const operationStatusFilters = [
  { label: "空闲", value: "idle" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "success" },
  { label: "失败", value: "failed" },
  { label: "跳过", value: "skipped" },
];

const currentContextRepository = computed(
  () => repositories.value.find((repository) => repository.path === repoContextMenuRepositoryPath.value) ?? null,
);

const repoContextMenuStyle = computed(() => ({
  left: `${repoContextMenuX.value}px`,
  top: `${repoContextMenuY.value}px`,
}));

const repoContextMenuClass = computed(() => ({
  "submenu-left": repoContextMenuSubmenuSide.value === "left",
  "submenu-up": repoContextMenuSubmenuVerticalSide.value === "up",
}));
const repoContextMenuSubmenuStyles = reactive<Record<string, ContextMenuSubmenuStyle>>({});

const repoContextMenuOptions = computed<ContextMenuOption[][]>(() => {
  const repository = currentContextRepository.value;
  const explorerChildren = buildExplorerMenuChildren();

  return [
    [
      {
        code: "toggle-selected",
        name: repository?.selected ? "取消勾选" : "勾选仓库",
        disabled: !repository,
      },
    ],
    [
      { code: "refresh", name: "刷新", disabled: busy.value || !repository },
      {
        name: "拉取",
        disabled: busy.value || !repository || !canPull(repository),
        children: pullStrategyOptions.map((option) => ({
          code: `pull:${option.value}`,
          name: option.label,
          disabled: busy.value || !repository || !canPull(repository),
        })),
      },
      { code: "commit", name: "提交...", disabled: busy.value || !repository },
      { code: "push", name: "推送", disabled: busy.value || !repository || !canPush(repository) },
    ],
    [
      {
        name: "Windows 资源管理",
        disabled: !repository || (!explorerMenuSupported.value && !explorerMenuLoading.value),
        loading: Boolean(repository) && explorerMenuLoading.value,
        children: explorerChildren,
      },
      { code: "open-folder", name: "打开文件夹", disabled: !repository },
      { code: "copy-path", name: "复制仓库路径", disabled: !repository },
    ],
    [
      { code: "select-all", name: "全选全部仓库", disabled: !repositories.value.length },
      { code: "clear-selection", name: "清空全部勾选", disabled: !selectedRepositories.value.length },
    ],
  ];
});

const logSummary = computed(() => {
  const repository = selectedRepository.value;
  if (!repository) {
    return "请选择一个仓库以查看日志树。";
  }
  const entries = repository.logEntries || [];
  if (!entries.length) {
    return repository.logMessage || "尚未加载日志。";
  }
  const latest = repository.lastCommit ? ` 最新提交：${repository.lastCommit}` : "";
  return `当前分支：${repository.branch || "未知分支"}，已加载 ${entries.length} 条提交记录。${latest}`;
});

const commitSummary = computed(() =>
  selectedCommitHash.value ? `提交 ${selectedCommitHash.value.slice(0, 12)}` : "请选择一条提交记录。",
);

const commitDetailText = computed(
  () => selectedRepository.value?.commitDetailText || "(没有提交详情)",
);

const changedFiles = computed(() => selectedRepository.value?.commitChangedFiles || []);

function buildColumnFilters(key: keyof RepositoryRecord) {
  return Array.from(
    new Set(
      repositories.value
        .map((repository) => String(repository[key] || "").trim())
        .filter(Boolean),
    ),
  )
    .sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true }))
    .map((value) => ({ label: value, value }));
}

function normalizeRepositoryPathForDisplay(path: string) {
  return path.replace(/^\\\\\?\\/, "").replace(/^\\\?\?\\/, "");
}

function normalizeRepository(repository: RepositoryRecord): RepositoryRecord {
  return {
    ...repository,
    accessMode: repository.accessMode ?? "pullPush",
    path: normalizeRepositoryPathForDisplay(repository.path),
  };
}

function normalizeRepositories(items: RepositoryRecord[]) {
  return items.map(normalizeRepository);
}

function applyUiState(uiState?: Partial<AppUiState>) {
  const rawOrder = uiState?.repositoryColumns ?? [];
  const validKeys = new Set(defaultRepositoryColumnKeys);
  repositoryColumnOrder.value = normalizeRepositoryColumnOrder(rawOrder);

  const requiredKeys = new Set(requiredRepositoryColumnKeys);
  hiddenRepositoryColumns.value = (uiState?.hiddenRepositoryColumns ?? []).filter(
    (key): key is RepositoryColumnKey =>
      validKeys.has(key as RepositoryColumnKey) && !requiredKeys.has(key as RepositoryColumnKey),
  );

  for (const key of Object.keys(repositoryColumnWidths)) {
    delete repositoryColumnWidths[key];
  }
  for (const [key, value] of Object.entries(uiState?.repositoryColumnWidths ?? {})) {
    if (validKeys.has(key as RepositoryColumnKey) && Number.isFinite(value) && value > 0) {
      repositoryColumnWidths[key] = value;
    }
  }
  layoutDetailWidth.value = normalizeLayoutSize(
    uiState?.layoutDetailWidth,
    DEFAULT_LAYOUT_DETAIL_WIDTH,
    MIN_LAYOUT_DETAIL_WIDTH,
  );
  layoutActivityHeight.value = normalizeLayoutSize(
    uiState?.layoutActivityHeight,
    DEFAULT_LAYOUT_ACTIVITY_HEIGHT,
    MIN_LAYOUT_ACTIVITY_HEIGHT,
  );
}

function saveUiState() {
  saveRepositories().catch((error) => handleError("保存表格布局失败", error));
}

function normalizeLayoutSize(value: unknown, fallback: number, min: number) {
  return typeof value === "number" && Number.isFinite(value) && value >= min ? Math.round(value) : fallback;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function columnWidth(column: RepositoryColumnDefinition): number | undefined {
  return repositoryColumnWidths[column.key] || column.width;
}

function refreshRepositoryTableLayout(delay = 0) {
  window.setTimeout(() => {
    nextTick(() => {
      repoTableRef.value?.recalculate(true).then(() => repoTableRef.value?.refreshScroll());
    });
  }, delay);
}

function ensureTauri() {
  if (!invoke) {
    throw new Error("未检测到 Tauri invoke API，请在 Tauri 运行时中启动应用。");
  }
  return invoke;
}

function openTextImportDialog() {
  importDialogVisible.value = true;
  refreshRepositoryTableLayout(80);
}

function setBusy(isBusy: boolean, message = "") {
  busy.value = isBusy;
  if (message) {
    statusText.value = message;
  }
}

function addActivity(text: string, level: ActivityItem["level"] = "info") {
  activityLog.value.push({
    id: ++activityId,
    time: new Date().toLocaleTimeString(),
    level,
    text,
  });
  if (activityLog.value.length > 500) {
    activityLog.value.splice(0, activityLog.value.length - 500);
  }
  nextTick(() => {
    if (activityLogRef.value) {
      activityLogRef.value.scrollTop = activityLogRef.value.scrollHeight;
    }
  });
}

function statusType(status: OperationStatus) {
  if (status === "success") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "skipped") {
    return "warning";
  }
  if (status === "running") {
    return "primary";
  }
  return "info";
}

function statusLabel(status: string) {
  return (
    {
      success: "成功",
      failed: "失败",
      skipped: "跳过",
      running: "运行中",
      idle: "空闲",
    }[status] || status
  );
}

function canPull(repository: RepositoryRecord) {
  return repository.accessMode !== "pushOnly";
}

function canPush(repository: RepositoryRecord) {
  return repository.accessMode !== "pullOnly";
}

function repositoryAccessModeLabel(accessMode: RepositoryAccessMode) {
  return repositoryAccessModeOptions.find((option) => option.value === accessMode)?.label || "拉取 + 推送";
}

function activityLevel(status: string): ActivityItem["level"] {
  if (status === "success") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "skipped") {
    return "warning";
  }
  return "info";
}

function selectedRowClassName({ row }: { row: RepositoryRecord }) {
  if (row.path === selectedPath.value) {
    return "selected-row";
  }
  if (row.lastOperationStatus === "failed") {
    return "failed-row";
  }
  if (row.lastOperationStatus === "running") {
    return "running-row";
  }
  return "";
}

function selectRepository(repository: RepositoryRecord) {
  selectedPath.value = repository.path;
  selectedCommitHash.value = repository.selectedCommitHash || "";
}

function toggleRepository(repository: RepositoryRecord, selected: boolean) {
  repository.selected = selected;
  saveRepositories().catch((error) => handleError("保存选择状态失败", error));
}

function updateRepositoryAccessMode(path: string, accessMode: RepositoryAccessMode) {
  const repository = repositories.value.find((item) => item.path === path);
  if (!repository) {
    return;
  }
  repository.accessMode = accessMode;
  saveRepositories().catch((error) => handleError("保存权限状态失败", error));
}

function updateSelectedRepositoryAccessMode(accessMode: RepositoryAccessMode) {
  const repository = selectedRepository.value;
  if (!repository) {
    return;
  }
  updateRepositoryAccessMode(repository.path, accessMode);
}

function replaceRepository(repository: RepositoryRecord) {
  const normalizedRepository = normalizeRepository(repository);
  const index = repositories.value.findIndex((item) => item.path === normalizedRepository.path);
  if (index === -1) {
    repositories.value.push(normalizedRepository);
  } else {
    repositories.value.splice(index, 1, normalizedRepository);
  }
  if (!selectedPath.value && repositories.value.length) {
    selectedPath.value = repositories.value[0].path;
  }
}

function removeRepositoriesByPath(paths: string[]) {
  const removedPaths = new Set(paths);
  if (!removedPaths.size) {
    return;
  }

  repositories.value = repositories.value.filter((repository) => !removedPaths.has(repository.path));
  if (removedPaths.has(selectedPath.value)) {
    selectedPath.value = repositories.value[0]?.path || "";
    selectedCommitHash.value = "";
  }
  syncVxeSelection();
}

function applyRepositories(nextRepositories: RepositoryRecord[]) {
  for (const repository of nextRepositories) {
    replaceRepository(repository);
  }
}

function mergeRepositories(nextRepositories: RepositoryRecord[]) {
  const existing = new Map(repositories.value.map((repository) => [repository.path, repository]));
  for (const repository of normalizeRepositories(nextRepositories)) {
    if (!existing.has(repository.path)) {
      existing.set(repository.path, repository);
    }
  }
  repositories.value = Array.from(existing.values()).sort((left, right) =>
    left.name.localeCompare(right.name, "zh-CN"),
  );
  if (!selectedPath.value && repositories.value.length) {
    selectedPath.value = repositories.value[0].path;
  }
}

function buildExplorerMenuChildren(): ContextMenuOption[] {
  if (!currentContextRepository.value) {
    return [];
  }
  if (explorerMenuLoading.value) {
    return [{ name: "加载中...", disabled: true }];
  }
  if (!explorerMenuSupported.value) {
    return [{ name: "仅支持 Windows", disabled: true }];
  }
  if (!explorerMenuItems.value.length) {
    return [{ name: "没有可用菜单项", disabled: true }];
  }
  return explorerMenuItems.value.map((item, index) => ({
    code: item.isSeparator || item.verbIndex === null ? undefined : `explorer:${item.verbIndex}`,
    name: item.isSeparator ? "────────" : item.label,
    disabled: item.isSeparator || item.verbIndex === null || busy.value,
    params: { separator: item.isSeparator, index },
  }));
}

function closeRepoContextMenu() {
  explorerMenuRequestId += 1;
  repoContextMenuVisible.value = false;
  repoContextMenuRepositoryPath.value = "";
  explorerMenuLoading.value = false;
  repoContextMenuSubmenuSide.value = "right";
  repoContextMenuSubmenuVerticalSide.value = "down";
  clearRepoContextMenuSubmenuStyles();
}

function updateRepoContextMenuPosition() {
  nextTick(() => {
    if (!repoContextMenuVisible.value || !repoContextMenuRef.value) {
      return;
    }
    const margin = 12;
    const menuWidth = repoContextMenuRef.value.offsetWidth;
    const menuHeight = repoContextMenuRef.value.offsetHeight;
    const maxX = Math.max(margin, window.innerWidth - menuWidth - margin);
    const maxY = Math.max(margin, window.innerHeight - menuHeight - margin);
    repoContextMenuX.value = clamp(repoContextMenuX.value, margin, maxX);
    repoContextMenuY.value = clamp(repoContextMenuY.value, margin, maxY);
  });
}

function contextMenuOptionKey(option: ContextMenuOption) {
  return option.code || option.name || "";
}

function clearRepoContextMenuSubmenuStyles() {
  for (const key of Object.keys(repoContextMenuSubmenuStyles)) {
    delete repoContextMenuSubmenuStyles[key];
  }
}

function getRepoContextMenuSubmenuStyle(option: ContextMenuOption) {
  return repoContextMenuSubmenuStyles[contextMenuOptionKey(option)];
}

function updateRepoContextMenuSubmenuStyle(option: ContextMenuOption, anchor: HTMLElement) {
  if (!option.children?.length) {
    return;
  }
  window.requestAnimationFrame(() => {
    const submenu = anchor.querySelector(".repo-context-menu-submenu");
    if (!(submenu instanceof HTMLElement)) {
      return;
    }
    const margin = 12;
    const baseTop = -6;
    const submenuHeight = submenu.offsetHeight;
    const anchorRect = anchor.getBoundingClientRect();
    const targetViewportTop = clamp(
      anchorRect.top + baseTop,
      margin,
      Math.max(margin, window.innerHeight - submenuHeight - margin),
    );
    repoContextMenuSubmenuStyles[contextMenuOptionKey(option)] = {
      top: `${targetViewportTop - anchorRect.top}px`,
    };
  });
}

function handleRepoContextMenuItemEnter(option: ContextMenuOption, event: MouseEvent) {
  const anchor = event.currentTarget;
  if (!(anchor instanceof HTMLElement)) {
    return;
  }
  updateRepoContextMenuSubmenuStyle(option, anchor);
}

function updateExplorerContextMenuSubmenuStyle() {
  if (!repoContextMenuRef.value) {
    return;
  }
  const explorerOption = repoContextMenuOptions.value
    .flat()
    .find((option) => option.name === "Windows 资源管理" && option.children?.length);
  if (!explorerOption) {
    return;
  }
  const anchors = Array.from(repoContextMenuRef.value.querySelectorAll<HTMLElement>(".repo-context-menu-item.hasChildren"));
  const anchor = anchors.find((element) =>
    element.querySelector(".repo-context-menu-label")?.textContent?.trim() === "Windows 资源管理",
  );
  if (!anchor) {
    return;
  }
  updateRepoContextMenuSubmenuStyle(explorerOption, anchor);
}

async function loadExplorerMenuItems(repositoryPath: string) {
  const tauriInvoke = ensureTauri();
  const requestId = ++explorerMenuRequestId;
  explorerMenuItems.value = [];
  explorerMenuLoading.value = true;
  clearRepoContextMenuSubmenuStyles();
  try {
    const response = await tauriInvoke<WindowsExplorerMenuResponse>("list_windows_explorer_menu_items", {
      path: repositoryPath,
    });
    if (requestId !== explorerMenuRequestId || repoContextMenuRepositoryPath.value !== repositoryPath) {
      return;
    }
    explorerMenuSupported.value = response.supported;
    explorerMenuItems.value = response.items || [];
  } catch (error) {
    if (requestId !== explorerMenuRequestId || repoContextMenuRepositoryPath.value !== repositoryPath) {
      return;
    }
    explorerMenuSupported.value = false;
    explorerMenuItems.value = [];
    addActivity(`加载 Windows 资源管理器菜单失败：${String(error)}`, "warning");
  } finally {
    if (requestId === explorerMenuRequestId && repoContextMenuRepositoryPath.value === repositoryPath) {
      explorerMenuLoading.value = false;
      updateRepoContextMenuPosition();
      updateExplorerContextMenuSubmenuStyle();
    }
  }
}

async function openRepoContextMenu(repository: RepositoryRecord, event: MouseEvent) {
  repoContextMenuRepositoryPath.value = repository.path;
  selectRepository(repository);
  repoContextMenuX.value = event.clientX;
  repoContextMenuY.value = event.clientY;
  repoContextMenuVisible.value = true;
  repoContextMenuSubmenuSide.value = "right";
  repoContextMenuSubmenuVerticalSide.value = "down";
  clearRepoContextMenuSubmenuStyles();
  updateRepoContextMenuPosition();
  await loadExplorerMenuItems(repository.path);
}

function findRepositoryFromContextTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return null;
  }
  const rowElement = target.closest(".vxe-body--row[rowid]");
  if (!(rowElement instanceof HTMLElement)) {
    return null;
  }
  const table = repoTableRef.value as (VxeTableInstance<RepositoryRecord> & {
    getRowNode?: (rowElement: Element) => { item?: RepositoryRecord } | null;
  }) | null;
  return table?.getRowNode?.(rowElement)?.item ?? null;
}

function handleRepoTableContextMenu(event: MouseEvent) {
  event.preventDefault();
  const repository = findRepositoryFromContextTarget(event.target);
  if (!repository) {
    closeRepoContextMenu();
    return;
  }
  void openRepoContextMenu(repository, event);
}

async function copyTextToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("当前环境不支持复制到剪贴板。");
  }
}

async function setAllRepositoriesSelected(selected: boolean) {
  for (const repository of repositories.value) {
    repository.selected = selected;
  }
  await saveRepositories();
  syncVxeSelection();
}

async function handleRepoContextMenuOptionClick(option: ContextMenuOption) {
  if (!option.code || option.disabled) {
    return;
  }

  const repository = currentContextRepository.value;
  closeRepoContextMenu();

  if (option.code.startsWith("pull:")) {
    if (repository) {
      await runRepositoryAction(repository, "pull", option.code.slice(5) as PullStrategy);
    }
    return;
  }

  if (option.code.startsWith("explorer:")) {
    if (!repository) {
      return;
    }
    try {
      const tauriInvoke = ensureTauri();
      const verbIndex = Number.parseInt(option.code.slice(9), 10);
      await tauriInvoke("invoke_windows_explorer_menu_item", {
        path: repository.path,
        verbIndex,
      });
      statusText.value = `已执行 ${repository.name} 的 Windows 资源管理器命令`;
    } catch (error) {
      handleError("执行 Windows 资源管理器命令失败", error);
    }
    return;
  }

  if (!repository && option.code !== "select-all" && option.code !== "clear-selection") {
    return;
  }

  switch (option.code) {
    case "toggle-selected":
      if (repository) {
        const nextSelected = !repository.selected;
        toggleRepository(repository, nextSelected);
        syncVxeSelection();
        statusText.value = nextSelected ? `已勾选 ${repository.name}` : `已取消勾选 ${repository.name}`;
      }
      return;
    case "refresh":
      if (repository) {
        await runRepositoryAction(repository, "refresh");
      }
      return;
    case "commit":
      if (repository) {
        await runRepositoryAction(repository, "commit");
      }
      return;
    case "push":
      if (repository) {
        await runRepositoryAction(repository, "push");
      }
      return;
    case "open-folder":
      if (repository) {
        try {
          const tauriInvoke = ensureTauri();
          await tauriInvoke("open_repository_folder", {
            path: repository.path,
          });
        } catch (error) {
          handleError("打开仓库文件夹失败", error);
        }
      }
      return;
    case "copy-path":
      if (repository) {
        try {
          await copyTextToClipboard(repository.path);
          statusText.value = `已复制 ${repository.name} 的仓库路径`;
        } catch (error) {
          handleError("复制仓库路径失败", error);
        }
      }
      return;
    case "select-all":
      await setAllRepositoriesSelected(true);
      statusText.value = "已全选全部仓库";
      return;
    case "clear-selection":
      await setAllRepositoriesSelected(false);
      statusText.value = "已清空全部勾选";
      return;
  }
}

function handleDocumentPointerDown(event: PointerEvent) {
  if (!(event.target instanceof Element)) {
    closeRepoContextMenu();
    return;
  }
  if (event.target.closest(".repo-context-menu")) {
    return;
  }
  closeRepoContextMenu();
}

async function loadInitialState() {
  if (!invoke) {
    statusText.value = "请在 Tauri 运行时中启动应用。";
    addActivity("未检测到 Tauri invoke API，无法调用 Rust 后端。", "warning");
    return;
  }

  setBusy(true, "正在加载仓库列表...");
  try {
    const appState = await invoke<AppState>("load_app_state");
    applyUiState(appState.uiState);
    repositories.value = normalizeRepositories(appState.repositories || []);
    selectedPath.value = repositories.value[0]?.path || "";
    statusText.value = "准备就绪";
    addActivity(`已加载 ${repositories.value.length} 个仓库。`, "success");
  } catch (error) {
    handleError("加载仓库列表失败", error);
  } finally {
    setBusy(false);
  }
}

async function saveRepositories() {
  if (!invoke) {
    return;
  }
  await invoke("save_repositories", {
    repositories: repositories.value,
    uiState: tableUiState.value,
  });
}

function appendImportPaths(paths: string[]) {
  const existing = importPathsText.value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const nextPaths = [...existing];
  for (const path of paths) {
    const normalizedPath = normalizeRepositoryPathForDisplay(path.trim());
    if (normalizedPath && !nextPaths.includes(normalizedPath)) {
      nextPaths.push(normalizedPath);
    }
  }
  importPathsText.value = nextPaths.join("\n");
}

async function selectImportDirectories() {
  if (!openDialog) {
    openTextImportDialog();
    ElMessage.warning("当前运行环境不支持原生目录选择，已切换到路径输入。");
    return;
  }
  refreshRepositoryTableLayout();
  try {
    const selected = await openDialog({
      title: "选择要导入的仓库目录或父目录",
      directory: true,
      multiple: true,
    });
    refreshRepositoryTableLayout();
    if (!selected) {
      return;
    }
    const paths = Array.isArray(selected) ? selected : [selected];
    appendImportPaths(paths);
    await importPaths();
  } catch (error) {
    handleError("选择导入目录失败", error);
  } finally {
    refreshRepositoryTableLayout(80);
  }
}

async function importPaths() {
  const paths = importPathsText.value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!paths.length) {
    ElMessage.warning("请输入至少一个路径。");
    return;
  }

  const tauriInvoke = ensureTauri();
  setBusy(true, "正在扫描路径...");
  try {
    const discovered = await tauriInvoke<RepositoryRecord[]>("discover_repositories", { paths });
    mergeRepositories(discovered);
    await refreshRepositories(discovered.map((repository) => repository.path), false);
    await saveRepositories();
    importDialogVisible.value = false;
    importPathsText.value = "";
    addActivity(`导入 ${discovered.length} 个仓库。`, "success");
    refreshRepositoryTableLayout();
  } catch (error) {
    handleError("导入路径失败", error);
  } finally {
    setBusy(false);
    refreshRepositoryTableLayout(80);
  }
}

async function refreshRepositories(paths: string[] | null = null, manageBusy = true) {
  const targets = paths
    ? repositories.value.filter((repository) => paths.includes(repository.path))
    : selectedRepositories.value;
  if (!targets.length) {
    statusText.value = "没有选中的仓库。";
    ElMessage.warning("没有选中的仓库。");
    return;
  }

  const tauriInvoke = ensureTauri();
  if (manageBusy) {
    setBusy(true, `正在刷新 ${targets.length} 个仓库...`);
  }
  try {
    const refreshed = await tauriInvoke<RepositoryRecord[]>("refresh_repositories", {
      repositories: targets,
    });
    const refreshedPaths = new Set(refreshed.map((repository) => repository.path));
    removeRepositoriesByPath(targets.map((repository) => repository.path).filter((path) => !refreshedPaths.has(path)));
    applyRepositories(refreshed);
    await saveRepositories();
    addActivity(`刷新完成：${refreshed.length} 个仓库。`, "success");
    statusText.value = "刷新完成";
  } catch (error) {
    handleError("刷新状态失败", error);
  } finally {
    if (manageBusy) {
      setBusy(false);
    }
  }
}

async function runRepositoryAction(
  repository: RepositoryRecord,
  kind: RepositoryActionKind,
  strategy?: PullStrategy,
) {
  const tauriInvoke = ensureTauri();
  const args: Record<string, unknown> = { repositories: [repository] };
  let command = "";
  let busyText = "";
  if (kind === "refresh") {
    command = "refresh_repositories";
    busyText = `正在刷新 ${repository.name}...`;
  } else if (kind === "pull") {
    command = "pull_repositories";
    args.strategy = strategy ?? "merge";
    busyText = `正在拉取 ${repository.name}...`;
  } else if (kind === "commit") {
    const message = await promptCommitMessage();
    if (!message) {
      statusText.value = "已取消提交。";
      return;
    }
    command = "commit_repositories";
    args.message = message;
    busyText = `正在提交 ${repository.name}...`;
  } else {
    command = "push_repositories";
    busyText = `正在推送 ${repository.name}...`;
  }

  setBusy(true, busyText);
  try {
    if (kind === "refresh") {
      const refreshed = await tauriInvoke<RepositoryRecord[]>(command, args);
      const refreshedPaths = new Set(refreshed.map((item) => item.path));
      removeRepositoriesByPath([repository.path].filter((path) => !refreshedPaths.has(path)));
      applyRepositories(refreshed);
      addActivity(`[刷新] ${repository.name} 已刷新。`, "success");
    } else {
      const results = await tauriInvoke<RepositoryOperationResult[]>(command, args);
      for (const item of results) {
        replaceRepository(item.repository);
        addActivity(
          `[${item.result.action}] ${item.result.repositoryName} - ${statusLabel(item.result.status)}：${item.result.message}`,
          activityLevel(item.result.status),
        );
      }
    }
    await saveRepositories();
    statusText.value = `${repository.name} 操作完成`;
  } catch (error) {
    handleError(`${repository.name} 操作失败`, error);
  } finally {
    setBusy(false);
  }
}

async function runOperation(kind: "pull" | "commit" | "push", strategy?: PullStrategy) {
  const targets = selectedRepositories.value;
  if (!targets.length) {
    statusText.value = "没有选中的仓库。";
    ElMessage.warning("没有选中的仓库。");
    return;
  }

  let command = "";
  const args: Record<string, unknown> = { repositories: targets };
  if (kind === "pull") {
    command = "pull_repositories";
    args.strategy = strategy ?? "merge";
  } else if (kind === "commit") {
    const message = await promptCommitMessage();
    if (!message) {
      statusText.value = "已取消提交。";
      return;
    }
    command = "commit_repositories";
    args.message = message;
  } else {
    command = "push_repositories";
  }

  const tauriInvoke = ensureTauri();
  setBusy(true, `正在执行 ${kind}...`);
  addActivity(`[${kind}] 批量任务开始，共 ${targets.length} 个仓库。`);
  try {
    const results = await tauriInvoke<RepositoryOperationResult[]>(command, args);
    for (const item of results) {
      replaceRepository(item.repository);
    }
    await saveRepositories();
    statusText.value = `${kind} 完成`;
    addActivity(`[${kind}] 批量任务完成。`, "success");
  } catch (error) {
    handleError(`${kind} 失败`, error);
  } finally {
    setBusy(false);
  }
}

async function promptCommitMessage() {
  try {
    const result = await ElMessageBox.prompt("请输入提交说明", "批量提交", {
      confirmButtonText: "提交",
      cancelButtonText: "取消",
      inputType: "textarea",
      inputPlaceholder: "例如：chore: update managed repositories",
      inputValidator: (value) => Boolean(value.trim()) || "提交说明不能为空",
    });
    return result.value.trim();
  } catch {
    return "";
  }
}

async function removeSelected() {
  const selected = new Set(selectedRepositories.value.map((repository) => repository.path));
  if (!selected.size) {
    statusText.value = "没有选中的仓库。";
    ElMessage.warning("没有选中的仓库。");
    return;
  }

  try {
    await ElMessageBox.confirm(`确认移除 ${selected.size} 个已勾选仓库？`, "移除仓库", {
      confirmButtonText: "移除",
      cancelButtonText: "取消",
      type: "warning",
    });
  } catch {
    return;
  }

  repositories.value = repositories.value.filter((repository) => !selected.has(repository.path));
  if (selected.has(selectedPath.value)) {
    selectedPath.value = repositories.value[0]?.path || "";
    selectedCommitHash.value = "";
  }
  syncVxeSelection();
  await saveRepositories();
  addActivity(`已移除 ${selected.size} 个仓库。`, "warning");
}

async function loadLogs() {
  const repository = selectedRepository.value;
  if (!repository) {
    statusText.value = "请选择一个仓库。";
    ElMessage.warning("请选择一个仓库。");
    return;
  }

  const tauriInvoke = ensureTauri();
  setBusy(true, "正在加载日志树...");
  try {
    const result = await tauriInvoke<GitLogResult>("load_log_entries", {
      path: repository.path,
      limit: 120,
    });
    repository.logEntries = result.entries || [];
    repository.logMessage = result.message || "";
    selectedCommitHash.value = repository.logEntries[0]?.commitHash || "";
    repository.selectedCommitHash = selectedCommitHash.value;
    statusText.value = result.message || "日志树已更新";
    activeTab.value = "logs";
    if (selectedCommitHash.value) {
      await loadCommitView(selectedCommitHash.value);
    }
  } catch (error) {
    handleError("加载日志失败", error);
  } finally {
    setBusy(false);
  }
}

async function selectCommit(entry: GitLogEntry) {
  const repository = selectedRepository.value;
  if (!repository) {
    return;
  }
  selectedCommitHash.value = entry.commitHash;
  repository.selectedCommitHash = entry.commitHash;
  activeTab.value = "commit";
  await loadCommitView(entry.commitHash);
}

async function loadCommitView(commitHash: string) {
  const repository = selectedRepository.value;
  if (!repository || !commitHash) {
    return;
  }

  const tauriInvoke = ensureTauri();
  setBusy(true, "正在加载提交详情...");
  try {
    const view = await tauriInvoke<GitCommitView>("load_commit_view", {
      path: repository.path,
      commitHash,
    });
    repository.commitDetailText = view.detailText || "";
    repository.commitChangedFiles = view.files || [];
    statusText.value = "提交详情已加载";
  } catch (error) {
    handleError("加载提交详情失败", error);
  } finally {
    setBusy(false);
  }
}

function handleBatchProgress(event: BatchProgressEvent) {
  if (event.phase === "started") {
    const repository = repositories.value.find((item) => item.path === event.repositoryPath);
    if (repository) {
      repository.lastOperationStatus = "running";
      repository.lastErrorMessage = "";
      repository.statusMessage = `${event.action}中 (${event.index}/${event.total})`;
    }
    statusText.value = `${event.action}中：${event.repositoryName} (${event.index}/${event.total})`;
    addActivity(`[${event.action}] 正在处理 ${event.repositoryName} (${event.index}/${event.total})...`);
    return;
  }

  if (event.repository) {
    replaceRepository(event.repository);
  }
  if (event.result) {
    addActivity(
      `[${event.result.action}] ${event.result.repositoryName} - ${statusLabel(event.result.status)}：${event.result.message}`,
      activityLevel(event.result.status),
    );
  }
  statusText.value = `${event.action}中：已完成 ${event.index}/${event.total}`;
}

async function setupProgressListener() {
  if (!listen) {
    return;
  }
  await listen<BatchProgressEvent>("batch-progress", ({ payload }) => {
    handleBatchProgress(payload);
  });
}

function setColumnVisible(key: RepositoryColumnKey, visible: boolean) {
  if (requiredRepositoryColumnKeys.includes(key)) {
    return;
  }
  const hidden = new Set(hiddenRepositoryColumns.value);
  if (visible) {
    hidden.delete(key);
  } else {
    hidden.add(key);
  }
  hiddenRepositoryColumns.value = Array.from(hidden);
  saveUiState();
}

function showAllColumns() {
  hiddenRepositoryColumns.value = [];
  saveUiState();
}

function resetTableLayout() {
  repositoryColumnOrder.value = [...defaultRepositoryColumnKeys];
  hiddenRepositoryColumns.value = [];
  for (const key of Object.keys(repositoryColumnWidths)) {
    delete repositoryColumnWidths[key];
  }
  saveUiState();
}

function dirtyFilterMethod({ value, row }: VxeColumnPropTypes.FilterMethodParams<RepositoryRecord>) {
  return value === "dirty" ? row.dirty : !row.dirty;
}

function statusFilterMethod({ value, row }: VxeColumnPropTypes.FilterMethodParams<RepositoryRecord>) {
  return row.lastOperationStatus === value;
}

function branchFilterMethod({ value, row }: VxeColumnPropTypes.FilterMethodParams<RepositoryRecord>) {
  return row.branch === value;
}

function tableRowClassName({ row }: { row: RepositoryRecord }) {
  return selectedRowClassName({ row });
}

function selectRepositoryFromVxe(params: VxeTableDefines.CellClickEventParams<RepositoryRecord>) {
  if (params.column.type === "checkbox") {
    return;
  }
  selectRepository(params.row);
}

function syncVxeSelection() {
  nextTick(() => {
    const table = repoTableRef.value;
    if (!table) {
      return;
    }
    const selected = visibleRepositories.value.filter((repository) => repository.selected);
    table.clearCheckboxRow().then(() => {
      if (selected.length) {
        return table.setCheckboxRow(selected, true);
      }
      return undefined;
    });
  });
}

function handleVxeSelectionChange(params: VxeTableDefines.CheckboxChangeEventParams<RepositoryRecord>) {
  const selectedPaths = new Set(params.records.map((repository) => repository.path));
  for (const repository of visibleRepositories.value) {
    repository.selected = selectedPaths.has(repository.path);
  }
  saveRepositories().catch((error) => handleError("保存选择状态失败", error));
}

function handleVxeColumnDragEnd() {
  window.setTimeout(() => {
    const nextOrder = repoTableRef.value
      ?.getTableColumn()
      .visibleColumn.map((column) => column.field)
      .filter((field): field is RepositoryColumnKey =>
        defaultRepositoryColumnKeys.includes(field as RepositoryColumnKey),
      );
    if (!nextOrder?.length) {
      return;
    }
    const normalizedOrder = normalizeRepositoryColumnOrder(nextOrder);
    if (normalizedOrder.join("|") === repositoryColumnOrder.value.join("|")) {
      return;
    }
    repositoryColumnOrder.value = normalizedOrder;
    saveUiState();
  }, 0);
}

function handleRepositoryColumnDragPointer(event: MouseEvent | DragEvent) {
  lastColumnDragPointer = {
    clientX: event.clientX,
    clientY: event.clientY,
  };
  if (event.type === "dragend") {
    columnDragHiddenDuringNativeDrag = hideColumnByVerticalDrag();
  }
}

function handleRepositoryColumnDragStart(params: VxeTableDefines.ColumnDragstartEventParams<RepositoryRecord>) {
  columnDragHiddenDuringNativeDrag = false;
  const field = params.column.field as RepositoryColumnKey | undefined;
  if (!field || !defaultRepositoryColumnKeys.includes(field) || !lastColumnDragPointer) {
    columnDragStart = null;
    return;
  }
  columnDragStart = {
    field,
    clientX: lastColumnDragPointer.clientX,
    clientY: lastColumnDragPointer.clientY,
  };
}

function shouldHideDraggedColumn(field: RepositoryColumnKey) {
  if (!lastColumnDragPointer || !columnDragStart || columnDragStart.field !== field) {
    return false;
  }
  const deltaX = Math.abs(lastColumnDragPointer.clientX - columnDragStart.clientX);
  const deltaY = Math.abs(lastColumnDragPointer.clientY - columnDragStart.clientY);
  return deltaY >= COLUMN_HIDE_DRAG_THRESHOLD && deltaY > deltaX;
}

function hideRepositoryColumn(key: RepositoryColumnKey) {
  if (requiredRepositoryColumnKeys.includes(key)) {
    ElMessage.warning("仓库列不能隐藏。");
    return;
  }
  if (!hiddenRepositoryColumns.value.includes(key)) {
    hiddenRepositoryColumns.value = [...hiddenRepositoryColumns.value, key];
  }
  saveUiState();
  ElMessage.success(`已隐藏列：${repositoryColumnMap.get(key)?.title || key}`);
}

function hideColumnByVerticalDrag() {
  const field = columnDragStart?.field;
  if (!field || !defaultRepositoryColumnKeys.includes(field) || !shouldHideDraggedColumn(field)) {
    return false;
  }
  hideRepositoryColumn(field);
  columnDragStart = null;
  return true;
}

function handleRepositoryColumnDragEnd(params: VxeTableDefines.ColumnDragendEventParams<RepositoryRecord>) {
  if (columnDragHiddenDuringNativeDrag) {
    columnDragHiddenDuringNativeDrag = false;
    columnDragStart = null;
    return;
  }
  const field = params.dragColumn?.field as RepositoryColumnKey | undefined;
  if (field && defaultRepositoryColumnKeys.includes(field)) {
    columnDragStart = {
      ...(columnDragStart ?? { clientX: lastColumnDragPointer?.clientX ?? 0, clientY: lastColumnDragPointer?.clientY ?? 0 }),
      field,
    };
  }
  if (hideColumnByVerticalDrag()) {
    return;
  }
  columnDragStart = null;
  handleVxeColumnDragEnd();
}

function handleVxeColumnResize(params: VxeTableDefines.ResizableChangeEventParams<RepositoryRecord>) {
  const key = params.column.field as RepositoryColumnKey | undefined;
  if (!key || !defaultRepositoryColumnKeys.includes(key)) {
    return;
  }
  repositoryColumnWidths[key] = Math.max(44, Math.round(params.resizeWidth));
  saveUiState();
}

function startDetailResize(event: PointerEvent) {
  const grid = contentGridRef.value;
  if (!grid) {
    return;
  }
  event.preventDefault();
  const bounds = grid.getBoundingClientRect();
  layoutResizeState = {
    kind: "detail",
    startX: event.clientX,
    startWidth: layoutDetailWidth.value,
    minWidth: MIN_LAYOUT_DETAIL_WIDTH,
    maxWidth: Math.max(MIN_LAYOUT_DETAIL_WIDTH, bounds.width - MIN_LAYOUT_REPO_WIDTH - LAYOUT_SPLITTER_SIZE),
  };
  document.body.dataset.layoutResizeAxis = "x";
  document.body.classList.add("layout-resizing");
  window.addEventListener("pointermove", handleLayoutResize);
  window.addEventListener("pointerup", stopLayoutResize, { once: true });
  window.addEventListener("pointercancel", stopLayoutResize, { once: true });
}

function startActivityResize(event: PointerEvent) {
  const leftLayout = contentGridRef.value?.querySelector<HTMLElement>(".left-layout");
  const repoPanel = leftLayout?.querySelector<HTMLElement>(".repo-panel");
  const activityPanel = leftLayout?.querySelector<HTMLElement>(".activity-panel");
  if (!leftLayout || !repoPanel || !activityPanel) {
    return;
  }
  event.preventDefault();
  const repoHeight = repoPanel.getBoundingClientRect().height;
  const activityHeight = activityPanel.getBoundingClientRect().height;
  layoutResizeState = {
    kind: "activity",
    startY: event.clientY,
    startHeight: layoutActivityHeight.value,
    minHeight: MIN_LAYOUT_ACTIVITY_HEIGHT,
    maxHeight: Math.max(MIN_LAYOUT_ACTIVITY_HEIGHT, activityHeight + repoHeight - MIN_LAYOUT_CONTENT_HEIGHT),
  };
  document.body.dataset.layoutResizeAxis = "y";
  document.body.classList.add("layout-resizing");
  window.addEventListener("pointermove", handleLayoutResize);
  window.addEventListener("pointerup", stopLayoutResize, { once: true });
  window.addEventListener("pointercancel", stopLayoutResize, { once: true });
}

function handleLayoutResize(event: PointerEvent) {
  if (!layoutResizeState) {
    return;
  }
  if (layoutResizeState.kind === "detail") {
    const delta = layoutResizeState.startX - event.clientX;
    layoutDetailWidth.value = Math.round(clamp(
      layoutResizeState.startWidth + delta,
      layoutResizeState.minWidth,
      layoutResizeState.maxWidth,
    ));
    return;
  }
  const delta = layoutResizeState.startY - event.clientY;
  layoutActivityHeight.value = Math.round(clamp(
    layoutResizeState.startHeight + delta,
    layoutResizeState.minHeight,
    layoutResizeState.maxHeight,
  ));
}

function stopLayoutResize() {
  if (!layoutResizeState) {
    return;
  }
  layoutResizeState = null;
  delete document.body.dataset.layoutResizeAxis;
  document.body.classList.remove("layout-resizing");
  window.removeEventListener("pointermove", handleLayoutResize);
  window.removeEventListener("pointerup", stopLayoutResize);
  window.removeEventListener("pointercancel", stopLayoutResize);
  saveUiState();
}

function graphLaneX(index: number) {
  return LOG_GRAPH_SLOT_WIDTH / 2 + index * LOG_GRAPH_SLOT_WIDTH;
}

function graphLaneColor(index: number) {
  return LOG_GRAPH_COLORS[index % LOG_GRAPH_COLORS.length];
}

function createEmptyLogGraphView(): LogGraphView {
  return {
    width: LOG_GRAPH_MIN_WIDTH,
    height: 0,
    segments: [],
    nodes: [],
  };
}

function getLogGraphChars(rawGraph: string) {
  return Array.from(rawGraph || "*");
}

function uniqueLaneNumbers(values: number[]) {
  return Array.from(new Set(values)).sort((left, right) => left - right);
}

function selectGraphEdgeSourceLane(activeLanes: number[], targetLane: number) {
  const leftCandidate = [...activeLanes].reverse().find((lane) => lane < targetLane);
  if (leftCandidate !== undefined) {
    return leftCandidate;
  }
  return activeLanes.find((lane) => lane > targetLane);
}

function parseLogGraphRow(rawGraph: string): ParsedLogGraphRow {
  const chars = getLogGraphChars(rawGraph);
  const activeLanes: number[] = [];
  const verticalLanes: number[] = [];
  const nodeLanes: number[] = [];
  const downRightEdges: Array<{ from: number; to: number }> = [];
  const downLeftEdges: Array<{ from: number; to: number }> = [];
  const horizontalEdges: Array<{ from: number; to: number }> = [];

  for (let index = 0; index < chars.length; index += 1) {
    const char = chars[index];
    if (char === "|" || char === "*" || char === "o") {
      const lane = Math.floor(index / 2);
      activeLanes.push(lane);
      verticalLanes.push(lane);
      if (char === "*" || char === "o") {
        nodeLanes.push(lane);
      }
      continue;
    }

    if (char === "\\") {
      const from = Math.floor(index / 2);
      const to = from + 1;
      activeLanes.push(from, to);
      downRightEdges.push({ from, to });
      continue;
    }

    if (char === "/") {
      const from = Math.floor((index + 1) / 2);
      const to = from - 1;
      if (to >= 0) {
        activeLanes.push(from, to);
        downLeftEdges.push({ from, to });
      }
      continue;
    }

    if (char === "-" || char === "_") {
      const from = Math.floor(index / 2);
      const to = from + 1;
      activeLanes.push(from, to);
      horizontalEdges.push({ from, to });
    }
  }

  const normalizedActiveLanes = uniqueLaneNumbers(activeLanes);
  return {
    laneCount: Math.max(1, (normalizedActiveLanes.at(-1) ?? -1) + 1),
    activeLanes: normalizedActiveLanes,
    verticalLanes: uniqueLaneNumbers(verticalLanes),
    nodeLanes: uniqueLaneNumbers(nodeLanes),
    downRightEdges,
    downLeftEdges,
    horizontalEdges,
  };
}

function buildVisualLogGraphRows(entries: GitLogEntry[], rowMetrics: Array<{ centerY: number }>) {
  const rows: VisualLogGraphRow[] = [];
  entries.forEach((entry, index) => {
    const currentY = rowMetrics[index].centerY;
    const connectorLines = entry.connectorLinesBefore || [];
    if (index > 0 && connectorLines.length) {
      const previousY = rowMetrics[index - 1].centerY;
      connectorLines.forEach((graph, connectorIndex) => {
        rows.push({
          key: `${entry.commitHash}-connector-${connectorIndex}`,
          y: previousY + ((connectorIndex + 1) * (currentY - previousY)) / (connectorLines.length + 1),
          parsed: parseLogGraphRow(graph),
        });
      });
    }
    rows.push({
      key: `${entry.commitHash}-commit`,
      y: currentY,
      parsed: parseLogGraphRow(entry.graph),
    });
  });
  return rows;
}

function setLogRowElement(commitHash: string, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLElement) {
    logRowElements.set(commitHash, element);
    return;
  }
  logRowElements.delete(commitHash);
}

function buildLogGraph(entries: GitLogEntry[]): LogGraphView {
  if (!entries.length) {
    return createEmptyLogGraphView();
  }

  const activeHashes = new Set(entries.map((entry) => entry.commitHash));
  for (const commitHash of Array.from(logRowElements.keys())) {
    if (!activeHashes.has(commitHash)) {
      logRowElements.delete(commitHash);
    }
  }

  const rowMetrics = entries.map((entry, index) => {
    const element = logRowElements.get(entry.commitHash);
    if (element) {
      const top = element.offsetTop;
      const height = element.offsetHeight;
      return {
        top,
        centerY: top + height / 2,
        bottom: top + height,
      };
    }
    const top = index * (LOG_GRAPH_ROW_FALLBACK_HEIGHT + LOG_GRAPH_ROW_GAP);
    return {
      top,
      centerY: top + LOG_GRAPH_ROW_FALLBACK_HEIGHT / 2,
      bottom: top + LOG_GRAPH_ROW_FALLBACK_HEIGHT,
    };
  });
  const visualRows = buildVisualLogGraphRows(entries, rowMetrics);
  const laneCount = Math.max(...visualRows.map((row) => row.parsed.laneCount));
  const width = Math.max(LOG_GRAPH_MIN_WIDTH, laneCount * LOG_GRAPH_SLOT_WIDTH);
  const segments: LogGraphSegment[] = [];
  const nodes: LogGraphNode[] = [];
  const laneColors: Array<string | undefined> = [];
  const listHeight = Math.max(
    logRowsRef.value?.scrollHeight || 0,
    rowMetrics.at(-1)?.bottom || 0,
    LOG_GRAPH_ROW_MIN_HEIGHT,
  );

  visualRows.forEach((row, rowIndex) => {
    const nextRow = visualRows[rowIndex + 1];
    const currentLaneColors = laneColors.slice();

    const resolveLaneColor = (laneIndex: number) => {
      const existingColor = currentLaneColors[laneIndex];
      if (existingColor) {
        return existingColor;
      }
      const fallbackColor = graphLaneColor(laneIndex);
      currentLaneColors[laneIndex] = fallbackColor;
      return fallbackColor;
    };

    row.parsed.activeLanes.forEach((laneIndex) => {
      resolveLaneColor(laneIndex);
    });

    row.parsed.nodeLanes.forEach((laneIndex) => {
      nodes.push({
        key: `${row.key}-node-${laneIndex}`,
        cx: graphLaneX(laneIndex),
        cy: row.y,
        color: resolveLaneColor(laneIndex),
      });
    });

    row.parsed.horizontalEdges.forEach((edge, edgeIndex) => {
      segments.push({
        key: `${row.key}-horizontal-${edgeIndex}`,
        x1: graphLaneX(edge.from),
        y1: row.y,
        x2: graphLaneX(edge.to),
        y2: row.y,
        color: resolveLaneColor(edge.from),
      });
    });

    if (!nextRow) {
      return;
    }

    const nextLaneColors: Array<string | undefined> = [];
    const currentActiveLanes = new Set(row.parsed.activeLanes);
    const nextActiveLanes = new Set(nextRow.parsed.activeLanes);
    row.parsed.verticalLanes.forEach((laneIndex) => {
      if (!nextActiveLanes.has(laneIndex)) {
        return;
      }
      const color = resolveLaneColor(laneIndex);
      segments.push({
        key: `${row.key}-vertical-${laneIndex}`,
        x1: graphLaneX(laneIndex),
        y1: row.y,
        x2: graphLaneX(laneIndex),
        y2: nextRow.y,
        color,
      });
      nextLaneColors[laneIndex] = color;
    });

    row.parsed.downRightEdges.forEach((edge, edgeIndex) => {
      const color = resolveLaneColor(edge.to);
      segments.push({
        key: `${row.key}-down-right-${edgeIndex}`,
        x1: graphLaneX(edge.from),
        y1: row.y,
        x2: graphLaneX(edge.to),
        y2: nextRow.y,
        color,
      });
      if (!nextLaneColors[edge.to]) {
        nextLaneColors[edge.to] = color;
      }
    });

    row.parsed.downLeftEdges.forEach((edge, edgeIndex) => {
      const color = resolveLaneColor(edge.from);
      segments.push({
        key: `${row.key}-down-left-${edgeIndex}`,
        x1: graphLaneX(edge.from),
        y1: row.y,
        x2: graphLaneX(edge.to),
        y2: nextRow.y,
        color,
      });
      if (!row.parsed.verticalLanes.includes(edge.from) && nextActiveLanes.has(edge.from)) {
        segments.push({
          key: `${row.key}-down-left-continue-${edgeIndex}`,
          x1: graphLaneX(edge.from),
          y1: row.y,
          x2: graphLaneX(edge.from),
          y2: nextRow.y,
          color,
        });
        nextLaneColors[edge.from] = color;
      }
    });

    nextRow.parsed.nodeLanes.forEach((laneIndex, nodeIndex) => {
      if (currentActiveLanes.has(laneIndex)) {
        return;
      }
      if (nextLaneColors[laneIndex]) {
        return;
      }
      const sourceLane = selectGraphEdgeSourceLane(row.parsed.activeLanes, laneIndex);
      if (sourceLane === undefined) {
        return;
      }
      const color = currentLaneColors[laneIndex] || graphLaneColor(laneIndex);
      segments.push({
        key: `${row.key}-inferred-entry-${nodeIndex}`,
        x1: graphLaneX(sourceLane),
        y1: row.y,
        x2: graphLaneX(laneIndex),
        y2: nextRow.y,
        color,
      });
      nextLaneColors[laneIndex] = color;
    });

    nextRow.parsed.activeLanes.forEach((laneIndex) => {
      if (!nextLaneColors[laneIndex]) {
        nextLaneColors[laneIndex] = graphLaneColor(laneIndex);
      }
    });

    laneColors.length = 0;
    nextLaneColors.forEach((color, laneIndex) => {
      if (color) {
        laneColors[laneIndex] = color;
      }
    });
  });

  return { width, height: listHeight, segments, nodes };
}

function updateLogGraphView() {
  if (activeTab.value !== "logs") {
    logGraphLayerView.value = createEmptyLogGraphView();
    return;
  }
  logGraphLayerView.value = buildLogGraph(selectedRepository.value?.logEntries || []);
}

function scheduleLogGraphViewUpdate() {
  nextTick(() => {
    updateLogGraphView();
  });
}

function handleError(prefix: string, error: unknown) {
  const message = `${prefix}: ${String(error)}`;
  statusText.value = message;
  addActivity(message, "danger");
  ElMessage.error(message);
}

onMounted(async () => {
  await setupProgressListener();
  await loadInitialState();
  syncVxeSelection();
  document.addEventListener("pointerdown", handleDocumentPointerDown, true);
  window.addEventListener("resize", scheduleLogGraphViewUpdate);
});

watch(importDialogVisible, () => {
  refreshRepositoryTableLayout(120);
});

watch(
  [
    () => selectedRepository.value?.path || "",
    () =>
      selectedRepository.value?.logEntries
        .map(
          (entry) =>
            `${entry.commitHash}:${entry.graph}:${(entry.connectorLinesBefore || []).join(",")}:${entry.subject}`,
        )
        .join("|") || "",
    activeTab,
  ],
  () => {
    scheduleLogGraphViewUpdate();
  },
  { flush: "post" },
);

onBeforeUnmount(() => {
  window.removeEventListener("pointermove", handleLayoutResize);
  window.removeEventListener("pointerup", stopLayoutResize);
  window.removeEventListener("pointercancel", stopLayoutResize);
  window.removeEventListener("resize", scheduleLogGraphViewUpdate);
  document.removeEventListener("pointerdown", handleDocumentPointerDown, true);
  document.body.classList.remove("layout-resizing");
  delete document.body.dataset.layoutResizeAxis;
});
</script>

<template>
  <el-config-provider>
    <main class="app-shell">
      <section ref="workspaceRef" class="workspace" :style="workspaceStyle">
        <header class="topbar">
          <div class="topbar-title">
            <div class="brand-mark">GB</div>
            <div>
              <h1>GitHub Batch Manager</h1>
              <p>集中维护本地 Git 仓库，批量刷新、拉取、提交、推送并查看提交记录。</p>
            </div>
          </div>
          <el-tag class="status-tag" :type="busy ? 'warning' : 'success'" effect="light" round>
            {{ statusText }}
          </el-tag>
        </header>

        <section class="control-strip" aria-label="仓库操作">
          <el-button id="importPathsButton" type="primary" :icon="FolderOpened" :disabled="busy" @click="selectImportDirectories">
            导入路径
          </el-button>
          <el-button id="pastePathsButton" :icon="DocumentAdd" :disabled="busy" @click="openTextImportDialog">
            粘贴路径
          </el-button>
          <el-button id="refreshButton" :icon="Refresh" :loading="busy" @click="refreshRepositories()">
            刷新状态
          </el-button>
          <el-popover
            popper-class="pull-strategy-popover"
            placement="bottom-start"
            trigger="hover"
            :show-after="120"
            :hide-after="120"
            :width="180"
          >
            <template #reference>
              <el-button id="pullButton" :icon="Download" :disabled="busy || !selectedRepositoriesCanPull">
                批量拉取
              </el-button>
            </template>
            <div class="pull-strategy-menu" aria-label="拉取策略">
              <button
                v-for="option in pullStrategyOptions"
                :key="option.value"
                type="button"
                class="pull-strategy-item"
                :disabled="busy || !selectedRepositoriesCanPull"
                @click="runOperation('pull', option.value)"
              >
                {{ option.label }}
              </button>
            </div>
          </el-popover>
          <el-button id="commitButton" :icon="Check" :disabled="busy" @click="runOperation('commit')">
            批量提交
          </el-button>
          <el-button id="pushButton" :icon="Upload" :disabled="busy || !selectedRepositoriesCanPush" @click="runOperation('push')">
            批量推送
          </el-button>
          <el-divider direction="vertical" />
          <el-button id="removeButton" :icon="Delete" :disabled="busy" @click="removeSelected">
            移除选中
          </el-button>
          <el-button id="columnSettingsButton" :disabled="busy" @click="columnSettingsVisible = true">
            列设置
          </el-button>
        </section>

        <section ref="contentGridRef" class="content-grid" :style="contentGridStyle">
          <section class="left-layout" :style="{ gridTemplateRows: `minmax(${MIN_LAYOUT_CONTENT_HEIGHT}px, 1fr) ${LAYOUT_SPLITTER_SIZE}px minmax(${MIN_LAYOUT_ACTIVITY_HEIGHT}px, ${layoutActivityHeight}px)` }">
            <section class="repo-panel">
              <div class="panel-toolbar">
                <div>
                  <h3>仓库列表</h3>
                  <p id="repoSummary">{{ repositorySummary }}</p>
                </div>
                <div class="table-tools">
                  <el-input
                    id="searchInput"
                    v-model="searchText"
                    clearable
                    :prefix-icon="Search"
                    placeholder="搜索名称、分支、路径或状态"
                    :disabled="busy"
                  />
                  <el-checkbox id="failedOnlyCheckbox" v-model="failedOnly" :disabled="busy">只看失败项</el-checkbox>
                </div>
              </div>

            <div id="repoTable" class="repo-vxe-table" @contextmenu.prevent="handleRepoTableContextMenu">
              <vxe-table
                ref="repoTableRef"
                  :data="visibleRepositories"
                  height="100%"
                  border
                  stripe
                  auto-resize
                  :sync-resize="importDialogVisible"
                  show-overflow="title"
                  show-header-overflow="title"
                  :row-class-name="tableRowClassName"
                  :row-config="{ keyField: 'path', isCurrent: true }"
                  :column-config="{ resizable: true, drag: true, useKey: true }"
                  :column-drag-config="repositoryColumnDragConfig"
                  :resizable-config="{ minWidth: 44 }"
                  :checkbox-config="{ checkField: 'selected', reserve: true, highlight: true }"
                  @cell-click="selectRepositoryFromVxe"
                  @checkbox-change="handleVxeSelectionChange"
                  @checkbox-all="handleVxeSelectionChange"
                  @column-resizable-change="handleVxeColumnResize"
                  @mousedown.capture="handleRepositoryColumnDragPointer"
                  @mousemove.capture="handleRepositoryColumnDragPointer"
                  @dragstart.capture="handleRepositoryColumnDragPointer"
                  @dragover.capture="handleRepositoryColumnDragPointer"
                  @dragend.capture="handleRepositoryColumnDragPointer"
                  @column-dragstart="handleRepositoryColumnDragStart"
                  @column-dragend="handleRepositoryColumnDragEnd"
              >
                  <vxe-column type="checkbox" field="selected" width="54" align="center" />
                  <vxe-column
                    v-for="column in visibleRepositoryColumns"
                    :key="column.key"
                    :field="column.key"
                    :title="column.title"
                    :width="columnWidth(column)"
                    :min-width="column.minWidth"
                    :align="column.align"
                    :sortable="column.sortable"
                    :show-overflow="['dirty', 'lastOperationStatus'].includes(column.key) ? false : 'title'"
                    :filters="
                      column.key === 'branch'
                        ? branchFilters
                        : column.key === 'dirty'
                          ? dirtyFilters
                          : column.key === 'lastOperationStatus'
                            ? operationStatusFilters
                            : undefined
                    "
                    :filter-method="
                      column.key === 'branch'
                        ? branchFilterMethod
                        : column.key === 'dirty'
                          ? dirtyFilterMethod
                          : column.key === 'lastOperationStatus'
                            ? statusFilterMethod
                            : undefined
                    "
                    :filter-multiple="false"
                  >
                    <template #default="{ row }">
                      <strong v-if="column.key === 'name'" class="repo-name-cell">{{ row.name || "-" }}</strong>
                      <span v-else-if="column.key === 'path'" class="repo-path-cell">
                        {{ normalizeRepositoryPathForDisplay(row.path) }}
                      </span>
                      <el-tag v-else-if="column.key === 'dirty'" :type="row.dirty ? 'warning' : 'success'" effect="light" round>
                        {{ row.dirty ? "有" : "净" }}
                      </el-tag>
                      <el-tag v-else-if="column.key === 'accessMode'" effect="light" round>
                        {{ repositoryAccessModeLabel(row.accessMode) }}
                      </el-tag>
                      <span v-else-if="column.key === 'lastCommit'">
                        {{ row.lastCommit || "-" }}
                        <small v-if="row.lastCommitAge" class="commit-age">{{ row.lastCommitAge }}</small>
                      </span>
                      <el-tag v-else-if="column.key === 'lastOperationStatus'" :type="statusType(row.lastOperationStatus)" effect="light" round>
                        {{ statusLabel(row.lastOperationStatus) }}
                      </el-tag>
                      <span v-else>{{ row[column.key] || "-" }}</span>
                    </template>
                  </vxe-column>
                </vxe-table>
              </div>
            </section>

            <button
              type="button"
              class="layout-splitter layout-splitter-horizontal"
              aria-label="调整操作日志高度"
              @pointerdown="startActivityResize"
            />

            <section class="activity-panel" aria-label="操作日志">
              <div class="activity-header">
                <h3>操作日志</h3>
                <el-button id="clearActivityButton" size="small" :icon="Delete" @click="activityLog = []">清空</el-button>
              </div>
              <div ref="activityLogRef" id="activityLog" class="activity-log">
                <div v-for="item in activityLog" :key="item.id" class="activity-line" :class="`level-${item.level}`">
                  <span>{{ item.time }}</span>
                  <p>{{ item.text }}</p>
                </div>
              </div>
            </section>
          </section>

          <button
            type="button"
            class="layout-splitter layout-splitter-vertical"
            aria-label="调整详情宽度"
            @pointerdown="startDetailResize"
          />

          <aside class="detail-panel">
            <el-tabs v-model="activeTab" stretch>
              <el-tab-pane label="详情" name="details">
                <el-descriptions v-if="selectedRepository" :column="1" border>
                  <el-descriptions-item label="仓库">{{ selectedRepository.name }}</el-descriptions-item>
                  <el-descriptions-item label="路径">{{ selectedRepository.path }}</el-descriptions-item>
                  <el-descriptions-item label="分支">{{ selectedRepository.branch || "-" }}</el-descriptions-item>
                  <el-descriptions-item label="同步">
                    领先 {{ selectedRepository.ahead || 0 }}，落后 {{ selectedRepository.behind || 0 }}
                  </el-descriptions-item>
                  <el-descriptions-item label="权限">
                    <el-select
                      :model-value="selectedRepository.accessMode"
                      size="small"
                      :disabled="busy"
                      @change="(value: RepositoryAccessMode) => updateSelectedRepositoryAccessMode(value)"
                    >
                      <el-option
                        v-for="option in repositoryAccessModeOptions"
                        :key="option.value"
                        :label="option.label"
                        :value="option.value"
                      />
                    </el-select>
                  </el-descriptions-item>
                  <el-descriptions-item label="状态">{{ selectedRepository.statusMessage || "-" }}</el-descriptions-item>
                  <el-descriptions-item v-if="selectedRepository.lastErrorMessage" label="错误">
                    {{ selectedRepository.lastErrorMessage }}
                  </el-descriptions-item>
                </el-descriptions>
                <el-empty v-else description="请选择一个仓库" />
              </el-tab-pane>

              <el-tab-pane label="日志树" name="logs">
                <div class="tab-action-row">
                  <span id="logSummary">{{ logSummary }}</span>
                  <el-button id="loadLogsButton" size="small" :icon="Refresh" :disabled="busy || !selectedRepository" @click="loadLogs">
                    加载日志
                  </el-button>
                </div>
                <div v-if="selectedRepository?.logEntries?.length" id="logRows" ref="logRowsRef" class="log-list">
                  <div
                    class="log-graph-layer"
                    :style="{ width: `${logGraphLayerView.width}px`, height: `${logGraphLayerView.height}px` }"
                    aria-hidden="true"
                  >
                    <svg
                      class="log-graph-svg"
                      :viewBox="`0 0 ${logGraphLayerView.width} ${logGraphLayerView.height || LOG_GRAPH_ROW_MIN_HEIGHT}`"
                    >
                      <line
                        v-for="segment in logGraphLayerView.segments"
                        :key="segment.key"
                        :x1="segment.x1"
                        :y1="segment.y1"
                        :x2="segment.x2"
                        :y2="segment.y2"
                        :stroke="segment.color"
                      />
                      <circle
                        v-for="node in logGraphLayerView.nodes"
                        :key="node.key"
                        :cx="node.cx"
                        :cy="node.cy"
                        :r="LOG_GRAPH_NODE_RADIUS"
                        :fill="node.color"
                      />
                    </svg>
                  </div>
                  <button
                    v-for="entry in selectedRepository.logEntries"
                    :key="entry.commitHash"
                    class="log-row"
                    :class="{ active: entry.commitHash === selectedCommitHash }"
                    type="button"
                    :ref="(element) => setLogRowElement(entry.commitHash, element)"
                    @click="selectCommit(entry)"
                  >
                    <span class="log-graph" :title="entry.graph || '*'" :style="{ width: `${logGraphLayerView.width}px` }">
                      <span class="log-graph-placeholder" />
                    </span>
                    <span class="log-body">
                      <strong>{{ entry.subject || "(无提交说明)" }}</strong>
                      <small>
                        {{ [entry.shortHash, entry.currentRef || entry.remoteRefs || entry.tagRefs, entry.author, entry.date].filter(Boolean).join(" · ") }}
                      </small>
                    </span>
                    <span class="log-tags">
                      <el-tag v-if="entry.isHead" size="small" type="primary">HEAD</el-tag>
                      <el-tag v-if="entry.hasTag" size="small" type="warning">TAG</el-tag>
                      <el-tag v-if="entry.hasRemoteRef" size="small" type="success">REMOTE</el-tag>
                    </span>
                  </button>
                </div>
                <el-empty v-else description="点击加载日志读取提交历史" />
              </el-tab-pane>

              <el-tab-pane label="提交详情" name="commit">
                <div class="tab-action-row">
                  <span id="commitSummary">{{ commitSummary }}</span>
                </div>
                <pre id="commitDetailText" class="commit-detail">{{ commitDetailText }}</pre>
                <el-table id="changedFiles" :data="changedFiles" border size="small" height="220">
                  <el-table-column prop="path" label="路径" min-width="220" show-overflow-tooltip />
                  <el-table-column prop="status" label="状态" width="90" />
                  <el-table-column prop="additions" label="新增" width="76" align="right" />
                  <el-table-column prop="deletions" label="删除" width="76" align="right" />
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </aside>
        </section>
      </section>

      <el-dialog v-model="importDialogVisible" title="导入路径" width="720px">
        <p class="dialog-hint">每行输入一个仓库目录或父目录。父目录会递归扫描其中的 Git 仓库。</p>
        <el-input
          id="pathsInput"
          v-model="importPathsText"
          type="textarea"
          :rows="9"
          placeholder="G:\04 AI\example-repo&#10;F:\Github"
        />
        <template #footer>
          <el-button @click="importDialogVisible = false">取消</el-button>
          <el-button id="confirmImportButton" type="primary" :loading="busy" @click="importPaths">导入</el-button>
        </template>
      </el-dialog>

      <el-drawer v-model="columnSettingsVisible" title="仓库表格列设置" size="360px">
        <div class="column-settings">
          <p>主表格已切换为 vxe-table。拖动表头可调整列顺序，拖动列边界可调整宽度，关闭后保留当前布局。</p>
          <el-checkbox
            v-for="column in orderedRepositoryColumns"
            :key="column.key"
            :model-value="!hiddenRepositoryColumns.includes(column.key)"
            :disabled="requiredRepositoryColumnKeys.includes(column.key)"
            @change="(value: string | number | boolean) => setColumnVisible(column.key, Boolean(value))"
          >
            {{ column.title }}
          </el-checkbox>
          <div class="column-settings-actions">
            <el-button @click="showAllColumns">显示全部</el-button>
            <el-button @click="resetTableLayout">重置布局</el-button>
          </div>
        </div>
      </el-drawer>
      <div
        v-if="repoContextMenuVisible"
        ref="repoContextMenuRef"
        class="repo-context-menu"
        :class="repoContextMenuClass"
        :style="repoContextMenuStyle"
      >
        <template v-for="(group, groupIndex) in repoContextMenuOptions" :key="groupIndex">
          <div v-if="groupIndex > 0" class="repo-context-menu-separator" />
          <div
            v-for="option in group"
            :key="option.code || option.name"
            class="repo-context-menu-item"
            :class="{ disabled: option.disabled, loading: option.loading, hasChildren: !!option.children?.length }"
            @mouseenter="handleRepoContextMenuItemEnter(option, $event)"
            @click.stop="handleRepoContextMenuOptionClick(option)"
          >
            <span class="repo-context-menu-label">{{ option.name }}</span>
            <span v-if="option.children?.length" class="repo-context-menu-arrow">›</span>
            <div
              v-if="option.children?.length"
              class="repo-context-menu-submenu"
              :style="getRepoContextMenuSubmenuStyle(option)"
            >
              <div
                v-for="child in option.children"
                :key="child.code || child.name"
                class="repo-context-menu-item"
                :class="{ disabled: child.disabled, loading: child.loading }"
                @click.stop="handleRepoContextMenuOptionClick(child)"
              >
                <span class="repo-context-menu-label">{{ child.name }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>
    </main>
  </el-config-provider>
</template>
