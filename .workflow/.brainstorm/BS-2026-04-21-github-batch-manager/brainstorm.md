# Brainstorm Session

**Session ID**: BS-2026-04-21-github-batch-manager
**Topic**: GitHub batch manager desktop MVP
**Started**: 2026-04-21T21:15:30+08:00
**Dimensions**: technical, ux, feasibility
**Mode**: Balanced

## Current Ideas
1. Build a desktop tool around the local git CLI so the app can batch-manage repositories without GitHub API auth.
2. Support two onboarding flows: scan a parent folder for repos and paste multiple explicit repo paths.
3. Keep the main workflow in one screen: repository grid on the left, operation toolbar on top, log tree panel on the right.

## Session Context
- Focus areas: repository import, batch operations, log visibility, offline-first implementation
- Perspectives: creative, pragmatic, systematic
- Constraints: standard library only, Windows-friendly desktop UX, testable core logic

## Exploration Vectors
1. How can the tool batch-manage repos without adding API/auth complexity?
2. What import flows make it easy to add many local GitHub folders at once?
3. How should batch operations report success, skip, and failure states per repository?
4. What is the lightest way to show a git log tree that still feels useful?
5. How do we keep the UI responsive while multiple git commands are running?

## Thought Evolution Timeline

### Round 1 - Exploration (2026-04-21T21:15:30+08:00)

#### Decision Log
> **Decision**: Prefer Python + Tkinter over WPF for the MVP.
> - **Context**: The repository is empty and offline testability matters.
> - **Options considered**: Python + Tkinter, C# + WPF, Electron.
> - **Chosen**: Python + Tkinter. **Reason**: built-in GUI and `unittest`, no dependency restore.
> - **Rejected**: WPF and Electron because both add heavier scaffolding and/or package restore risk.
> - **Impact**: We can spend time on product behavior instead of toolchain bootstrapping.

#### Ideas Generated
- Toolbar actions for `Refresh`, `Pull`, `Commit`, `Push`, `Select All`, `Clear Selection`.
- Recursive repository discovery from one or more roots.
- Right-hand detail panel with repository summary and git graph text viewer.

#### Narrative Synthesis
**Starting point**: A request for a batch GitHub repository manager.
**Key progress**: Reframed the product as a local repository operations tool instead of a GitHub API client.
**Decision impact**: The MVP can focus on reliable git workflows, local paths, and a useful operations dashboard.
**Current state**: Python + Tkinter is the strongest implementation path.
**Open directions**: Finalize task breakdown and start implementation.

## Synthesis & Conclusions
- Primary recommendation: build a local desktop app that orchestrates `git` commands across many repositories.
- UX recommendation: keep selection and batch actions visible at all times, and show the log tree for the currently highlighted repository.
- Technical recommendation: isolate git execution and parsing in services so the UI can remain thin and the behavior can be unit-tested.
