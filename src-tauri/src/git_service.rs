use crate::models::{
    GitChangedFile, GitCommitView, GitLogEntry, GitLogResult, OperationResult, RepositorySnapshot,
};
use std::collections::HashMap;
use std::path::Path;
use std::process::{Command, Stdio};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandResult {
    pub returncode: i32,
    pub stdout: String,
    pub stderr: String,
}

pub trait GitCommandRunner {
    fn run(&self, repository_path: &Path, args: &[&str]) -> CommandResult;
}

#[derive(Debug, Clone, Copy)]
pub struct SubprocessGitCommandRunner;

impl GitCommandRunner for SubprocessGitCommandRunner {
    fn run(&self, repository_path: &Path, args: &[&str]) -> CommandResult {
        match Command::new("git")
            .arg("-C")
            .arg(repository_path)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
        {
            Ok(output) => CommandResult {
                returncode: output.status.code().unwrap_or(1),
                stdout: String::from_utf8_lossy(&output.stdout).to_string(),
                stderr: String::from_utf8_lossy(&output.stderr).to_string(),
            },
            Err(error) => CommandResult {
                returncode: 1,
                stdout: String::new(),
                stderr: error.to_string(),
            },
        }
    }
}

pub struct GitRepositoryService<R: GitCommandRunner = SubprocessGitCommandRunner> {
    runner: R,
}

impl GitRepositoryService<SubprocessGitCommandRunner> {
    pub fn new() -> Self {
        Self {
            runner: SubprocessGitCommandRunner,
        }
    }
}

impl<R: GitCommandRunner> GitRepositoryService<R> {
    pub fn get_snapshot(&self, repository_path: &Path) -> RepositorySnapshot {
        let status_result = self
            .runner
            .run(repository_path, &["status", "--porcelain=v1", "--branch"]);
        if status_result.returncode != 0 {
            return RepositorySnapshot::empty(format_error(&status_result, "无法读取仓库状态"));
        }

        let mut snapshot = parse_status_output(&status_result.stdout);
        let log_result = self
            .runner
            .run(repository_path, &["log", "-1", "--pretty=%h%x1f%s%x1f%cr"]);
        if log_result.returncode == 0 && !log_result.stdout.trim().is_empty() {
            let (summary, age) = parse_last_commit_output(&log_result.stdout);
            snapshot.last_commit = summary;
            snapshot.last_commit_age = age;
        } else {
            snapshot.last_commit = "尚无提交".to_string();
            snapshot.last_commit_age = String::new();
        }

        snapshot
    }

    pub fn load_log_entries(&self, repository_path: &Path, limit: usize) -> GitLogResult {
        let limit_text = limit.to_string();
        let result = self.runner.run(
            repository_path,
            &[
                "log",
                "--graph",
                "--decorate=short",
                "--date=format:%Y-%m-%d %H:%M:%S",
                "--pretty=format:%x1f%H%x1f%h%x1f%ad%x1f%an%x1f%d%x1f%s",
                "--all",
                "-n",
                &limit_text,
            ],
        );
        if result.returncode != 0 {
            return GitLogResult {
                entries: Vec::new(),
                message: format_error(&result, "无法读取提交日志"),
            };
        }

        let entries = parse_log_entries_output(&result.stdout);
        if entries.is_empty() {
            return GitLogResult {
                entries,
                message: "当前仓库还没有可显示的提交记录。".to_string(),
            };
        }

        GitLogResult {
            entries,
            message: "日志树已更新".to_string(),
        }
    }

    pub fn load_commit_view(&self, repository_path: &Path, commit_hash: &str) -> GitCommitView {
        GitCommitView {
            detail_text: self.load_commit_details(repository_path, commit_hash),
            files: self.load_commit_files(repository_path, commit_hash),
        }
    }

    pub fn load_commit_details(&self, repository_path: &Path, commit_hash: &str) -> String {
        let result = self.runner.run(
            repository_path,
            &[
                "show",
                "--stat",
                "--decorate=short",
                "--date=format:%Y-%m-%d %H:%M:%S",
                "--format=commit %H%nAuthor: %an%nDate:   %ad%nRefs:   %d%n%n%s%n%n%b",
                "-n",
                "1",
                commit_hash,
            ],
        );
        if result.returncode != 0 {
            return format_error(&result, "无法读取提交详情");
        }

        let detail_text = result.stdout.trim();
        if detail_text.is_empty() {
            format!("commit {commit_hash}\n\n(没有更多提交详情)")
        } else {
            detail_text.to_string()
        }
    }

    pub fn load_commit_files(
        &self,
        repository_path: &Path,
        commit_hash: &str,
    ) -> Vec<GitChangedFile> {
        let status_result = self.runner.run(
            repository_path,
            &["show", "--name-status", "--format=", "-n", "1", commit_hash],
        );
        let numstat_result = self.runner.run(
            repository_path,
            &["show", "--numstat", "--format=", "-n", "1", commit_hash],
        );

        let status_items = if status_result.returncode == 0 {
            parse_name_status_output(&status_result.stdout)
        } else {
            Vec::new()
        };
        let numstat_items = if numstat_result.returncode == 0 {
            parse_numstat_output(&numstat_result.stdout)
        } else {
            Vec::new()
        };

        let status_map = status_items
            .iter()
            .cloned()
            .collect::<HashMap<String, String>>();
        let numstat_map = numstat_items
            .iter()
            .map(|(path, additions, deletions)| {
                (path.clone(), (additions.clone(), deletions.clone()))
            })
            .collect::<HashMap<String, (String, String)>>();

        let mut ordered_paths = Vec::new();
        for (path, _) in &status_items {
            push_unique(&mut ordered_paths, path);
        }
        for (path, _, _) in &numstat_items {
            push_unique(&mut ordered_paths, path);
        }

        ordered_paths
            .into_iter()
            .map(|path| {
                let (additions, deletions) = numstat_map
                    .get(&path)
                    .cloned()
                    .unwrap_or_else(|| ("0".to_string(), "0".to_string()));
                GitChangedFile {
                    status: status_map
                        .get(&path)
                        .cloned()
                        .unwrap_or_else(|| "修改".to_string()),
                    path,
                    additions,
                    deletions,
                }
            })
            .collect()
    }

    pub fn pull(
        &self,
        repository_path: &Path,
        repository_name: &str,
        strategy: &str,
    ) -> OperationResult {
        let args = build_pull_args(strategy);
        let arg_refs = args.iter().map(String::as_str).collect::<Vec<_>>();
        let result = self.runner.run(repository_path, &arg_refs);
        if result.returncode != 0 {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "pull".to_string(),
                status: "failed".to_string(),
                message: format_error(&result, "拉取失败"),
            };
        }

        OperationResult {
            repository_path: repository_path.to_string_lossy().to_string(),
            repository_name: repository_name.to_string(),
            action: "pull".to_string(),
            status: "success".to_string(),
            message: result.stdout.trim().to_string().or_default("拉取完成"),
        }
    }

    pub fn commit_all(
        &self,
        repository_path: &Path,
        repository_name: &str,
        message: &str,
    ) -> OperationResult {
        if message.trim().is_empty() {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "commit".to_string(),
                status: "failed".to_string(),
                message: "提交说明不能为空。".to_string(),
            };
        }

        let status_result = self.runner.run(repository_path, &["status", "--short"]);
        if status_result.returncode != 0 {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "commit".to_string(),
                status: "failed".to_string(),
                message: format_error(&status_result, "无法检查变更"),
            };
        }

        if status_result.stdout.trim().is_empty() {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "commit".to_string(),
                status: "skipped".to_string(),
                message: "没有可提交的变更，已跳过。".to_string(),
            };
        }

        let add_result = self.runner.run(repository_path, &["add", "-A"]);
        if add_result.returncode != 0 {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "commit".to_string(),
                status: "failed".to_string(),
                message: format_error(&add_result, "暂存失败"),
            };
        }

        let commit_result = self.runner.run(repository_path, &["commit", "-m", message]);
        if commit_result.returncode != 0 {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "commit".to_string(),
                status: "failed".to_string(),
                message: format_error(&commit_result, "提交失败"),
            };
        }

        OperationResult {
            repository_path: repository_path.to_string_lossy().to_string(),
            repository_name: repository_name.to_string(),
            action: "commit".to_string(),
            status: "success".to_string(),
            message: commit_result
                .stdout
                .trim()
                .to_string()
                .or_default("提交完成"),
        }
    }

    pub fn push(&self, repository_path: &Path, repository_name: &str) -> OperationResult {
        let result = self.runner.run(repository_path, &["push"]);
        if result.returncode != 0 {
            return OperationResult {
                repository_path: repository_path.to_string_lossy().to_string(),
                repository_name: repository_name.to_string(),
                action: "push".to_string(),
                status: "failed".to_string(),
                message: format_error(&result, "推送失败"),
            };
        }

        OperationResult {
            repository_path: repository_path.to_string_lossy().to_string(),
            repository_name: repository_name.to_string(),
            action: "push".to_string(),
            status: "success".to_string(),
            message: result.stdout.trim().to_string().or_default("推送完成"),
        }
    }
}

trait StringFallback {
    fn or_default(self, fallback: &str) -> String;
}

impl StringFallback for String {
    fn or_default(self, fallback: &str) -> String {
        if self.is_empty() {
            fallback.to_string()
        } else {
            self
        }
    }
}

fn push_unique(items: &mut Vec<String>, item: &str) {
    if !items.iter().any(|existing| existing == item) {
        items.push(item.to_string());
    }
}

fn format_error(result: &CommandResult, prefix: &str) -> String {
    let stderr = result.stderr.trim();
    let stdout = result.stdout.trim();
    let details = if !stderr.is_empty() {
        stderr
    } else if !stdout.is_empty() {
        stdout
    } else {
        "未知 git 错误"
    };
    format!("{prefix}: {details}")
}

pub fn parse_status_output(output: &str) -> RepositorySnapshot {
    let lines = output
        .lines()
        .map(str::trim_end)
        .filter(|line| !line.trim().is_empty())
        .collect::<Vec<_>>();
    if lines.is_empty() {
        return RepositorySnapshot::empty("仓库为空。");
    }

    let headline = lines[0].strip_prefix("## ").unwrap_or(lines[0]).to_string();
    let branch: String;
    let mut ahead = 0;
    let mut behind = 0;

    if let Some(rest) = headline.strip_prefix("No commits yet on ") {
        branch = rest.trim().to_string();
    } else if let Some(rest) = headline.strip_prefix("Initial commit on ") {
        branch = rest.trim().to_string();
    } else {
        let (branch_section, tracking_section) = headline
            .split_once("...")
            .map_or((headline.as_str(), ""), |(left, right)| (left, right));
        branch = branch_section.trim().to_string();
        if !tracking_section.is_empty() {
            if let (Some(start), Some(end)) =
                (tracking_section.find('['), tracking_section.find(']'))
            {
                if start < end {
                    for piece in tracking_section[start + 1..end].split(',') {
                        let item = piece.trim();
                        if let Some(value) = item.strip_prefix("ahead ") {
                            ahead = value.trim().parse().unwrap_or(0);
                        } else if let Some(value) = item.strip_prefix("behind ") {
                            behind = value.trim().parse().unwrap_or(0);
                        }
                    }
                }
            }
        }
    }

    RepositorySnapshot {
        branch,
        dirty: lines.iter().skip(1).any(|line| !line.trim().is_empty()),
        ahead,
        behind,
        last_commit: String::new(),
        last_commit_age: String::new(),
        status_message: "状态已刷新".to_string(),
    }
}

pub fn parse_last_commit_output(output: &str) -> (String, String) {
    let parts = output.trim().split('\x1f').collect::<Vec<_>>();
    if parts.len() < 3 {
        return (output.trim().to_string(), String::new());
    }

    let summary = parts[1].trim().to_string();
    (summary, parts[2].trim().to_string())
}

pub fn parse_log_entries_output(output: &str) -> Vec<GitLogEntry> {
    let mut entries = Vec::new();
    let mut connector_lines_before = Vec::new();

    for raw_line in output.lines() {
        if let Some((graph_prefix, payload)) = raw_line.split_once('\x1f') {
            let parts = payload.split('\x1f').collect::<Vec<_>>();
            if parts.len() < 6 {
                continue;
            }

            let refs_raw = parts[4];
            let refs = normalize_refs_display(refs_raw);
            let (current_ref, remote_refs, tag_refs) = split_ref_groups(refs_raw);
            entries.push(GitLogEntry {
                graph: graph_prefix.trim_end().to_string(),
                connector_lines_before: std::mem::take(&mut connector_lines_before),
                commit_hash: parts[0].trim().to_string(),
                short_hash: parts[1].trim().to_string(),
                date: parts[2].trim().to_string(),
                author: parts[3].trim().to_string(),
                refs,
                subject: parts[5].trim().to_string(),
                current_ref,
                remote_refs: remote_refs.clone(),
                tag_refs,
                is_head: refs_raw.contains("HEAD ->"),
                has_tag: refs_raw.contains("tag:"),
                has_remote_ref: !remote_refs.is_empty(),
            });
            continue;
        }

        let connector = raw_line.trim_end();
        if !connector.is_empty() {
            connector_lines_before.push(connector.to_string());
        }
    }

    entries
}

pub fn normalize_refs_display(refs_raw: &str) -> String {
    let refs = trim_ref_wrappers(refs_raw);
    if refs.is_empty() {
        return String::new();
    }

    refs.split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .map(|part| {
            part.strip_prefix("tag: ")
                .unwrap_or(part)
                .trim()
                .to_string()
        })
        .collect::<Vec<_>>()
        .join(", ")
}

pub fn split_ref_groups(refs_raw: &str) -> (String, String, String) {
    let refs = trim_ref_wrappers(refs_raw);
    if refs.is_empty() {
        return (String::new(), String::new(), String::new());
    }

    let mut current_parts = Vec::new();
    let mut remote_parts = Vec::new();
    let mut tag_parts = Vec::new();
    let mut other_parts = Vec::new();

    for part in refs
        .split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
    {
        if part.starts_with("HEAD ->") {
            current_parts.push(part.to_string());
        } else if let Some(tag) = part.strip_prefix("tag: ") {
            tag_parts.push(tag.trim().to_string());
        } else if part.contains('/') {
            remote_parts.push(part.to_string());
        } else {
            other_parts.push(part.to_string());
        }
    }

    current_parts.extend(other_parts);
    (
        current_parts.join(", "),
        remote_parts.join(", "),
        tag_parts.join(", "),
    )
}

fn trim_ref_wrappers(refs_raw: &str) -> &str {
    let refs = refs_raw.trim();
    refs.strip_prefix('(')
        .and_then(|inner| inner.strip_suffix(')'))
        .unwrap_or(refs)
        .trim()
}

pub fn parse_name_status_output(output: &str) -> Vec<(String, String)> {
    output
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(|line| {
            let parts = line.split('\t').collect::<Vec<_>>();
            let status_code = parts
                .first()
                .and_then(|part| part.chars().next())
                .unwrap_or('M');
            (
                normalize_name_status_path(&parts),
                map_status_code(status_code),
            )
        })
        .collect()
}

fn normalize_name_status_path(parts: &[&str]) -> String {
    if parts.len() >= 3 {
        let code = parts[0].chars().next().unwrap_or('M');
        if matches!(code, 'R' | 'C') {
            return format!("{} -> {}", parts[1], parts[2]);
        }
    }

    if parts.len() >= 2 {
        parts[1].to_string()
    } else {
        parts.first().copied().unwrap_or_default().to_string()
    }
}

pub fn parse_numstat_output(output: &str) -> Vec<(String, String, String)> {
    output
        .lines()
        .map(str::trim_end)
        .filter(|line| !line.is_empty())
        .filter_map(|line| {
            let parts = line.split('\t').collect::<Vec<_>>();
            if parts.len() < 3 {
                return None;
            }
            Some((
                normalize_numstat_path(parts[2]),
                parts[0].to_string(),
                parts[1].to_string(),
            ))
        })
        .collect()
}

fn normalize_numstat_path(raw_path: &str) -> String {
    if let (Some(start), Some(end)) = (raw_path.find('{'), raw_path.rfind('}')) {
        if start < end {
            let prefix = &raw_path[..start];
            let inner = &raw_path[start + 1..end];
            if let Some((from, to)) = inner.split_once(" => ") {
                return format!("{prefix}{from} -> {prefix}{to}");
            }
        }
    }

    if let Some((from, to)) = raw_path.split_once(" => ") {
        return format!("{from} -> {to}");
    }

    raw_path.to_string()
}

pub fn map_status_code(status_code: char) -> String {
    match status_code {
        'A' => "新增",
        'M' => "修改",
        'D' => "删除",
        'R' => "重命名",
        'C' => "复制",
        'T' => "类型变更",
        'U' => "冲突",
        _ => "修改",
    }
    .to_string()
}

pub fn build_pull_args(strategy: &str) -> Vec<String> {
    match strategy {
        "ff_only" => vec!["pull".to_string(), "--ff-only".to_string()],
        "rebase" => vec!["pull".to_string(), "--rebase".to_string()],
        _ => vec!["pull".to_string(), "--no-rebase".to_string()],
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::VecDeque;

    #[test]
    fn parse_status_output_supports_porcelain_branch_metadata() {
        let snapshot = parse_status_output(
            "## main...origin/main [ahead 2, behind 1]\n M src/main.rs\n?? notes.txt\n",
        );

        assert_eq!(snapshot.branch, "main");
        assert!(snapshot.dirty);
        assert_eq!(snapshot.ahead, 2);
        assert_eq!(snapshot.behind, 1);
    }

    #[test]
    fn parse_numstat_output_normalizes_rename_paths() {
        let parsed = parse_numstat_output("1\t0\ta.txt => b.txt\n");

        assert_eq!(
            parsed,
            vec![("a.txt -> b.txt".to_string(), "1".to_string(), "0".to_string())]
        );
    }

    #[test]
    fn parse_numstat_output_normalizes_brace_rename_paths() {
        let parsed = parse_numstat_output("1\t0\tsrc/{old.ts => new.ts}\n");

        assert_eq!(
            parsed,
            vec![(
                "src/old.ts -> src/new.ts".to_string(),
                "1".to_string(),
                "0".to_string()
            )]
        );
    }

    #[test]
    fn get_snapshot_uses_porcelain_status_command() {
        struct RecordingRunner {
            calls: RefCell<Vec<Vec<String>>>,
            responses: RefCell<VecDeque<CommandResult>>,
        }

        impl GitCommandRunner for RecordingRunner {
            fn run(&self, _repository_path: &Path, args: &[&str]) -> CommandResult {
                self.calls
                    .borrow_mut()
                    .push(args.iter().map(|item| (*item).to_string()).collect());
                self.responses
                    .borrow_mut()
                    .pop_front()
                    .expect("recorded response")
            }
        }

        let runner = RecordingRunner {
            calls: RefCell::new(Vec::new()),
            responses: RefCell::new(VecDeque::from([
                CommandResult {
                    returncode: 0,
                    stdout: "## main\n".to_string(),
                    stderr: String::new(),
                },
                CommandResult {
                    returncode: 0,
                    stdout: String::new(),
                    stderr: String::new(),
                },
            ])),
        };
        let service = GitRepositoryService { runner };

        let _snapshot = service.get_snapshot(Path::new("C:/repo"));

        let calls = service.runner.calls.borrow();
        assert_eq!(
            calls.first(),
            Some(&vec![
                "status".to_string(),
                "--porcelain=v1".to_string(),
                "--branch".to_string()
            ])
        );
    }
}
