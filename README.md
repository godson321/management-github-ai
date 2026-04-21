# GitHub 批量仓库管理工具

这是一个基于 Python 3.13 + Tkinter 的桌面 MVP，用来集中管理多个本地 GitHub 仓库。它不依赖 GitHub API，而是直接调用本机 `git` 命令，因此更适合已经把仓库克隆到本地、想统一做批量维护的人。

## 当前功能

- 扫描一个根目录，自动发现其中的多个 Git 仓库
- 批量导入多个明确路径
- 在仓库列表中勾选多个项目
- 批量刷新仓库状态
- 批量执行 `pull`
- 批量执行 `commit`
- 批量执行 `push`
- 查看当前选中仓库的提交日志树
- 自动保存已跟踪的仓库列表

## 技术方案

- GUI：Tkinter
- Git 集成：本地 `git` CLI
- 持久化：本地 JSON
- 测试：Python `unittest`

## 目录结构

```text
main.py
src/github_batch_manager/
  __init__.py
  __main__.py
  discovery.py
  git_service.py
  models.py
  store.py
  ui.py
tests/
  test_discovery.py
  test_git_service.py
  test_store.py
```

## 运行方式

请先确认本机可直接执行 `git`：

```powershell
git --version
```

启动应用：

```powershell
python main.py
```

## 使用说明

1. 点击“扫描目录”选择一个父目录，程序会递归查找其中的 Git 仓库。
2. 或点击“导入路径”，每行输入一个路径，支持仓库目录或包含多个仓库的父目录。
3. 在列表第一列点击 `[x] / [ ]` 来勾选需要批量操作的仓库。
4. 使用“刷新状态 / 批量拉取 / 批量提交 / 批量推送”执行批量操作。
5. 点击某个仓库行后，右侧会显示仓库详情和提交日志树。

## 测试

运行测试：

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

## 已知边界

- 当前是桌面 MVP，重点在批量本地仓库管理，还没有 GitHub 账号授权、Issue、PR 等云端能力。
- `commit` 操作会执行 `git add -A`，适合“我确认当前仓库全部变更都要提交”的场景。
- 日志树使用 `git log --graph --decorate --oneline --all` 的文本图展示，优先保证可读性和实现稳定性。
