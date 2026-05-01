export type OperationStatus = "idle" | "running" | "success" | "failed" | "skipped";

export interface RepositoryRecord {
  path: string;
  selected: boolean;
  name: string;
  branch: string;
  dirty: boolean;
  ahead: number;
  behind: number;
  lastCommit: string;
  lastCommitAge: string;
  statusMessage: string;
  lastOperationStatus: OperationStatus;
  lastErrorMessage: string;
  logEntries: GitLogEntry[];
  logMessage: string;
  selectedCommitHash: string;
  commitDetailText: string;
  commitChangedFiles: GitChangedFile[];
}

export interface AppState {
  repositories: RepositoryRecord[];
  uiState: AppUiState;
}

export interface AppUiState {
  repositoryColumns: string[];
  hiddenRepositoryColumns: string[];
  repositoryColumnWidths: Record<string, number>;
  layoutDetailWidth?: number;
  layoutActivityHeight?: number;
}

export interface OperationResult {
  repositoryPath: string;
  repositoryName: string;
  action: string;
  status: OperationStatus;
  message: string;
}

export interface RepositoryOperationResult {
  repository: RepositoryRecord;
  result: OperationResult;
}

export interface GitLogEntry {
  graph: string;
  connectorLinesBefore?: string[];
  commitHash: string;
  shortHash: string;
  date: string;
  author: string;
  refs: string;
  subject: string;
  currentRef: string;
  remoteRefs: string;
  tagRefs: string;
  isHead: boolean;
  hasTag: boolean;
  hasRemoteRef: boolean;
}

export interface GitLogResult {
  entries: GitLogEntry[];
  message: string;
}

export interface GitChangedFile {
  path: string;
  status: string;
  additions: string;
  deletions: string;
}

export interface GitCommitView {
  detailText: string;
  files: GitChangedFile[];
}

export interface BatchProgressEvent {
  phase: "started" | "finished";
  action: string;
  index: number;
  total: number;
  repositoryPath: string;
  repositoryName: string;
  repository?: RepositoryRecord;
  result?: OperationResult;
}

export interface ActivityItem {
  id: number;
  time: string;
  level: "info" | "success" | "warning" | "danger";
  text: string;
}

export interface WindowsExplorerMenuItem {
  label: string;
  verbIndex: number | null;
  isSeparator: boolean;
}

export interface WindowsExplorerMenuResponse {
  supported: boolean;
  items: WindowsExplorerMenuItem[];
}
