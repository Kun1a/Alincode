
├── src/mewcode/config.py  — 不改（provider 配置与 permission settings 分离）​
├── src/mewcode/cli.py     — 改:构造 permission.Engine 注入 tui​
├── smoke/main.py          — 改:cwd + 构造引擎、Mode.BYPASS 运行​
├── tests/​
│   ├── test_permission_*.py  — 新:黑名单/沙箱(含祖先回退)/规则/优先级/矩阵/加载降级/解析失败 单测​
│   ├── test_agent.py      — 改/新:权限集成(Allow/Deny/Ask/会话/永久)、保序、只读并发不退化、取消、模式迁移​
│   └── test_tui.py        — 改/新:shift+tab 循环切换、approval 态按键回传、Esc 取消兜底、状态栏常驻模式、模式跨轮保持​
├── .gitignore             — 改:加 .mewcode/settings.local.yaml​
└── .mewcode/settings.yaml.example — 新:权限配置示例（default_mode + allow/deny）​
```​
​
## 技术决策​
​
| 决策点 | 选择 | 理由 |​
|--------|------|------|​
| 权限判定落点 | 独立 permission 模块(前四层) + agent 编排层(第五层) | 与 provider 解耦（N6 免费）；逻辑内聚、可单测；不污染 tool/llm |​
| 五层短路 | `check` 顺序 黑名单→沙箱→规则→模式 单函数 early-return；Ask 作第五层信号 | 满足 F6；黑名单/沙箱按类别跳过；规则就近命中即返回；人在回路在 agent |​
| 黑名单不可配 | 模块内编译好的 `re.Pattern` 常量列表、无加载入口 | N1：任何配置/模式都碰不到它；bypass 也拦 |​
| 黑名单完备性 | 启发式、显式声明非完备 | 不可能穷尽危险命令；防御纵深由沙箱+规则+人在回路补 |​
| 沙箱解析顺序 | 先 `Path.resolve(strict=True)`（或最近祖先）再前缀比对 | N2：防软链接逃逸；新建文件按已存在祖先判，避免误判 |​
| 沙箱不管命令执行 | bash 不做路径围栏 | 无法可靠静态解析任意命令的文件访问；交黑名单+规则+模式 |​
| glob/grep 沙箱盲区 | extract_target 取其搜索根 `path` 做围栏；`pattern` 不参与沙箱 | glob/grep 真正遍历目标是 pattern，但任意 pattern 的越界遍历由工具内部 `pathlib.Path.walk`/`os.walk`(不跟随目录软链接)限制；沙箱对 glob/grep 为**尽力围栏搜索根**，登记为已知盲区 |​
| Mode 归属 | 迁到 permission 模块、四档统一 | 用户拍板「统一一个模式轴」；mode 是权限概念，agent/tui 共用 |​
| 模式切换方式 | Shift+Tab 循环四档（含 bypass）；保留 /plan·/do | 用户拍板用 Shift+Tab、四档全循环；/plan·/do 保留计划工作流的执行语义；不再设 /mode 命令 |​
| 状态栏左侧内容 | 常驻显示当前权限模式，取代 provider 名 | 用户拍板「别展示 provider 名、展示权限模式」；右侧模型名+用量不变 |​
| plan 语义 | 沿用 ch04 硬限制（只读工具集+提醒）+ /do | 用户拍板；矩阵 plan 行仅防御性兜底；/plan 与 default_mode=plan 都按 Mode.PLAN 应用 |​
| 模式兜底值域 | 只产 Allow/Ask（无 Deny 档） | 用户拍板矩阵；Deny 仅来自黑名单/沙箱/deny 规则/人在回路 |​
| 规则优先级 | 会话>本地>项目>用户；同层 deny 优先 allow | 用户拍板「越靠近会话越优先」；deny 优先更安全 |​
| 永久放行落点 | 写本地层 `.mewcode/settings.local.yaml`（gitignore） | 用户拍板；不进 git、不影响队友（对齐 Claude Code don't-ask-again） |​
| 自动规则泛化 | 不泛化，只生成精确规则 | 自动猜泛化模式有误放行风险；泛化交用户手写 |​
| 规则名 | 友好名 Bash/Read/Write/Edit/Glob/Grep ↔ 内部名映射 | 用户示例即友好名；对齐 Claude Code 习惯，规则更可读 |​
| 参数解析失败归属 | 文件类不可解析→Deny；bash 缺 command→落 Ask；未知工具→Exec/Ask | N7/AC15 安全默认，绝不静默 Allow |​
| 人在回路选项集 | 三选一（允许本次/永久/拒绝）+ 菜单式 ↑↓·回车·数字键直选、默认高亮允许本次 | 用户拍板 1:1 复刻 Claude Code；永久=精确写本地配置；砍掉本会话 Outcome（会话级层移除，规则只走三个文件层） |​
| 人在回路回路 | `ApprovalRequest` 事件 + agent 内 `await asyncio.Future` | Textual 单线程事件循环；事件 + Future 是 async 惯用法；`CancelledError` 可解阻塞（N4） |​
| respond 通道 | `asyncio.Future` 单次未来量 | TUI 调 `set_result(...)` 永不阻塞；取消竞态下兜底送 `DENY_ONCE` 不泄漏 |​
| approving 态取消 | 全局 ctrl+c/esc 分派覆盖 Approving | 否则 approving 态 ctrl+c 走 `app.exit()` 退出程序，违 N4 |​
| 会话/永久规则写入方 | agent 在 Loop 内调引擎（TUI 只回传 Outcome） | 引擎状态变更集中一处；职责清晰 |​
| 只读权限检查 | 批内逐个 check，但只读永不 Ask | N3：保留 ch04 并发（`asyncio.gather`）；只读最多被沙箱/deny 规则拦为 Deny，无需交互 |​
| settings 与 config 分离 | 新 settings.yaml(.local) 而非塞进 config.yaml | 权限配置与 provider 凭据职责不同；config.yaml 已精确 gitignore（含密钥），settings 项目级需可提交 |​
| smoke 运行模式 | Mode.BYPASS、根于 cwd | 非交互无法人在回路；bypass 跳过 Ask（黑名单/沙箱仍在），用例文件操作须落 cwd 内 |​
| new_engine 失败处理 | 致命错(仅 resolve_root)也返回非 None 空规则安全引擎 + err | cli 注入永不为 None、check 不抛；配置格式错只降级不致错（N5） |