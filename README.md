# GitHub Batch Manager

GitHub Batch Manager 是一个基于 Rust + Tauri 的桌面工具，用来集中管理多个本地 Git/GitHub 仓库。它不依赖 GitHub API，而是直接调用本机 `git` CLI，适合已经把仓库克隆到本地、需要批量维护的人。

旧版 Python + Tkinter 代码暂时保留在 `main.py` 和 `src/github_batch_manager/`，用于迁移期间对照行为；新的主实现位于 `src-tauri/` 和 `frontend/`。

## 当前功能

- 导入一个或多个仓库路径，或导入父目录并递归发现其中的 Git 仓库
- 自动保存仓库列表到本地 JSON
- 批量刷新仓库状态
- 批量执行 `pull`
- 批量执行 `commit`
- 批量执行 `push`
- 查看当前仓库的提交日志树
- 查看单个提交详情和文件变更统计
- 搜索仓库名称、分支、路径和状态
- 只看失败项

## 技术方案

- 桌面容器：Tauri v2
- 后端：Rust
- 前端：静态 HTML/CSS/JavaScript
- Git 集成：本地 `git` CLI
- 持久化：本地 JSON，沿用旧版路径
  - Windows: `%APPDATA%\GitHubBatchManager\repositories.json`
  - 其他系统: `~/.github-batch-manager/repositories.json`

## 目录结构

```text
frontend/
  index.html
  styles.css
  app.js
src-tauri/
  Cargo.toml
  tauri.conf.json
  src/
    commands.rs
    discovery.rs
    git_service.rs
    lib.rs
    main.rs
    models.rs
    store.rs
main.py                       # 旧版 Python 入口，迁移期保留
src/github_batch_manager/      # 旧版 Python 实现，迁移期保留
tests/                         # 旧版 Python 单元测试
```

## 环境要求

1. 安装 Rust toolchain，并确保 `cargo`、`rustc` 可用。
2. 安装 Tauri v2 所需系统依赖。Windows 需要 Microsoft C++ Build Tools 和 WebView2 Runtime。
3. 确认本机可执行 `git`：

```powershell
git --version
```

## 运行

当前前端没有 npm 构建步骤。安装 Rust 和 Tauri CLI 后可运行：

```powershell
cargo install tauri-cli --version "^2"
cd src-tauri
cargo tauri dev
```

也可以进入 Tauri 工程运行 Rust 测试：

```powershell
cd src-tauri
cargo test
```

## 自动化测试

Rust 后端功能测试：

```powershell
cmd.exe /s /c "call ""C:\Program Files\Microsoft Visual Studio\18\Enterprise\VC\Auxiliary\Build\vcvars64.bat"" >nul && cargo test"
```

前端语法检查：

```powershell
npm.cmd run test:frontend:syntax
```

界面操作自动化测试使用 Playwright。测试会在浏览器里加载 `frontend/index.html`，并 mock Tauri `invoke` 来覆盖导入、筛选、批量拉取、日志和提交详情流程：

```powershell
npm.cmd install
npm.cmd run test:ui
```

## 已知边界

- `commit` 会执行 `git add -A`，适合确认当前仓库全部变更都要提交的场景。
- 批量操作依次执行，当前没有取消队列和并发控制。
- 旧版 Windows Explorer 右键菜单联动尚未迁移到 Tauri。
- 本机未安装 Rust toolchain 时无法编译或运行 Tauri 应用。
