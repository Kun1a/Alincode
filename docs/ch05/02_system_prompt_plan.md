
├── src/mewcode/prompt/​
│   ├── __init__.py        — 改：导出 Module/装配/build_system_prompt；保留 banner（CAT_BANNER/render_banner/READY_HINT）​
│   ├── modules.py         — 新：fixed_modules()/optional_modules() 七固定+三空槽的内容常量​
│   ├── environment.py     — 新：Environment / gather_environment / Environment.render​
│   └── reminder.py        — 新：system_reminder / plan_reminder（完整版/精简版常量）/ EXECUTE_DIRECTIVE​
├── src/mewcode/llm/​
│   ├── __init__.py        — 改:Request/System dataclass；Usage 加缓存字段；Provider.stream 签名；删 _effective_system​
│   ├── anthropic_provider.py — 改：两块 system（断点+env）、缓存用量解析、reminder 织入​
│   └── openai_provider.py    — 改：单条 system（stable+env）、cached_tokens 解析、reminder 尾部注入​
├── src/mewcode/agent/​
│   └── agent.py           — 改：__init__(+version)、run 采集环境/装配系统、按轮次 reminder、缓存透传​
├── src/mewcode/tool/​
│   ├── edit_file.py       — 改：DESCRIPTION 补强化​
│   └── bash.py            — 改：DESCRIPTION 补强化​
├── src/mewcode/tui/​
│   └── stream.py          — 改：Agent(...) 传 version（m.version 已有）​
├── examples/smoke.py      — 改：打印缓存用量；Agent(p, registry, "dev")​
└── tests/​
    ├── test_prompt.py     — 新：装配顺序/跳空槽/N1 确定性/双重强化文本断言​
    ├── test_anthropic_system.py — 新：序列化稳定块带 cache_control、环境块不带（守护回归）​
    └── test_agent.py      — 改：断言 Request 装配（system 两段、规划按轮次 reminder）、缓存用量透传​
```​
​
## 技术决策​
​
| 决策点 | 选择 | 理由 |​
|--------|------|------|​
| 系统提示组织 | 模块化（`Module(name, priority, content)` + `assemble_system`） | 满足 F1「挂载即扩展」；优先级排序使顺序确定（N1） |​
| 环境信息归属 | system 通道独立第二块（用户拍板） | 结构上接系统提示之后；物理上与稳定块分离，不进缓存 |​
| Anthropic 缓存断点 | 仅在稳定 system 块打 `cache_control: ephemeral`（默认 5m） | 请求序 tools→system→messages，断点在稳定块即缓存「工具+稳定块」整段前缀；env 在其后不缓存，env 变化不冲前缀命中 |​
| 工具是否单独打断点 | 否 | 稳定块断点的前缀已含全部工具，无需再给 tool 单独标 cache_control |​
| OpenAI 环境信息 | 拼入单条 system 消息（stable 在前） | 兼容端点对多条 system 支持不一；stable 居前缀，端点前缀缓存自动命中稳定部分。代价：env 居 system 尾，OpenAI 工具可能不进缓存前缀——本章 OpenAI 缓存为尽力而为、不强制（F8） |​
| 缓存用量字段 | `Usage` 加 `cache_write` / `cache_read` | Anthropic 取 `cache_creation_input_tokens`/`cache_read_input_tokens`；OpenAI 取 `prompt_tokens_details.cached_tokens` |​
| stream 入参 | 改 `Request` dataclass | 入参从 4 个增至含 `system`/`reminder`，dataclass 更清晰、后续扩展不再改签名（N8） |​
| reminder 注入位置 | Anthropic 并入末条 user 消息 content 块；OpenAI 追加尾部 user 消息 | Anthropic 严格角色交替——并入避免连续 user 触发 400（N3）；OpenAI 容忍连续 user |​
| reminder 持久化 | 不写入 conversation（用户拍板） | 每轮动态构造；不污染缓存、不破坏历史可恢复性 |​
| 规划提醒节奏 | `iter == 1` 或 `(iter - 1) % 4 == 0` → 完整，否则精简（per `run` 内 iter） | 实现 F7「首轮完整、间隔重复、其余精简」；复用已有 iter 计数 |​
| 缓存验证呈现 | smoke/调试打印（用户拍板） | 不动 TUI 状态栏；`Usage` 携带字段供打印 |​
| prompt↔llm 依赖 | 系统提示由 agent 传入，llm 不再 import prompt | 打破潜在循环依赖；职责更清晰 |​
| 子进程外调 git | `asyncio.create_subprocess_exec("git", "status", "--porcelain")` + `asyncio.wait_for(..., timeout=2.0)`；同步路径回退 `subprocess.run(timeout=2)` | 不阻塞 event loop（N4）；超时/失败均降级为空字符串 |