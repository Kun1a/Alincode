# AlinCode 桌面聊天三栏布局任务

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `webui/src/state/chatReducer.ts` | 保存当前会话环境字段。 |
| 新建 | `webui/src/components/EnvironmentPanel.tsx` | 展示只读环境摘要。 |
| 修改 | `webui/src/components/Sidebar.tsx` | 展示品牌、Profile 和历史。 |
| 修改 | `webui/src/components/ChatView.tsx` | 组织三栏工作区。 |
| 修改 | `webui/src/components/StatusBar.tsx` | 展示紧凑运行状态。 |
| 修改 | `webui/src/components/MessageList.tsx` | 保持消息行为并提供布局钩子。 |
| 修改 | `webui/src/components/Composer.tsx` | 保持发送行为并提供布局钩子。 |
| 修改 | `webui/src/styles.css` | 实现深海蓝三栏视觉。 |
| 修改 | `docs/superpowers/plans/2026-09-01-windows-desktop-agent-checklist.md` | 记录实际验收结果。 |

## T1：保存会话环境字段

**文件：** `webui/src/state/chatReducer.ts`

**依赖：** 无。

**步骤：**

1. 为 `ChatState` 添加 `workspace`、`model`、`mode` 字段，并在 `initialChatState` 中以空字符串初始化。
2. 在 `session.info` 分支中保存 `workspace`、`model`、`mode`，同时保留原有连接与会话 ID 更新。
3. 运行 `npm run build`（目录：`webui`），确认 TypeScript 构建成功。
4. 提交 `webui/src/state/chatReducer.ts`，提交信息：`feat: retain chat environment state`。

**验证：** `npm run build` 成功，且 `session.info` 字段没有未使用或类型错误。

## T2：新增右侧环境栏

**文件：** `webui/src/components/EnvironmentPanel.tsx`、`webui/src/components/ChatView.tsx`

**依赖：** T1。

**步骤：**

1. 新建 `EnvironmentPanel`，通过 `useChat` 读取连接状态、模型、目录、用量和预算。
2. 在组件挂载时只读请求 `/api/profile/provider`，仅显示协议和模型；不将 API Key 放入组件状态、DOM 或日志。
3. 为未连接、未配置模型、未选择目录、未设置预算分别显示明确文字；预算为 `0` 时不渲染比例进度。
4. 在 `ChatView` 中对存在 Profile 的桌面页面渲染环境栏；无 Profile 的 `--web` 入口不渲染该栏。
5. 运行 `npm run build`（目录：`webui`）。
6. 提交两个组件文件，提交信息：`feat: add chat environment panel`。

**验证：** 有 Profile 的页面存在右栏；Provider 请求失败时仍能构建并显示「未配置」。

## T3：重排真实导航与对话区域

**文件：** `webui/src/components/Sidebar.tsx`、`webui/src/components/ChatView.tsx`、`webui/src/components/StatusBar.tsx`、`webui/src/components/MessageList.tsx`、`webui/src/components/Composer.tsx`

**依赖：** T1、T2。

**步骤：**

1. 让 `Sidebar` 接收 `Profile`，显示 `/alincode-a-mark.png`、产品名称和 Profile 摘要；会话读取、恢复和新建仍调用原有逻辑。
2. 将 `ChatView` 的标题改为会话标题与目录摘要，并将设置按钮留在中栏标题。
3. 使 `StatusBar` 仅展示连接、运行、轮次和预算耗尽等实时状态，不展示冗长会话 ID。
4. 为现有消息块添加布局容器，为输入框增加装饰性加号和带 `aria-label` 的发送按钮；不修改 `sendText`、取消或键盘处理逻辑。
5. 运行 `npm run build`（目录：`webui`）。
6. 在开发服务中手工验证：新建对话、切换历史、发送、取消、打开与关闭设置。
7. 提交上述 5 个组件文件，提交信息：`feat: restructure desktop chat workspace`。

**验证：** 所有现有聊天交互可用，历史仍只属于当前 Profile。

## T4：实现深海蓝三栏视觉并验收

**文件：** `webui/src/styles.css`、`docs/superpowers/plans/2026-09-01-windows-desktop-agent-checklist.md`

**依赖：** T1、T2、T3。

**步骤：**

1. 保持登录页和设置页选择器兼容，在聊天选择器中定义深海蓝、青蓝高亮、柔和边线和可读排版令牌。
2. 使用 CSS Grid 实现左栏 `268px`、中栏弹性、右栏 `306px` 的桌面布局；中栏消息区独立滚动。
3. 让用户消息以低饱和蓝色气泡显示，助手消息保持无气泡阅读面，工具和审批保持现有展开/按钮行为。
4. 在小于 `1120px` 时压缩侧栏，小于 `900px` 时隐藏右栏；为交互元素添加可见焦点样式并尊重减少动效偏好。
5. 运行 `npm run build`（目录：`webui`）与 `uv run pytest`（项目根目录）。
6. 重新打包或启动桌面端，用已有 Profile 发送真实消息，确认右栏用量更新且左栏能恢复会话。
7. 在 tmux 启动 TUI，输入需要读取项目目录的真实请求，观察工具调用与回复；只勾选有证据的既有 checklist 条目。
8. 提交样式和已更新 checklist，提交信息：`feat: style desktop chat layout`。

**验证：** Windows 桌面端加载新三栏布局；前端构建、后端测试和一次 TUI 端到端对话均有实际成功证据。

## 执行顺序

```text
T1 → T2 → T3 → T4
```
