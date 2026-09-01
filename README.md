# AlinCode

终端 AI 编程助手（类 Codex），Python 实现。支持多 Provider、权限审批、会话持久化、Skills、Hooks、Team 多智能体，以及浏览器端 WebUI。

## 安装

```bash
uv sync
```

## 配置

在项目根目录创建 `config.yaml`：

```yaml
providers:
  - name: default
    protocol: anthropic        # anthropic / openai / openai_compatible
    model: claude-sonnet-4-5
    base_url: https://api.anthropic.com
    api_key: sk-xxx
    context_window: 200000
```

## 终端模式（TUI）

```bash
python -m Alincode              # 或 alincode
python -m Alincode config.yaml  # 指定配置文件
```

## WebUI 模式

TUI 与 Web 共用同一个 agent 事件流（`Agent.run()`），行为一致；agent 核心零改动。

### 启动

```bash
cd webui && npm install && npm run build && cd ..
python -m Alincode --web                       # 默认 127.0.0.1:8765
python -m Alincode --web --host 127.0.0.1 --port 9000
```

浏览器打开 http://127.0.0.1:8765 。

### 开发模式（前端热更新）

```bash
python -m Alincode --web       # 后端 8765
cd webui && npm run dev        # Vite 开发服务器 5173，已配置 /api 与 /ws 代理
```

浏览器打开 http://127.0.0.1:5173 。

### 安全注意

WebUI 可驱动真实工具执行（读写文件、运行命令），MVP 阶段无鉴权。
`--web` 默认仅绑定本机地址；绑定非本机地址前请自行评估风险（启动时会打印警告）。

## Windows 桌面模式

桌面版使用原生窗口承载本机 WebUI，不需要先打开浏览器。首次使用创建本机 Profile；每个 Profile 独立保存密码校验、API Key、项目目录、会话历史与本地 token 统计。

```bash
python -m Alincode --desktop
```

桌面服务只监听 `127.0.0.1` 的随机端口，并用一次性启动令牌建立本机会话。API Key 使用 Windows DPAPI 加密，仅能由保存它的 Windows 用户读取。token 用量是本地统计，**不是供应商账户余额**。

本机数据默认位于 `%LOCALAPPDATA%\AlinCode\profiles`。Profile 不做云同步；如需迁移，请在目标电脑重新配置自己的 API Key。

## Windows 便携包

在 Windows x64 开发机执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

脚本会构建前端、生成 `onedir` 便携目录并输出 `artifacts\AlinCode-windows-x64.zip`。该包无需用户安装 Python 或 Node.js。可执行文件未签名，Windows SmartScreen 可能显示警告；请只从可信来源获取并按提示查看发布者信息。

### 功能范围

已支持：消息流式输出、工具执行行（展开参数/结果）、权限审批卡片（允许本次/永久允许/拒绝）、取消、会话持久化与历史列表。

暂未覆盖（TUI 独有）：斜杠命令、Team 多智能体、子 agent 进度、Plan/AskUser 交互。

## 测试

```bash
uv run pytest tests/ -q
```
