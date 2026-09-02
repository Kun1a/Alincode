# 文件上下文实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 Windows 桌面端通过一个加号打开多文件选择器，并把安全读取的文本内容加入当前轮请求。

**架构：** FastAPI 调用注入的桌面文件选择器；WebSocket 只接收用户选择返回的路径并在服务端读取、限额和格式化。React Composer 保存本轮附件、展示可移除卡片，发送后清空。

**技术栈：** FastAPI、Python tkinter、WebSocket、React、Vitest、pytest。

---

### 任务 1：原生文件选择与安全读取

**文件：**
- 修改：`Alincode/web/server.py`
- 修改：`Alincode/desktop.py`
- 创建：`Alincode/web/attachments.py`
- 测试：`tests/web/test_server.py`
- 测试：`tests/web/test_session.py`

- [ ] 编写文件选择和文本读取的失败测试。
- [ ] 运行 pytest 确认接口尚不存在。
- [ ] 实现多选文件端点、200 KB 单文件限制和 UTF-8 文本读取。
- [ ] 运行 focused pytest 确认通过。

### 任务 2：本轮上下文注入

**文件：**
- 修改：`Alincode/web/session.py`
- 修改：`webui/src/lib/protocol.ts`
- 测试：`tests/web/test_session.py`

- [ ] 编写带附件发送时 Provider 收到文件路径和内容的失败测试。
- [ ] 实现仅本轮使用的附件提示块，并保持历史界面仅展示用户原消息。
- [ ] 运行 focused pytest 确认通过。

### 任务 3：Composer 附件卡片

**文件：**
- 修改：`webui/src/components/Composer.tsx`
- 修改：`webui/src/state/ChatContext.tsx`
- 修改：`webui/src/styles.css`
- 测试：`webui/src/components/ChatView.test.tsx`

- [ ] 编写加号入口的失败前端测试。
- [ ] 实现文件选择请求、可移除卡片、发送后清空。
- [ ] 运行 Vitest 和生产构建。
