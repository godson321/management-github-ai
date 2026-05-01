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

#[cfg(test)]
mod tests {
    use super::discover;
    use std::fs;

    #[test]
    fn discovers_direct_repository_and_nested_repositories() {
        let root = std::env::temp_dir().join(format!("gbm-discovery-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let direct_repo = root.join("direct");
        let nested_repo = root.join("nested").join("repo-a");
        let plain_dir = root.join("plain");
        fs::create_dir_all(direct_repo.join(".git")).unwrap();
        fs::create_dir_all(nested_repo.join(".git")).unwrap();
        fs::create_dir_all(&plain_dir).unwrap();

        let discovered = discover(&[
            root.to_string_lossy().to_string(),
            direct_repo.to_string_lossy().to_string(),
            plain_dir.to_string_lossy().to_string(),
        ]);
        let mut names = discovered
            .iter()
            .filter_map(|path| path.file_name())
            .filter_map(|name| name.to_str())
            .collect::<Vec<_>>();
        names.sort_unstable();

        assert_eq!(names, vec!["direct", "repo-a"]);
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ignores_missing_paths() {
        let missing = std::env::temp_dir().join("gbm-missing-path");
        let discovered = discover(&[missing.to_string_lossy().to_string()]);
        assert!(discovered.is_empty());
    }
}
