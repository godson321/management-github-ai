import { expect, test } from "@playwright/test";

const baseRepositories = [
  {
    path: "\\\\?\\G:\\Repos\\alpha",
    selected: true,
    name: "alpha",
    branch: "main",
    dirty: false,
    ahead: 0,
    behind: 0,
    lastCommit: "alpha init",
    lastCommitAge: "2 hours ago",
    statusMessage: "状态已刷新",
    lastOperationStatus: "idle",
    lastErrorMessage: "",
    logEntries: [],
    logMessage: "尚未加载日志。",
    selectedCommitHash: "",
    commitDetailText: "",
    commitChangedFiles: [],
  },
  {
    path: "\\\\?\\G:\\Repos\\beta",
    selected: false,
    name: "beta",
    branch: "feature",
    dirty: true,
    ahead: 2,
    behind: 1,
    lastCommit: "beta change",
    lastCommitAge: "5 minutes ago",
    statusMessage: "pull失败: conflict",
    lastOperationStatus: "failed",
    lastErrorMessage: "conflict",
    logEntries: [],
    logMessage: "尚未加载日志。",
    selectedCommitHash: "",
    commitDetailText: "",
    commitChangedFiles: [],
  },
];

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function repoTable(page) {
  return page.locator("#repoTable");
}

function repoBody(page) {
  return repoTable(page).locator(".vxe-table--body-wrapper.body--wrapper").first();
}

function repoHeader(page) {
  return repoTable(page).locator(".vxe-table--header-wrapper").first();
}

function repoHeaderColumn(page, title: string) {
  return repoHeader(page).locator("th.vxe-header--column", { hasText: title }).first();
}

function repoSelectionHeader(page) {
  return repoHeader(page).locator("th.vxe-header--column").first();
}

async function repositoryColumnTitles(page) {
  return repoHeader(page).locator("th.vxe-header--column").evaluateAll((cells) =>
    cells.map((cell) => cell.textContent?.trim() ?? "").filter(Boolean),
  );
}

async function openApp(page, options = {}) {
  const repositories = clone((options as { repositories?: typeof baseRepositories }).repositories ?? baseRepositories);
  const uiState = clone(
    (options as { uiState?: Record<string, unknown> }).uiState ?? {
      repositoryColumns: [
        "selected",
        "name",
        "path",
        "branch",
        "dirty",
        "ahead",
        "behind",
        "lastCommit",
        "lastOperationStatus",
        "statusMessage",
      ],
      hiddenRepositoryColumns: [],
      repositoryColumnWidths: {},
    },
  );
  const consoleErrors: string[] = [];

  await page.addInitScript(({ initialRepositories, initialUiState }) => {
    const cloneInPage = (value: unknown) => JSON.parse(JSON.stringify(value));
    const listeners = new Map<string, Array<(event: { event: string; payload: unknown }) => void>>();

    window.__GBM_TEST_STATE__ = {
      repositories: cloneInPage(initialRepositories),
      uiState: cloneInPage(initialUiState),
      calls: [],
      dialogSelections: ["G:\\Repos"],
      listeners,
    };

    function emit(event: string, payload: unknown) {
      for (const handler of listeners.get(event) ?? []) {
        handler({ event, payload });
      }
    }

    window.__TAURI__ = {
      core: {
        invoke: async (command: string, args: Record<string, unknown> = {}) => {
          window.__GBM_TEST_STATE__.calls.push({ command, args: cloneInPage(args) });
          const state = window.__GBM_TEST_STATE__;

          if (command === "load_app_state") {
            return { repositories: cloneInPage(state.repositories), uiState: cloneInPage(state.uiState) };
          }

          if (command === "save_repositories") {
            state.repositories = cloneInPage(args.repositories);
            state.uiState = cloneInPage(args.uiState);
            return null;
          }

          if (command === "discover_repositories") {
            return [
              {
                path: "G:\\Repos\\gamma",
                selected: true,
                name: "gamma",
                branch: "",
                dirty: false,
                ahead: 0,
                behind: 0,
                lastCommit: "",
                lastCommitAge: "",
                statusMessage: "未刷新",
                lastOperationStatus: "idle",
                lastErrorMessage: "",
                logEntries: [],
                logMessage: "请选择一个仓库以查看日志树。",
                selectedCommitHash: "",
                commitDetailText: "",
                commitChangedFiles: [],
              },
            ];
          }

          if (command === "refresh_repositories") {
            return (args.repositories as Array<Record<string, unknown>>).map((repository) => ({
              ...repository,
              branch: repository.branch || "main",
              dirty: false,
              ahead: 0,
              behind: 0,
              lastCommit: "refreshed",
              lastCommitAge: "just now",
              statusMessage: "状态已刷新",
              lastOperationStatus: "idle",
              lastErrorMessage: "",
            }));
          }

          if (command === "pull_repositories") {
            const results = (args.repositories as Array<Record<string, unknown>>).map((repository, index, all) => {
              emit("batch-progress", {
                phase: "started",
                action: "pull",
                index: index + 1,
                total: all.length,
                repositoryPath: repository.path,
                repositoryName: repository.name,
              });

              const nextRepository = {
                ...repository,
                statusMessage: "pull成功: Already up to date.",
                lastOperationStatus: "success",
                lastErrorMessage: "",
              };
              const result = {
                repositoryPath: repository.path,
                repositoryName: repository.name,
                action: "pull",
                status: "success",
                message: "Already up to date.",
              };
              emit("batch-progress", {
                phase: "finished",
                action: "pull",
                index: index + 1,
                total: all.length,
                repositoryPath: repository.path,
                repositoryName: repository.name,
                repository: nextRepository,
                result,
              });
              return { repository: nextRepository, result };
            });
            return results;
          }

          if (command === "load_log_entries") {
            return {
              message: "日志树已更新",
              entries: [
                {
                  graph: "*",
                  connectorLinesBefore: [],
                  commitHash: "abc123456789",
                  shortHash: "abc1234",
                  date: "2026-04-29 22:00:00",
                  author: "tester",
                  refs: "HEAD -> main",
                  subject: "feat: add tauri ui",
                  currentRef: "HEAD -> main",
                  remoteRefs: "origin/main",
                  tagRefs: "",
                  isHead: true,
                  hasTag: false,
                  hasRemoteRef: true,
                },
                {
                  graph: "| *",
                  connectorLinesBefore: ["|\\"],
                  commitHash: "def123456789",
                  shortHash: "def1234",
                  date: "2026-04-29 21:00:00",
                  author: "tester",
                  refs: "",
                  subject: "merge branch",
                  currentRef: "",
                  remoteRefs: "",
                  tagRefs: "",
                  isHead: false,
                  hasTag: false,
                  hasRemoteRef: false,
                },
                {
                  graph: "* |",
                  connectorLinesBefore: [],
                  commitHash: "ghi123456789",
                  shortHash: "ghi1234",
                  date: "2026-04-29 20:00:00",
                  author: "tester",
                  refs: "",
                  subject: "chore: add issue template",
                  currentRef: "",
                  remoteRefs: "",
                  tagRefs: "",
                  isHead: false,
                  hasTag: false,
                  hasRemoteRef: false,
                },
                {
                  graph: "*",
                  connectorLinesBefore: ["|/"],
                  commitHash: "jkl123456789",
                  shortHash: "jkl1234",
                  date: "2026-04-29 19:00:00",
                  author: "tester",
                  refs: "",
                  subject: "refactor: tidy commands",
                  currentRef: "",
                  remoteRefs: "",
                  tagRefs: "",
                  isHead: false,
                  hasTag: false,
                  hasRemoteRef: false,
                },
              ],
            };
          }

          if (command === "load_commit_view") {
            return {
              detailText: `commit ${args.commitHash}\n\nfeat: add tauri ui`,
              files: [
                {
                  path: "frontend/src/App.vue",
                  status: "修改",
                  additions: "42",
                  deletions: "3",
                },
              ],
            };
          }

          throw new Error(`Unexpected command: ${command}`);
        },
      },
      event: {
        listen: async (event: string, handler: (payload: { event: string; payload: unknown }) => void) => {
          const handlers = listeners.get(event) ?? [];
          handlers.push(handler);
          listeners.set(event, handlers);
          return () => {
            const nextHandlers = (listeners.get(event) ?? []).filter((item) => item !== handler);
            listeners.set(event, nextHandlers);
          };
        },
      },
      dialog: {
        open: async (options: Record<string, unknown>) => {
          window.__GBM_TEST_STATE__.calls.push({ command: "dialog.open", args: cloneInPage(options) });
          return cloneInPage(window.__GBM_TEST_STATE__.dialogSelections);
        },
      },
    };
  }, { initialRepositories: repositories, initialUiState: uiState });

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  await page.goto("/");
  await expect(page.getByText("准备就绪")).toBeVisible();
  return {
    getCalls: () => page.evaluate(() => window.__GBM_TEST_STATE__.calls),
    consoleErrors,
  };
}

test("加载保存的仓库并筛选失败项", async ({ page }) => {
  await openApp(page);

  await expect(repoBody(page).getByText("alpha", { exact: true })).toBeVisible();
  await expect(repoBody(page).getByText("beta", { exact: true })).toBeVisible();
  await expect(repoHeader(page).getByText("文件夹路径", { exact: true })).toBeVisible();
  await expect(repoBody(page).getByText("G:\\Repos\\alpha", { exact: true })).toBeVisible();
  await expect(repoTable(page).getByText("\\\\?\\")).toHaveCount(0);
  await expect(page.getByText("2 个仓库，当前显示 2 个，已选择 1 个")).toBeVisible();

  await page.getByText("只看失败项").click();

  await expect(repoBody(page).getByText("alpha", { exact: true })).toHaveCount(0);
  await expect(repoBody(page).getByText("beta", { exact: true })).toBeVisible();
});

test("列设置可以隐藏列并保存表格状态", async ({ page }) => {
  const harness = await openApp(page);

  await expect(repoHeader(page).getByText("分支", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "列设置" }).click();
  await page.locator(".el-drawer").getByText("分支", { exact: true }).click();

  await expect(repoHeader(page).getByText("分支", { exact: true })).toHaveCount(0);

  const saveCalls = (await harness.getCalls()).filter(
    (call: { command: string }) => call.command === "save_repositories",
  );
  expect(saveCalls.at(-1).args.uiState.hiddenRepositoryColumns).toContain("branch");
});

test("主表格表头可以拖拽调整列顺序并保存", async ({ page }) => {
  const harness = await openApp(page);
  const branchHeader = repoHeaderColumn(page, "分支");
  const nameHeader = repoHeaderColumn(page, "仓库");
  await expect.poll(() => repositoryColumnTitles(page)).toEqual([
    "仓库",
    "文件夹路径",
    "分支",
    "改动",
    "领先",
    "落后",
    "最新提交",
    "结果",
    "状态",
  ]);
  const branchDragHandle = branchHeader.locator(".vxe-cell--drag-handle").first();
  await expect(branchDragHandle).toBeVisible();
  await expect(branchDragHandle).not.toHaveClass(/is--disabled/);
  const branchHandleBox = await branchDragHandle.boundingBox();
  const nameBox = await nameHeader.boundingBox();

  expect(branchHandleBox).not.toBeNull();
  expect(nameBox).not.toBeNull();

  const branchDragStartX = branchHandleBox!.x + branchHandleBox!.width / 2;
  const branchDragStartY = branchHandleBox!.y + branchHandleBox!.height / 2;
  await page.mouse.move(branchDragStartX, branchDragStartY);
  await page.mouse.down();
  await page.mouse.move(branchDragStartX + 12, branchDragStartY, { steps: 4 });
  await page.mouse.move(nameBox!.x + 4, nameBox!.y + nameBox!.height / 2, { steps: 12 });
  await expect(repoTable(page).locator(".vxe-table--drag-sort-tip")).toHaveAttribute("drag-status", "normal");
  await page.mouse.up();

  await expect.poll(() => repositoryColumnTitles(page)).toEqual([
    "分支",
    "仓库",
    "文件夹路径",
    "改动",
    "领先",
    "落后",
    "最新提交",
    "结果",
    "状态",
  ]);

  const saveCalls = (await harness.getCalls()).filter(
    (call: { command: string }) => call.command === "save_repositories",
  );
  expect(saveCalls.at(-1).args.uiState.repositoryColumns.slice(0, 2)).toEqual(["branch", "name"]);
});

test("selection column header does not show drag handle", async ({ page }) => {
  await openApp(page);

  await expect(repoSelectionHeader(page).locator(".vxe-cell--drag-handle")).toHaveCount(0);

  const branchDragHandle = repoHeader(page).locator("th.vxe-header--column").nth(3).locator(".vxe-cell--drag-handle").first();
  await expect(branchDragHandle).toBeVisible();
  await expect(branchDragHandle).not.toHaveClass(/is--disabled/);
});

for (const direction of [
  { name: "向上", offsetY: -80 },
  { name: "向下", offsetY: 80 },
] as const) {
  test(`主表格表头${direction.name}拖出释放时隐藏该列`, async ({ page }) => {
    const harness = await openApp(page);
    const branchHeader = repoHeaderColumn(page, "分支");
    const branchDragHandle = branchHeader.locator(".vxe-cell--drag-handle").first();
    await expect(branchDragHandle).toBeVisible();

    const branchHandleBox = await branchDragHandle.boundingBox();
    expect(branchHandleBox).not.toBeNull();

    const startX = branchHandleBox!.x + branchHandleBox!.width / 2;
    const startY = branchHandleBox!.y + branchHandleBox!.height / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 4, startY + direction.offsetY, { steps: 8 });
    await page.mouse.up();

    await expect(repoHeader(page).getByText("分支", { exact: true })).toHaveCount(0);

    const saveCalls = (await harness.getCalls()).filter(
      (call: { command: string }) => call.command === "save_repositories",
    );
    expect(saveCalls.at(-1).args.uiState.hiddenRepositoryColumns).toContain("branch");
  });
}

test("重复的历史列状态会被去重", async ({ page }) => {
  const harness = await openApp(page, {
    uiState: {
      repositoryColumns: [
        "name",
        "branch",
        "name",
        "dirty",
        "branch",
        "ahead",
        "behind",
        "lastCommit",
        "lastOperationStatus",
        "statusMessage",
      ],
      hiddenRepositoryColumns: [],
      repositoryColumnWidths: {},
    },
  });

  await expect.poll(() => repositoryColumnTitles(page)).toEqual([
    "仓库",
    "文件夹路径",
    "分支",
    "改动",
    "领先",
    "落后",
    "最新提交",
    "结果",
    "状态",
  ]);

  await page.getByRole("button", { name: "列设置" }).click();
  await page.locator(".el-drawer").getByText("分支", { exact: true }).click();

  const saveCalls = (await harness.getCalls()).filter(
    (call: { command: string }) => call.command === "save_repositories",
  );
  expect(saveCalls.at(-1).args.uiState.repositoryColumns).toEqual([
    "name",
    "path",
    "branch",
    "dirty",
    "ahead",
    "behind",
    "lastCommit",
    "lastOperationStatus",
    "statusMessage",
  ]);
});

test("导入路径后刷新发现的仓库并保存状态", async ({ page }) => {
  const harness = await openApp(page, { repositories: [] });

  await page.getByRole("button", { name: "导入路径" }).click();
  await expect(page.getByRole("dialog", { name: "导入路径" })).toHaveCount(0);

  await expect(repoBody(page).getByText("gamma", { exact: true })).toBeVisible();
  await expect(repoBody(page).getByText("refreshed")).toBeVisible();
  await expect(page.getByText("导入 1 个仓库。")).toBeVisible();

  const calls = await harness.getCalls();
  const commands = calls.map((call: { command: string }) => call.command);
  const dialogCall = calls.find((call: { command: string }) => call.command === "dialog.open");
  expect(commands).toContain("discover_repositories");
  expect(commands).toContain("refresh_repositories");
  expect(commands).toContain("save_repositories");
  expect(dialogCall.args).toMatchObject({ directory: true, multiple: true });
  const discoverCall = calls.find((call: { command: string }) => call.command === "discover_repositories");
  expect(discoverCall.args.paths).toEqual(["G:\\Repos"]);
});

test("粘贴路径窗口打开后主表格仍然保持渲染", async ({ page }) => {
  await openApp(page);

  await expect(repoBody(page).getByText("alpha", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "粘贴路径" }).click();

  await expect(page.getByRole("dialog", { name: "导入路径" })).toBeVisible();
  await expect(repoHeader(page).getByText("仓库", { exact: true })).toBeVisible();
  await expect(repoBody(page).getByText("alpha", { exact: true })).toBeVisible();
});

test("批量拉取写入逐项进度日志", async ({ page }) => {
  const harness = await openApp(page);

  await page.getByRole("button", { name: "批量拉取" }).hover();
  await page.getByRole("button", { name: "合并拉取" }).click();

  await expect(page.getByText("[pull] 正在处理 alpha (1/1)...")).toBeVisible();
  await expect(page.getByText("[pull] alpha - 成功：Already up to date.")).toBeVisible();
  await expect(repoBody(page).getByText("pull成功: Already up to date.")).toBeVisible();

  const pullCall = (await harness.getCalls()).find(
    (call: { command: string }) => call.command === "pull_repositories",
  );
  expect(pullCall.args.strategy).toBe("merge");
  expect(pullCall.args.repositories).toHaveLength(1);
  expect(pullCall.args.repositories[0].name).toBe("alpha");
});

test("表头复选框可以全选和全取消当前表格仓库", async ({ page }) => {
  const harness = await openApp(page);
  const headerCheckbox = repoTable(page).locator(".vxe-table--header-wrapper .vxe-checkbox--icon").first();

  await expect(page.getByText("2 个仓库，当前显示 2 个，已选择 1 个")).toBeVisible();

  await headerCheckbox.click();
  await expect(page.getByText("2 个仓库，当前显示 2 个，已选择 2 个")).toBeVisible();

  await headerCheckbox.click();
  await expect(page.getByText("2 个仓库，当前显示 2 个，已选择 0 个")).toBeVisible();

  const saveCalls = (await harness.getCalls()).filter(
    (call: { command: string }) => call.command === "save_repositories",
  );
  expect(saveCalls.at(-1).args.repositories.every((repository: { selected: boolean }) => !repository.selected)).toBe(true);
});

test("从详情页加载日志和提交详情", async ({ page }) => {
  await openApp(page);

  await page.getByRole("tab", { name: "日志树" }).click();
  await page.getByRole("button", { name: "加载日志" }).click();

  await expect(page.getByText("feat: add tauri ui").first()).toBeVisible();
  await expect(page.getByText("merge branch")).toBeVisible();
  await expect(page.getByText("chore: add issue template")).toBeVisible();
  await expect(page.locator("#logRows .log-graph-layer .log-graph-svg")).toHaveCount(1);
  await expect(page.locator("#logRows .log-row .log-graph-svg")).toHaveCount(0);
  await expect.poll(() => page.locator("#logRows .log-graph-svg line").count()).toBeGreaterThan(0);
  await expect.poll(() => page.locator("#logRows .log-graph-svg circle").count()).toBeGreaterThan(0);
  await expect
    .poll(() =>
      page.locator("#logRows .log-graph-svg line").evaluateAll((lines) =>
        lines.filter((line) => line.getAttribute("x1") !== line.getAttribute("x2")).length,
      ),
    )
    .toBeGreaterThan(0);

  await page.getByRole("tab", { name: "提交详情" }).click();

  await expect(page.locator("#commitDetailText")).toContainText("commit abc123456789");
  await expect(page.locator("#changedFiles").getByText("frontend/src/App.vue")).toBeVisible();
  await expect(page.locator("#changedFiles").getByText("42", { exact: true })).toBeVisible();
});

test("日志树连线颜色会沿同一条路径保持一致", async ({ page }) => {
  await openApp(page);

  await page.getByRole("tab", { name: "日志树" }).click();
  await page.getByRole("button", { name: "加载日志" }).click();

  const segments = await page.locator("#logRows .log-graph-svg line").evaluateAll((lines) =>
    lines.map((line) => ({
      x1: Number(line.getAttribute("x1")),
      y1: Number(line.getAttribute("y1")),
      x2: Number(line.getAttribute("x2")),
      y2: Number(line.getAttribute("y2")),
      stroke: line.getAttribute("stroke") || "",
    })),
  );
  const nodes = await page.locator("#logRows .log-graph-svg circle").evaluateAll((circles) =>
    circles.map((circle) => ({
      cx: Number(circle.getAttribute("cx")),
      cy: Number(circle.getAttribute("cy")),
      fill: circle.getAttribute("fill") || "",
    })),
  );

  expect(segments.length).toBeGreaterThan(0);
  expect(nodes.length).toBeGreaterThan(0);

  const laneXs = [
    ...segments.flatMap((segment) => [segment.x1, segment.x2]),
    ...nodes.map((node) => node.cx),
  ].filter((value) => Number.isFinite(value));
  const mainLaneX = Math.min(...laneXs);

  expect(segments.some((segment) => segment.stroke === "#111827" && segment.x1 === mainLaneX && segment.x2 === mainLaneX)).toBe(true);
  expect(
    segments.some(
      (segment) =>
        segment.stroke === "#ef1b1b" &&
        segment.x1 !== segment.x2 &&
        Math.max(segment.x1, segment.x2) > mainLaneX &&
        Math.min(segment.x1, segment.x2) === mainLaneX,
    ),
  ).toBe(true);
  expect(nodes.some((node) => node.fill === "#111827" && node.cx === mainLaneX)).toBe(true);
  expect(nodes.some((node) => node.fill === "#ef1b1b" && node.cx > mainLaneX)).toBe(true);
});

test("主视口固定，仓库表格内部滚动", async ({ page }) => {
  const repositories = Array.from({ length: 36 }, (_, index) => ({
    ...baseRepositories[0],
    path: `G:\\Repos\\repo-${String(index).padStart(2, "0")}`,
    name: `repo-${String(index).padStart(2, "0")}`,
    selected: true,
  }));

  await openApp(page, { repositories });

  const scrollMetrics = await page.evaluate(() => {
    const tableBody = document.querySelector("#repoTable .vxe-table--body-inner-wrapper");
    const virtualScrollHandle = document.querySelector("#repoTable .vxe-table--scroll-y-handle");
    return {
      documentOverflows:
        document.documentElement.scrollHeight > document.documentElement.clientHeight,
      bodyOverflows: document.body.scrollHeight > document.body.clientHeight,
      tableBodyOverflows: tableBody ? tableBody.scrollHeight > tableBody.clientHeight : false,
      virtualScrollOverflows: virtualScrollHandle
        ? virtualScrollHandle.scrollHeight > virtualScrollHandle.clientHeight
        : false,
    };
  });

  expect(scrollMetrics.documentOverflows).toBe(false);
  expect(scrollMetrics.bodyOverflows).toBe(false);
  expect(scrollMetrics.tableBodyOverflows).toBe(true);
  expect(scrollMetrics.virtualScrollOverflows).toBe(true);
});

test("仓库列表详情和操作日志分隔条可以拖动并保存尺寸", async ({ page }) => {
  const harness = await openApp(page);
  const detailPanel = page.locator(".detail-panel");
  const activityPanel = page.locator(".activity-panel");
  const verticalSplitter = page.locator(".layout-splitter-vertical");
  const horizontalSplitter = page.locator(".layout-splitter-horizontal");

  const beforeDetail = await detailPanel.boundingBox();
  const verticalBox = await verticalSplitter.boundingBox();
  expect(beforeDetail).not.toBeNull();
  expect(verticalBox).not.toBeNull();

  await page.mouse.move(verticalBox!.x + verticalBox!.width / 2, verticalBox!.y + verticalBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(verticalBox!.x - 80, verticalBox!.y + verticalBox!.height / 2, { steps: 6 });
  await page.mouse.up();

  const afterDetail = await detailPanel.boundingBox();
  expect(afterDetail).not.toBeNull();
  expect(afterDetail!.width).toBeGreaterThan(beforeDetail!.width + 40);

  const beforeActivity = await activityPanel.boundingBox();
  const horizontalBox = await horizontalSplitter.boundingBox();
  expect(beforeActivity).not.toBeNull();
  expect(horizontalBox).not.toBeNull();

  await page.mouse.move(horizontalBox!.x + horizontalBox!.width / 2, horizontalBox!.y + horizontalBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(horizontalBox!.x + horizontalBox!.width / 2, horizontalBox!.y - 56, { steps: 6 });
  await page.mouse.up();

  const afterActivity = await activityPanel.boundingBox();
  expect(afterActivity).not.toBeNull();
  expect(afterActivity!.height).toBeGreaterThan(beforeActivity!.height + 32);

  const saveCalls = (await harness.getCalls()).filter(
    (call: { command: string }) => call.command === "save_repositories",
  );
  const latestUiState = saveCalls.at(-1).args.uiState;
  expect(latestUiState.layoutDetailWidth).toBeGreaterThan(420);
  expect(latestUiState.layoutActivityHeight).toBeGreaterThan(158);
  expect(Number.isInteger(latestUiState.layoutDetailWidth)).toBe(true);
  expect(Number.isInteger(latestUiState.layoutActivityHeight)).toBe(true);
});
