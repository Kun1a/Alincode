# Agent 工作流可视化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 AlinCode 网页聊天内以可折叠工作流卡片展示工具执行和本地耗时。

**架构：** `chatReducer` 为实时工具块附加时间戳与耗时；`MessageList` 将连续工具块交给独立 `WorkflowBlock` 渲染。历史工具块不含时间数据，组件只省略耗时标签。

**技术栈：** React 18、TypeScript、Vitest、现有 WebSocket 协议。

---

### 任务 1：记录工具可见耗时

**文件：**
- 修改：`webui/src/lib/protocol.ts`
- 修改：`webui/src/state/chatReducer.ts`
- 测试：`webui/src/state/chatReducer.test.ts`

- [x] 添加失败的 reducer 测试，断言 `tool.start` 后有 `startedAt`，同名 `tool.end` 后有非负 `durationMs`。
- [x] 运行 `npm test -- --run src/state/chatReducer.test.ts`，确认因字段未实现失败。
- [x] 给 `tool` Block 添加可选时间字段，并在 reducer 的 start/end 分支写入/计算最小数据。
- [x] 重跑该测试，确认通过。

### 任务 2：渲染工作流卡片

**文件：**
- 创建：`webui/src/components/WorkflowBlock.tsx`
- 修改：`webui/src/components/MessageList.tsx`
- 修改：`webui/src/styles.css`
- 测试：`webui/src/components/MessageList.test.tsx`

- [x] 添加失败的组件测试：连续两个 `tool` Block 只渲染一个“执行工作流”区域，并显示两个工具名。
- [x] 运行 `npm test -- --run src/components/MessageList.test.tsx`，确认模块或断言失败。
- [x] 实现只负责展示的 `WorkflowBlock`，在 `MessageList` 中顺序聚合连续工具块，保留用户、助手、审批和提示块的显示顺序。
- [x] 添加深海蓝工作流卡片、展开状态、成功/运行中/失败状态及 reduced-motion 样式。
- [x] 重跑组件测试，确认通过。

### 任务 3：全量验证与提交

**文件：**
- 修改：`docs/superpowers/specs/2026-09-02-agent-workflow.md`
- 修改：`docs/superpowers/plans/2026-09-02-agent-workflow.md`

- [x] 运行 `npm test -- --run` 和 `npm run build`。
- [x] 检查 `git diff --check`，仅暂存本计划列出的文件。
- [x] 提交 `feat: visualize agent workflow`。
