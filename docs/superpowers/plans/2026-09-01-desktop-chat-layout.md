# AlinCode 桌面聊天三栏布局实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改动 Agent 和本机 Profile 行为的前提下，将已实现的桌面聊天页改造成符合已确认原型的三栏工作区。

**架构：** 保留 `ChatProvider` 作为唯一的 WebSocket 状态来源。扩展它已接收的 `session.info` 字段，使中栏标题和右栏环境数据直接来自当前会话；新增一个只读 `EnvironmentPanel` 负责 Provider 协议和环境摘要。`ChatView` 只负责编排三栏，`Sidebar` 接收当前 Profile 展示品牌和身份。

**技术栈：** React 18、TypeScript、现有 Vite 构建、现有 FastAPI Profile API 与 WebSocket 协议。

---

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `webui/src/lib/protocol.ts` | 保持 `session.info` 的模型、目录和模式字段类型可用。 |
| 修改 | `webui/src/state/chatReducer.ts` | 在聊天状态中保存当前会话的模型、目录和模式。 |
| 新建 | `webui/src/components/EnvironmentPanel.tsx` | 只读显示连接、模型、协议、目录和本地额度。 |
| 修改 | `webui/src/components/Sidebar.tsx` | 增加品牌、Profile 摘要和可读的历史空状态。 |
| 修改 | `webui/src/components/ChatView.tsx` | 组合左栏、中栏、右栏，并保留设置弹窗。 |
| 修改 | `webui/src/components/StatusBar.tsx` | 将状态信息变成中栏紧凑会话摘要。 |
| 修改 | `webui/src/components/MessageList.tsx` | 增加语义化消息角色容器，不改变消息内容和滚动行为。 |
| 修改 | `webui/src/components/Composer.tsx` | 保留原发送/取消逻辑，提供原型对应的输入区结构。 |
| 修改 | `webui/src/styles.css` | 以深海蓝设计令牌重写聊天页三栏、消息和响应式样式；登录/设置样式保持兼容。 |

## 任务 1：会话环境状态

**文件：**
- 修改：`webui/src/state/chatReducer.ts`
- 修改：`webui/src/lib/protocol.ts`

- [ ] **步骤 1：扩展初始聊天状态**

在 `ChatState` 与 `initialChatState` 中增加以下字段，空字符串表示后端尚未送达会话信息：

```ts
workspace: string;
model: string;
mode: string;

workspace: "", model: "", mode: "",
```

- [ ] **步骤 2：在 `session.info` 事件中保存环境字段**

将分支替换为：

```ts
case "session.info":
  return {
    ...state,
    connected: true,
    sessionId: msg.session_id,
    workspace: msg.workspace,
    model: msg.model,
    mode: msg.mode,
  };
```

- [ ] **步骤 3：验证类型和构建**

运行：`npm run build`（工作目录：`webui`）

预期：TypeScript 编译和 Vite 构建成功，且没有协议字段类型错误。

- [ ] **步骤 4：提交**

```bash
git add webui/src/state/chatReducer.ts webui/src/lib/protocol.ts
git commit -m "feat: retain chat environment state"
```

## 任务 2：右侧环境栏

**文件：**
- 新建：`webui/src/components/EnvironmentPanel.tsx`
- 修改：`webui/src/components/ChatView.tsx`

- [ ] **步骤 1：编写 `EnvironmentPanel` 的只读数据模型**

组件只读取现有的 `/api/profile/provider`，不传递或保存 API Key。Provider 响应仅用于展示 `protocol` 和 `model`；请求失败时显示「未配置」。

```ts
type ProviderSummary = { protocol: string; model: string };
const [provider, setProvider] = useState<ProviderSummary | null>(null);

useEffect(() => {
  void fetch("/api/profile/provider")
    .then(response => response.ok ? response.json() as Promise<ProviderSummary> : null)
    .then(setProvider)
    .catch(() => setProvider(null));
}, []);
```

- [ ] **步骤 2：使用现有 `useChat` 状态渲染环境摘要**

渲染连接状态、`state.model || provider?.model || "未配置模型"`、协议、`state.workspace || "尚未选择项目目录"`、`state.usedTokens` 与 `state.budget`。预算为 `0` 时只显示「未设置上限」，不得计算百分比。

- [ ] **步骤 3：将环境栏接入桌面壳**

在 `ChatView` 中仅当 `profile` 存在时渲染右栏，保留无 Profile 的 `--web` 调试入口：

```tsx
<div className="desktop-shell">
  {profile ? <Sidebar profile={profile} /> : null}
  <main className="chat-view">{/* 既有标题、状态、消息、输入 */}</main>
  {profile ? <EnvironmentPanel /> : null}
</div>
```

- [ ] **步骤 4：验证构建和空状态**

运行：`npm run build`（工作目录：`webui`）。

手工验证：在未设置预算或目录的 Profile 中打开桌面端，右栏分别显示「未设置上限」和「尚未选择项目目录」。

- [ ] **步骤 5：提交**

```bash
git add webui/src/components/EnvironmentPanel.tsx webui/src/components/ChatView.tsx
git commit -m "feat: add chat environment panel"
```

## 任务 3：左栏与会话主区结构

**文件：**
- 修改：`webui/src/components/Sidebar.tsx`
- 修改：`webui/src/components/ChatView.tsx`
- 修改：`webui/src/components/StatusBar.tsx`
- 修改：`webui/src/components/MessageList.tsx`
- 修改：`webui/src/components/Composer.tsx`

- [ ] **步骤 1：为左栏传入 Profile 并渲染已有品牌资源**

调整 `Sidebar` 签名：

```tsx
export function Sidebar({ profile }: { profile: Profile }) { /* ... */ }
```

在新建会话按钮前使用 `/alincode-a-mark.png`、`AlinCode` 与「你的本地 Coding Agent」；在底部显示 `profile.name` 和「仅保存在这台设备」。历史列表仍只调用现有的 `resumeSession`。

- [ ] **步骤 2：将标题和状态分层**

标题显示 `state.sessionId ? "当前对话" : "新建对话"` 与项目目录末段；`StatusBar` 保留连接、轮次、运行中和预算耗尽状态，但不再显示冗长会话 ID。

- [ ] **步骤 3：为消息和输入添加不改变行为的语义结构**

`MessageList` 为用户、助手、工具、审批和提示保留现有组件及事件，只增加 `.message-row`/`.message-meta` 包装。`Composer` 保留 `sendText`、Enter 发送、Shift+Enter 换行、取消逻辑，只增加加号和圆形发送按钮的结构与可访问标签。

- [ ] **步骤 4：验证现有交互未回归**

运行：`npm run build`（工作目录：`webui`）。

手工验证：新建会话、切换历史、发送普通消息、Agent 运行时取消、打开与关闭设置均按原有行为工作。

- [ ] **步骤 5：提交**

```bash
git add webui/src/components/Sidebar.tsx webui/src/components/ChatView.tsx webui/src/components/StatusBar.tsx webui/src/components/MessageList.tsx webui/src/components/Composer.tsx
git commit -m "feat: restructure desktop chat workspace"
```

## 任务 4：视觉样式和桌面验收

**文件：**
- 修改：`webui/src/styles.css`
- 验证：`docs/superpowers/plans/2026-09-01-windows-desktop-agent-checklist.md`

- [ ] **步骤 1：定义聊天页设计令牌**

在保留登录/设置通用变量兼容性的前提下，增加深海蓝聊天令牌：

```css
--chat-night: #07131e;
--chat-surface: #101f2b;
--chat-main: #0b1824;
--chat-line: rgba(114, 185, 222, .18);
--chat-accent: #48b9f2;
--chat-aqua: #67e2d4;
```

- [ ] **步骤 2：实现桌面三栏与消息视觉层级**

`.desktop-shell` 使用 `grid-template-columns: 268px minmax(500px, 1fr) 306px`。中栏最大化阅读宽度；左栏和环境栏使用独立滚动。用户消息使用低饱和蓝色气泡，助手文字不使用气泡，工具与审批沿用可展开卡片语义。

- [ ] **步骤 3：实现窄窗口规则与无障碍焦点**

当窗口小于 `1120px` 时压缩两侧栏宽；当小于 `900px` 时隐藏右侧环境栏，不隐藏历史栏。所有按钮和输入框保留可见键盘焦点；不增加持续动画。

- [ ] **步骤 4：构建和桌面端端到端验证**

运行：`npm run build`（工作目录：`webui`），然后运行项目现有打包/桌面启动命令。

预期：构建产物可被桌面窗口加载；使用已有 Profile 完成一次真实聊天请求，右栏用量变化且左栏可恢复该会话。

- [ ] **步骤 5：运行全量回归**

运行：`uv run pytest`（项目根目录）。

预期：全部后端自动化测试通过。

- [ ] **步骤 6：按现有项目规则执行 tmux 端到端验证并更新 checklist**

在 tmux 启动 AlinCode，输入一个需要读取工作目录的真实编程请求，观察工具调用和回复。仅将有实际证据的既有 checklist 条目改为 `[x]`，记录命令或观察结果。

- [ ] **步骤 7：提交**

```bash
git add webui/src/styles.css docs/superpowers/plans/2026-09-01-windows-desktop-agent-checklist.md
git commit -m "feat: style desktop chat layout"
```

## 执行顺序

```text
任务 1 → 任务 2 → 任务 3 → 任务 4
```

任务 2 和任务 3 都依赖任务 1 的会话环境字段；任务 4 统一完成视觉样式和端到端验证。
