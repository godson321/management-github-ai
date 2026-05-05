use crate::discovery;
use crate::git_service::GitRepositoryService;
use crate::models::{
    AppState, AppUiState, BatchProgressEvent, GitCommitView, GitLogResult, OperationResult,
    RepositoryOperationResult, RepositoryRecord, WindowsExplorerMenuItem,
    WindowsExplorerMenuResponse,
};
use crate::store::RepositoryStore;
use serde_json::Value;
use std::path::Path;
use std::process::{Command, Stdio};
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
        .filter(|repository| {
            let repository_path = Path::new(&repository.path);
            repository_path.exists() && repository_path.is_dir()
        })
        .map(|mut repository| {
            let snapshot = service.get_snapshot(Path::new(&repository.path));
            repository.apply_snapshot(snapshot);
            repository.last_operation_status = "idle".to_string();
            repository.last_error_message = String::new();
            repository
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::normalize_repository_path;
    use std::future::Future;
    use std::path::PathBuf;
    use std::task::{Context, Poll, RawWaker, RawWakerVTable, Waker};

    fn block_on<F: Future>(future: F) -> F::Output {
        fn raw_waker() -> RawWaker {
            fn clone(_: *const ()) -> RawWaker {
                raw_waker()
            }
            fn wake(_: *const ()) {}
            fn wake_by_ref(_: *const ()) {}
            fn drop(_: *const ()) {}

            RawWaker::new(
                std::ptr::null(),
                &RawWakerVTable::new(clone, wake, wake_by_ref, drop),
            )
        }

        let waker = unsafe { Waker::from_raw(raw_waker()) };
        let mut future = Box::pin(future);
        let mut context = Context::from_waker(&waker);
        match Future::poll(future.as_mut(), &mut context) {
            Poll::Ready(value) => value,
            Poll::Pending => panic!("future unexpectedly pending"),
        }
    }

    struct TempDirGuard(PathBuf);

    impl Drop for TempDirGuard {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn unique_suffix() -> u128 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock before unix epoch")
            .as_nanos()
    }

    #[test]
    fn refresh_repositories_skips_missing_directories() {
        let root = std::env::temp_dir().join(format!(
            "github-batch-manager-refresh-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        std::fs::create_dir_all(root.join("existing")).expect("create temp dir");
        let _guard = TempDirGuard(root.clone());

        let repositories = vec![
            RepositoryRecord::new(root.join("missing")),
            RepositoryRecord::new(root.join("existing")),
        ];

        let refreshed = block_on(refresh_repositories(repositories)).expect("refresh succeeds");

        assert_eq!(refreshed.len(), 1);
        assert_eq!(refreshed[0].path, normalize_repository_path(root.join("existing")));
    }

    #[test]
    fn refresh_repositories_keeps_existing_directories() {
        let root = std::env::temp_dir().join(format!(
            "github-batch-manager-refresh-existing-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        std::fs::create_dir_all(root.join("existing")).expect("create temp dir");
        let _guard = TempDirGuard(root.clone());

        let repository = RepositoryRecord::new(root.join("existing"));

        let refreshed = block_on(refresh_repositories(vec![repository])).expect("refresh succeeds");

        assert_eq!(refreshed.len(), 1);
        assert_eq!(refreshed[0].path, normalize_repository_path(root.join("existing")));
    }
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

#[tauri::command]
pub async fn open_repository_folder(path: String) -> Result<(), String> {
    let target_path = Path::new(&path);
    if !target_path.exists() {
        return Err(format!("仓库目录不存在: {}", target_path.display()));
    }
    if !target_path.is_dir() {
        return Err(format!("目标不是目录: {}", target_path.display()));
    }

    #[cfg(target_os = "windows")]
    {
        Command::new("explorer.exe")
            .arg(target_path)
            .spawn()
            .map_err(|error| format!("无法打开仓库目录: {error}"))?;
        return Ok(());
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(target_path)
            .spawn()
            .map_err(|error| format!("无法打开仓库目录: {error}"))?;
        return Ok(());
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open")
            .arg(target_path)
            .spawn()
            .map_err(|error| format!("无法打开仓库目录: {error}"))?;
        return Ok(());
    }

    #[allow(unreachable_code)]
    Err("当前平台不支持打开仓库目录。".to_string())
}

#[tauri::command]
pub async fn list_windows_explorer_menu_items(path: String) -> Result<WindowsExplorerMenuResponse, String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = path;
        return Ok(WindowsExplorerMenuResponse {
            supported: false,
            items: Vec::new(),
        });
    }

    #[cfg(target_os = "windows")]
    {
        let target_path = Path::new(&path);
        if !target_path.exists() {
            return Err(format!("仓库目录不存在: {}", target_path.display()));
        }
        if !target_path.is_dir() {
            return Err(format!("目标不是目录: {}", target_path.display()));
        }

        let stdout = run_powershell_script(
            LIST_FOLDER_MENU_SCRIPT,
            target_path,
            None,
        )?;
        let items = parse_windows_explorer_menu_items(&stdout)?;
        Ok(WindowsExplorerMenuResponse {
            supported: true,
            items,
        })
    }
}

#[tauri::command]
pub async fn invoke_windows_explorer_menu_item(path: String, verb_index: u32) -> Result<(), String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (path, verb_index);
        return Err("Windows Explorer 菜单仅支持 Windows。".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        let target_path = Path::new(&path);
        if !target_path.exists() {
            return Err(format!("仓库目录不存在: {}", target_path.display()));
        }
        if !target_path.is_dir() {
            return Err(format!("目标不是目录: {}", target_path.display()));
        }

        run_powershell_script(INVOKE_FOLDER_MENU_SCRIPT, target_path, Some(verb_index))?;
        Ok(())
    }
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

#[cfg(target_os = "windows")]
const POWERSHELL_ENCODING_PREFIX: &str = "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $OutputEncoding=[Text.UTF8Encoding]::new($false); ";

#[cfg(target_os = "windows")]
const LIST_FOLDER_MENU_SCRIPT: &str = r#"
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
"#;

#[cfg(target_os = "windows")]
const INVOKE_FOLDER_MENU_SCRIPT: &str = r#"
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
"#;

#[cfg(target_os = "windows")]
fn run_powershell_script(
    script: &str,
    folder_path: &Path,
    verb_index: Option<u32>,
) -> Result<String, String> {
    let mut command = Command::new("powershell.exe");
    command
        .arg("-NoLogo")
        .arg("-NoProfile")
        .arg("-NonInteractive")
        .arg("-ExecutionPolicy")
        .arg("Bypass")
        .arg("-Command")
        .arg(format!("{POWERSHELL_ENCODING_PREFIX}{script}"))
        .env("GBM_TARGET_PATH", folder_path.as_os_str())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    match verb_index {
        Some(index) => {
            command.env("GBM_VERB_INDEX", index.to_string());
        }
        None => {
            command.env_remove("GBM_VERB_INDEX");
        }
    }

    let output = command
        .spawn()
        .and_then(|child| child.wait_with_output())
        .map_err(|error| format!("无法执行 PowerShell 命令: {error}"))?;

    if output.status.success() {
        return String::from_utf8(output.stdout)
            .map_err(|error| format!("PowerShell 输出不是有效 UTF-8: {error}"));
    }

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let message = if !stderr.is_empty() {
        stderr
    } else if !stdout.is_empty() {
        stdout
    } else {
        "Unknown Windows shell error.".to_string()
    };
    Err(message)
}

#[cfg(target_os = "windows")]
fn parse_windows_explorer_menu_items(stdout: &str) -> Result<Vec<WindowsExplorerMenuItem>, String> {
    let payload = stdout.trim();
    if payload.is_empty() {
        return Ok(Vec::new());
    }

    let decoded: Value =
        serde_json::from_str(payload).map_err(|error| format!("无法解析资源管理器菜单: {error}"))?;
    let rows = match decoded {
        Value::Array(items) => items,
        Value::Object(item) => vec![Value::Object(item)],
        _ => return Err("资源管理器菜单返回了无效数据。".to_string()),
    };

    let mut items = Vec::new();
    let mut previous_was_separator = true;
    for row in rows {
        let Value::Object(map) = row else {
            continue;
        };

        let raw_label = map
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let normalized_label = normalize_shell_menu_label(raw_label);
        if normalized_label.is_empty() {
            if !previous_was_separator {
                items.push(WindowsExplorerMenuItem {
                    label: String::new(),
                    verb_index: None,
                    is_separator: true,
                });
                previous_was_separator = true;
            }
            continue;
        }

        let Some(raw_index) = map.get("index").and_then(Value::as_u64) else {
            continue;
        };

        let verb_index = u32::try_from(raw_index)
            .map_err(|_| format!("无效的 Explorer 菜单索引: {raw_index}"))?;
        items.push(WindowsExplorerMenuItem {
            label: normalized_label,
            verb_index: Some(verb_index),
            is_separator: false,
        });
        previous_was_separator = false;
    }

    while matches!(items.last(), Some(item) if item.is_separator) {
        items.pop();
    }

    Ok(items)
}

#[cfg(target_os = "windows")]
fn normalize_shell_menu_label(raw_label: &str) -> String {
    let without_ampersand = raw_label.replace('&', "");
    let flattened = without_ampersand.replace('\r', " ").replace('\n', " ");
    let trimmed = if let Some((label, _)) = flattened.split_once('\t') {
        label.trim().to_string()
    } else {
        flattened.trim().to_string()
    };
    trimmed.split_whitespace().collect::<Vec<_>>().join(" ")
}
