use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub fn normalize_repository_path(raw_path: impl AsRef<Path>) -> String {
    let path = raw_path.as_ref();
    let expanded = expand_home(path);
    let normalized = expanded
        .canonicalize()
        .unwrap_or(expanded)
        .to_string_lossy()
        .to_string();
    strip_windows_verbatim_prefix(&normalized)
}

fn strip_windows_verbatim_prefix(path: &str) -> String {
    path.strip_prefix(r"\\?\")
        .or_else(|| path.strip_prefix(r"\??\"))
        .unwrap_or(path)
        .to_string()
}

fn expand_home(path: &Path) -> PathBuf {
    let raw = path.to_string_lossy();
    if raw == "~" {
        return home_dir().unwrap_or_else(|| path.to_path_buf());
    }

    if let Some(rest) = raw.strip_prefix("~/").or_else(|| raw.strip_prefix("~\\")) {
        if let Some(home) = home_dir() {
            return home.join(rest);
        }
    }

    path.to_path_buf()
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum RepositoryAccessMode {
    PullOnly,
    PushOnly,
    PullPush,
}

impl Default for RepositoryAccessMode {
    fn default() -> Self {
        Self::PullPush
    }
}

impl RepositoryAccessMode {
    pub fn can_pull(self) -> bool {
        matches!(self, Self::PullOnly | Self::PullPush)
    }

    pub fn can_push(self) -> bool {
        matches!(self, Self::PushOnly | Self::PullPush)
    }

    pub fn denied_message(self, action: &str) -> &'static str {
        match (self, action) {
            (Self::PullOnly, "push") => "仅允许拉取",
            (Self::PushOnly, "pull") => "仅允许推送",
            _ => "当前项目不允许执行此操作",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RepositoryRecord {
    pub path: String,
    pub selected: bool,
    #[serde(default)]
    pub access_mode: RepositoryAccessMode,
    pub name: String,
    pub branch: String,
    pub dirty: bool,
    pub ahead: u32,
    pub behind: u32,
    pub last_commit: String,
    pub last_commit_age: String,
    pub status_message: String,
    pub last_operation_status: String,
    pub last_error_message: String,
    pub log_entries: Vec<GitLogEntry>,
    pub log_message: String,
    pub selected_commit_hash: String,
    pub commit_detail_text: String,
    pub commit_changed_files: Vec<GitChangedFile>,
}

impl RepositoryRecord {
    pub fn new(path: impl AsRef<Path>) -> Self {
        let normalized = normalize_repository_path(path);
        let name = Path::new(&normalized)
            .file_name()
            .and_then(|item| item.to_str())
            .filter(|item| !item.is_empty())
            .unwrap_or(&normalized)
            .to_string();

        Self {
            path: normalized,
            selected: true,
            access_mode: RepositoryAccessMode::default(),
            name,
            branch: String::new(),
            dirty: false,
            ahead: 0,
            behind: 0,
            last_commit: String::new(),
            last_commit_age: String::new(),
            status_message: "未刷新".to_string(),
            last_operation_status: "idle".to_string(),
            last_error_message: String::new(),
            log_entries: Vec::new(),
            log_message: "请选择一个仓库以查看日志树。".to_string(),
            selected_commit_hash: String::new(),
            commit_detail_text: String::new(),
            commit_changed_files: Vec::new(),
        }
    }

    pub fn apply_snapshot(&mut self, snapshot: RepositorySnapshot) {
        self.branch = snapshot.branch;
        self.dirty = snapshot.dirty;
        self.ahead = snapshot.ahead;
        self.behind = snapshot.behind;
        self.last_commit = snapshot.last_commit;
        self.last_commit_age = snapshot.last_commit_age;
        self.status_message = snapshot.status_message;
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RepositorySnapshot {
    pub branch: String,
    pub dirty: bool,
    pub ahead: u32,
    pub behind: u32,
    pub last_commit: String,
    pub last_commit_age: String,
    pub status_message: String,
}

impl RepositorySnapshot {
    pub fn empty(status_message: impl Into<String>) -> Self {
        Self {
            branch: String::new(),
            dirty: false,
            ahead: 0,
            behind: 0,
            last_commit: String::new(),
            last_commit_age: String::new(),
            status_message: status_message.into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct OperationResult {
    pub repository_path: String,
    pub repository_name: String,
    pub action: String,
    pub status: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RepositoryOperationResult {
    pub repository: RepositoryRecord,
    pub result: OperationResult,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct BatchProgressEvent {
    pub phase: String,
    pub action: String,
    pub index: usize,
    pub total: usize,
    pub repository_path: String,
    pub repository_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repository: Option<RepositoryRecord>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<OperationResult>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct GitLogEntry {
    pub graph: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub connector_lines_before: Vec<String>,
    pub commit_hash: String,
    pub short_hash: String,
    pub date: String,
    pub author: String,
    pub refs: String,
    pub subject: String,
    pub current_ref: String,
    pub remote_refs: String,
    pub tag_refs: String,
    pub is_head: bool,
    pub has_tag: bool,
    pub has_remote_ref: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct GitLogResult {
    pub entries: Vec<GitLogEntry>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct GitChangedFile {
    pub path: String,
    pub status: String,
    pub additions: String,
    pub deletions: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct GitCommitView {
    pub detail_text: String,
    pub files: Vec<GitChangedFile>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct WindowsExplorerMenuItem {
    pub label: String,
    pub verb_index: Option<u32>,
    pub is_separator: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct WindowsExplorerMenuResponse {
    pub supported: bool,
    pub items: Vec<WindowsExplorerMenuItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AppState {
    pub repositories: Vec<RepositoryRecord>,
    #[serde(default)]
    pub ui_state: AppUiState,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AppUiState {
    #[serde(default = "default_repository_columns")]
    pub repository_columns: Vec<String>,
    #[serde(default)]
    pub hidden_repository_columns: Vec<String>,
    #[serde(default)]
    pub repository_column_widths: std::collections::BTreeMap<String, u32>,
    #[serde(default)]
    pub layout_detail_width: Option<u32>,
    #[serde(default)]
    pub layout_activity_height: Option<u32>,
}

impl Default for AppUiState {
    fn default() -> Self {
        Self {
            repository_columns: default_repository_columns(),
            hidden_repository_columns: Vec::new(),
            repository_column_widths: std::collections::BTreeMap::new(),
            layout_detail_width: None,
            layout_activity_height: None,
        }
    }
}

fn default_repository_columns() -> Vec<String> {
    [
        "selected",
        "name",
        "path",
        "branch",
        "dirty",
        "ahead",
        "behind",
        "accessMode",
        "lastCommit",
        "lastOperationStatus",
        "statusMessage",
    ]
    .iter()
    .map(|item| (*item).to_string())
    .collect()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct StoredRepositoryRecord {
    pub path: String,
    #[serde(default = "default_selected")]
    pub selected: bool,
    #[serde(default)]
    pub access_mode: RepositoryAccessMode,
}

fn default_selected() -> bool {
    true
}

impl From<&RepositoryRecord> for StoredRepositoryRecord {
    fn from(repository: &RepositoryRecord) -> Self {
        Self {
            path: repository.path.clone(),
            selected: repository.selected,
            access_mode: repository.access_mode,
        }
    }
}

impl From<StoredRepositoryRecord> for RepositoryRecord {
    fn from(stored: StoredRepositoryRecord) -> Self {
        let mut repository = RepositoryRecord::new(stored.path);
        repository.selected = stored.selected;
        repository.access_mode = stored.access_mode;
        repository
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repository_record_defaults_to_pull_push_access_mode() {
        let repository = RepositoryRecord::new("C:/repo");

        assert_eq!(repository.access_mode, RepositoryAccessMode::PullPush);
    }

    #[test]
    fn stored_repository_record_missing_access_mode_defaults_to_pull_push() {
        let stored: StoredRepositoryRecord = serde_json::from_value(serde_json::json!({
            "path": "C:/repo",
            "selected": false
        }))
        .expect("deserialize stored repository");

        let repository = RepositoryRecord::from(stored);

        assert_eq!(repository.access_mode, RepositoryAccessMode::PullPush);
        assert!(!repository.selected);
    }
}
