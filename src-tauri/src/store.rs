use crate::models::{AppState, AppUiState, RepositoryRecord, StoredRepositoryRecord};
use serde_json::Value;
use std::fs;
use std::io;
use std::path::PathBuf;

pub struct RepositoryStore {
    file_path: PathBuf,
}

impl RepositoryStore {
    pub fn new() -> Self {
        Self {
            file_path: default_store_path(),
        }
    }

    pub fn load(&self) -> AppState {
        let Ok(raw) = fs::read_to_string(&self.file_path) else {
            return AppState {
                repositories: Vec::new(),
                ui_state: AppUiState::default(),
            };
        };

        let Ok(payload) = serde_json::from_str::<Value>(&raw) else {
            let _ = self.backup_invalid_store("invalid", &raw);
            return AppState {
                repositories: Vec::new(),
                ui_state: AppUiState::default(),
            };
        };

        let repo_items = if let Some(items) = payload.get("repositories") {
            items.clone()
        } else if payload.is_array() {
            payload.clone()
        } else {
            Value::Array(Vec::new())
        };

        let repositories = repo_items
            .as_array()
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| {
                        serde_json::from_value::<StoredRepositoryRecord>(item.clone()).ok()
                    })
                    .map(RepositoryRecord::from)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        let ui_state = payload
            .get("ui_state")
            .cloned()
            .and_then(|item| serde_json::from_value::<AppUiState>(item).ok())
            .unwrap_or_default();

        AppState {
            repositories,
            ui_state,
        }
    }

    pub fn save(
        &self,
        repositories: &[RepositoryRecord],
        ui_state: &AppUiState,
    ) -> Result<(), io::Error> {
        if let Some(parent) = self.file_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let temp_path = self.file_path.with_extension("tmp");
        let stored_repositories = repositories
            .iter()
            .map(StoredRepositoryRecord::from)
            .collect::<Vec<_>>();
        let serialized = serde_json::json!({
            "repositories": stored_repositories,
            "ui_state": ui_state,
        });

        fs::write(
            &temp_path,
            serde_json::to_string_pretty(&serialized).expect("store payload should serialize"),
        )?;
        if self.file_path.exists() {
            let backup_path = self.file_path.with_extension("bak");
            let _ = fs::remove_file(&backup_path);
            fs::rename(&self.file_path, &backup_path)?;
            match fs::rename(&temp_path, &self.file_path) {
                Ok(()) => {
                    let _ = fs::remove_file(backup_path);
                }
                Err(error) => {
                    let _ = fs::rename(&backup_path, &self.file_path);
                    let _ = fs::remove_file(&temp_path);
                    return Err(error);
                }
            }
        } else {
            fs::rename(temp_path, &self.file_path)?;
        }
        Ok(())
    }

    fn backup_invalid_store(&self, suffix: &str, raw: &str) -> io::Result<()> {
        if let Some(parent) = self.file_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let backup_path = self.file_path.with_extension(format!("{suffix}.json"));
        fs::write(backup_path, raw)
    }
}

fn default_store_path() -> PathBuf {
    if let Some(appdata) = std::env::var_os("APPDATA") {
        return PathBuf::from(appdata)
            .join("GitHubBatchManager")
            .join("repositories.json");
    }

    home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".github-batch-manager")
        .join("repositories.json")
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::RepositoryRecord;

    fn unique_temp_dir(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "github-batch-manager-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system clock before unix epoch")
                .as_nanos()
        ))
    }

    struct TempDirGuard(PathBuf);

    impl Drop for TempDirGuard {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn load_preserves_old_file_visibility_for_invalid_json() {
        let root = unique_temp_dir("store");
        std::fs::create_dir_all(&root).expect("create temp dir");
        let _guard = TempDirGuard(root.clone());
        let store_path = root.join("repositories.json");

        std::fs::write(&store_path, "{invalid json").expect("write invalid store");

        let store = RepositoryStore {
            file_path: store_path,
        };

        let state = store.load();

        assert!(state.repositories.is_empty());
        assert_eq!(state.ui_state, AppUiState::default());
    }

    #[test]
    fn load_keeps_backup_of_invalid_store_file() {
        let root = unique_temp_dir("store-invalid");
        std::fs::create_dir_all(&root).expect("create temp dir");
        let _guard = TempDirGuard(root.clone());
        let store_path = root.join("repositories.json");

        std::fs::write(&store_path, "{invalid json").expect("write invalid store");

        let store = RepositoryStore {
            file_path: store_path.clone(),
        };

        let _state = store.load();

        let backup_path = root.join("repositories.invalid.json");
        assert!(backup_path.exists(), "invalid payload should be backed up");
    }

    #[test]
    fn save_writes_recoverable_store_payload() {
        let root = unique_temp_dir("store-save");
        std::fs::create_dir_all(&root).expect("create temp dir");
        let _guard = TempDirGuard(root.clone());
        let store_path = root.join("repositories.json");
        let store = RepositoryStore {
            file_path: store_path.clone(),
        };

        store
            .save(&[RepositoryRecord::new("C:/repo")], &AppUiState::default())
            .expect("save state");

        let raw = std::fs::read_to_string(store_path).expect("read store");
        assert!(raw.contains("\"repositories\""));
        assert!(raw.contains("\"uiState\"") || raw.contains("\"ui_state\""));
    }
}
