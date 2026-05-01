use crate::discovery;
use crate::git_service::GitRepositoryService;
use crate::models::{
    AppState, BatchProgressEvent, GitCommitView, GitLogResult, OperationResult,
    RepositoryOperationResult, RepositoryRecord, AppUiState,
};
use crate::store::RepositoryStore;
use std::path::Path;
use tauri::{AppHandle, Emitter};

#[tauri::command]
pub fn load_app_state() -> Result<AppState, String> {
    Ok(RepositoryStore::new().load())
}

#[tauri::command]
pub fn save_repositories(
    repositories: Vec<RepositoryRecord>,
    ui_state: Option<AppUiState>,
) -> Result<(), String> {
    let existing_state = RepositoryStore::new().load().ui_state;
    let ui_state = ui_state.unwrap_or(existing_state);
    RepositoryStore::new()
        .save(&repositories, &ui_state)
        .map_err(|error| format!("保存仓库列表失败: {error}"))
}

#[tauri::command]
pub async fn discover_repositories(paths: Vec<String>) -> Result<Vec<RepositoryRecord>, String> {
    Ok(discovery::discover(&paths)
        .into_iter()
        .map(RepositoryRecord::new)
        .collect())
}

#[tauri::command]
pub async fn refresh_repositories(
    repositories: Vec<RepositoryRecord>,
) -> Result<Vec<RepositoryRecord>, String> {
    let service = GitRepositoryService::new();
    Ok(repositories
        .into_iter()
        .map(|mut repository| {
            let snapshot = service.get_snapshot(Path::new(&repository.path));
            repository.apply_snapshot(snapshot);
            repository.last_operation_status = "idle".to_string();
            repository.last_error_message = String::new();
            repository
        })
        .collect())
}

#[tauri::command]
pub async fn pull_repositories(
    app: AppHandle,
    repositories: Vec<RepositoryRecord>,
    strategy: String,
) -> Result<Vec<RepositoryOperationResult>, String> {
    run_batch(app, repositories, "pull", |service, repository| {
        service.pull(Path::new(&repository.path), &repository.name, &strategy)
    })
}

#[tauri::command]
pub async fn commit_repositories(
    app: AppHandle,
    repositories: Vec<RepositoryRecord>,
    message: String,
) -> Result<Vec<RepositoryOperationResult>, String> {
    run_batch(app, repositories, "commit", |service, repository| {
        service.commit_all(Path::new(&repository.path), &repository.name, &message)
    })
}

#[tauri::command]
pub async fn push_repositories(
    app: AppHandle,
    repositories: Vec<RepositoryRecord>,
) -> Result<Vec<RepositoryOperationResult>, String> {
    run_batch(app, repositories, "push", |service, repository| {
        service.push(Path::new(&repository.path), &repository.name)
    })
}

#[tauri::command]
pub async fn load_log_entries(path: String, limit: Option<usize>) -> Result<GitLogResult, String> {
    let service = GitRepositoryService::new();
    Ok(service.load_log_entries(Path::new(&path), limit.unwrap_or(120)))
}

#[tauri::command]
pub async fn load_commit_view(path: String, commit_hash: String) -> Result<GitCommitView, String> {
    let service = GitRepositoryService::new();
    Ok(service.load_commit_view(Path::new(&path), &commit_hash))
}

fn run_batch(
    app: AppHandle,
    repositories: Vec<RepositoryRecord>,
    action_name: &str,
    action: impl Fn(&GitRepositoryService, &RepositoryRecord) -> OperationResult,
) -> Result<Vec<RepositoryOperationResult>, String> {
    let service = GitRepositoryService::new();
    let total = repositories.len();
    Ok(repositories
        .into_iter()
        .enumerate()
        .map(|(index, mut repository)| {
            let item_index = index + 1;
            emit_batch_progress(
                &app,
                BatchProgressEvent {
                    phase: "started".to_string(),
                    action: action_name.to_string(),
                    index: item_index,
                    total,
                    repository_path: repository.path.clone(),
                    repository_name: repository.name.clone(),
                    repository: None,
                    result: None,
                },
            );

            let result = action(&service, &repository);
            let snapshot = service.get_snapshot(Path::new(&repository.path));
            repository.apply_snapshot(snapshot);
            repository.last_operation_status = result.status.clone();
            repository.last_error_message = if result.status == "failed" {
                result.message.clone()
            } else {
                String::new()
            };
            repository.status_message = summarize_result_message(&result);

            let operation_result = RepositoryOperationResult { repository, result };
            emit_batch_progress(
                &app,
                BatchProgressEvent {
                    phase: "finished".to_string(),
                    action: action_name.to_string(),
                    index: item_index,
                    total,
                    repository_path: operation_result.repository.path.clone(),
                    repository_name: operation_result.repository.name.clone(),
                    repository: Some(operation_result.repository.clone()),
                    result: Some(operation_result.result.clone()),
                },
            );

            operation_result
        })
        .collect())
}

fn emit_batch_progress(app: &AppHandle, payload: BatchProgressEvent) {
    let _ = app.emit("batch-progress", payload);
}

fn summarize_result_message(result: &OperationResult) -> String {
    let prefix = match result.status.as_str() {
        "success" => format!("{}成功", result.action),
        "failed" => format!("{}失败", result.action),
        "skipped" => format!("{}跳过", result.action),
        _ => result.action.clone(),
    };
    let mut first_line = result
        .message
        .lines()
        .next()
        .unwrap_or_default()
        .trim()
        .to_string();
    if first_line.chars().count() > 44 {
        first_line = first_line.chars().take(44).collect::<String>();
        first_line = first_line.trim_end().to_string();
        first_line.push_str("...");
    }
    format!("{prefix}: {first_line}")
}
