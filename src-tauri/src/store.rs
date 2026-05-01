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

    #[cfg(test)]
    pub fn with_file_path(file_path: PathBuf) -> Self {
        Self { file_path }
    }

    pub fn load(&self) -> AppState {
        let Ok(raw) = fs::read_to_string(&self.file_path) else {
            return AppState {
                repositories: Vec::new(),
                ui_state: AppUiState::default(),
            };
        };

        let Ok(payload) = serde_json::from_str::<Value>(&raw) else {
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
            fs::remove_file(&self.file_path)?;
        }
        fs::rename(temp_path, &self.file_path)?;
        Ok(())
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
use super::RepositoryStore;
use crate::models::{AppUiState, RepositoryRecord};
    use std::fs;

    #[test]
    fn save_and_load_round_trip() {
        let root = std::env::temp_dir().join(format!("gbm-store-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let store = RepositoryStore::with_file_path(root.join("repositories.json"));
        let repositories = vec![RepositoryRecord::new(root.join("repo-one")), {
            let mut repository = RepositoryRecord::new(root.join("repo-two"));
            repository.selected = false;
            repository
        }];

        let ui_state = AppUiState::default();
        store.save(&repositories, &ui_state).unwrap();
        let loaded = store.load();

        assert_eq!(
            loaded
                .repositories
                .iter()
                .map(|item| item.path.as_str())
                .collect::<Vec<_>>(),
            repositories
                .iter()
                .map(|item| item.path.as_str())
                .collect::<Vec<_>>()
        );
        assert_eq!(
            loaded
                .repositories
                .iter()
                .map(|item| item.selected)
                .collect::<Vec<_>>(),
            vec![true, false]
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn invalid_json_returns_empty_list() {
        let root = std::env::temp_dir().join(format!("gbm-store-invalid-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let store_path = root.join("repositories.json");
        fs::write(&store_path, "{broken").unwrap();

        let store = RepositoryStore::with_file_path(store_path);
        assert!(store.load().repositories.is_empty());
        let _ = fs::remove_dir_all(&root);
    }
}
