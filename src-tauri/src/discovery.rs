use crate::models::normalize_repository_path;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

const IGNORED_DIRECTORIES: &[&str] = &[".git", "__pycache__", ".venv", "node_modules", "target"];

pub fn discover(raw_paths: &[String]) -> Vec<PathBuf> {
    let mut discovered: BTreeMap<String, PathBuf> = BTreeMap::new();

    for raw_path in raw_paths {
        if raw_path.trim().is_empty() {
            continue;
        }

        let candidate = PathBuf::from(normalize_repository_path(raw_path.trim()));
        if !candidate.exists() {
            continue;
        }

        if is_git_repository(&candidate) {
            let normalized = normalize_repository_path(&candidate);
            discovered.insert(normalized.to_lowercase(), PathBuf::from(normalized));
            continue;
        }

        if candidate.is_dir() {
            for repository_path in walk_for_repositories(&candidate) {
                let normalized = normalize_repository_path(&repository_path);
                discovered.insert(normalized.to_lowercase(), PathBuf::from(normalized));
            }
        }
    }

    discovered.into_values().collect()
}

fn walk_for_repositories(root_path: &Path) -> Vec<PathBuf> {
    let mut repositories = Vec::new();
    walk(root_path, &mut repositories);
    repositories
}

fn walk(current_path: &Path, repositories: &mut Vec<PathBuf>) {
    if is_git_repository(current_path) {
        repositories.push(current_path.to_path_buf());
        return;
    }

    let Ok(entries) = fs::read_dir(current_path) else {
        return;
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }

        let Some(name) = path.file_name().and_then(|item| item.to_str()) else {
            continue;
        };

        if IGNORED_DIRECTORIES.contains(&name) {
            continue;
        }

        walk(&path, repositories);
    }
}

fn is_git_repository(candidate: &Path) -> bool {
    if !candidate.is_dir() {
        return false;
    }

    let dot_git = candidate.join(".git");
    dot_git.is_dir() || dot_git.is_file()
}
