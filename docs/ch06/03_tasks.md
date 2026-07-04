
1. 既有 `/plan`·`/do` 用例适配 `permission.Mode`（`Mode.PLAN`/`Mode.DEFAULT`）。​
2. 新增（使用 Textual 的 `App.run_test()` 异步上下文 + `Pilot`）：​
   - 连续 `await pilot.press("shift+tab")`（idle 态）→ 断言 `app.mode` 依次 `Mode.DEFAULT`→`ACCEPT_EDITS`→`PLAN`→`BYPASS`→`DEFAULT`、停留 idle、每次有提示块写入 RichLog。​
   - 通过 fake agent 注入 `ApprovalRequest` 事件 → 断言 `app.state == APPROVING`、`app.pending` 已设、`approve_cursor == 0`；`await pilot.press("down")` 再 `enter`→`respond` 收到 `Outcome.ALLOW_FOREVER`；另测数字键 `1`→`ALLOW_ONCE`、`3`→`DENY_ONCE`，回 `STREAMING`。​
   - approving 态按 `escape`/`ctrl+c`→ 触发取消、`respond` 收到兜底 `Outcome.DENY_ONCE`、应用未退出。​
   - `status_bar` 左侧在各模式显示对应模式名（DEFAULT/ACCEPT EDITS/PLAN/BYPASS），且**不含 provider 名**。​
   - **模式跨轮保持**：Shift+Tab 切到 `ACCEPT_EDITS` 后再 `begin_turn`，断言 `app.mode` 仍为 `ACCEPT_EDITS`（不被重置）。​
​
**验证：** `pytest tests/test_tui.py -q`（带 `pytest-asyncio` + Textual 测试工具）。​
​
## T12: cli / smoke / 配置文件接线**文件：** `src/mewcode/cli.py`、`smoke/main.py`、`.gitignore`、`.mewcode/settings.yaml.example`​
**依赖：** T6, T8, T10​
**步骤：**​
1. `cli.py`：`root = str(Path.cwd().resolve())`；`engine, err = permission.new_engine(root)`；`if err is not None: print("权限引擎降级:", err, file=sys.stderr)` 后**继续**（`engine` 必非 None）；`app = tui.new_app(cfg.providers, version, registry, engine)`（沿用既有错误处理）。​
2. `smoke/main.py`：新增 `cwd = str(Path.cwd().resolve())`；`engine, _ = permission.new_engine(cwd)`；`agent = new_agent(p, tool.default_registry(), "dev", engine)`；`await run(agent, conv, Mode.BYPASS)`。​
3. `.gitignore`：在「本地配置」段追加 `.mewcode/settings.local.yaml`。​
4. `.mewcode/settings.yaml.example`：示例——`default_mode: default`；`permissions.allow: ["Bash(git *)", "Bash(pytest)"]`；`permissions.deny: ["Bash(rm *)", "Read(.env)", "Write(.env)"]`；注释说明三层文件与优先级，并注明**只读类默认即 Allow，allow 规则主要用于提前放行 Bash/Write，deny 规则可对只读做围栏（如 Read(.env)）**。​
​
**验证：** `python -m mewcode --version` 不抛；`python -m smoke` 在含 write_file 的脚本下**不阻塞、跑完**（确认 `Mode.BYPASS` 跳过 Ask）；`python -m mewcode` 能正常启动进对话。​
​
## T13: 全量编译测试与规范**文件：** —​
**依赖：** T1–T12​
**步骤：**​
1. `ruff format --check .`（通过；本地 `ruff format .` 已统一）。​
2. `ruff check .`（无告警；`permission` 子包按本地包分组，import 顺序正确）。​
3. `pytest`、`pytest --timeout=30 tests/test_agent.py tests/test_permission_*.py tests/test_tui.py`。​
4. （可选）`mypy src/mewcode` 通过（含 `permission` 子包）。​
5. 确认 `.mewcode/settings.local.yaml` 已被 gitignore（`git check-ignore`）；检索输出无 api_key 明文。​
6. **tmux 实跑冒烟**（CLAUDE.md 开发原则第 2 条）：default 下写文件触发 Ask 弹窗；Shift+Tab 循环到 `bypassPermissions` 后不再 Ask、状态栏左侧显示 `BYPASS`；`rm -rf /` 在 bypass 下仍被拦。​
​
**验证：** 全部通过。​
​
## 执行顺序​
​
```​
T1(类型) ─┬───────────────────────────────────┐​
T2(黑名单)─┤                                    │​
T3(沙箱) ──┤                                    ├─→ T6(引擎/流水线) ─→ T7(规则写入)​
T4(规则) ──┴─→ T5(配置/映射) ───────────────────┘                          │​
                                                                            │​
                                              T6,T7 ─→ T8(agent 接入) ─┬─→ T9(agent 单测)​
                                                                       ├─→ T10(TUI 接入) ─┬─→ T11(TUI 单测)​
                                                                       │                  │​
                                                          T6,T8,T10 ─→ T12(cli/smoke/配置)​
全部 ─→ T13(ruff/pytest/mypy/tmux)​
```​
（依赖：T5←{T1,T4}；T6←{T1,T2,T3,T4,T5}；T7←{T5,T6}；T8←{T6,T7}；T9←T8；T10←T8；T11←T10；T12←{T6,T8,T10}；T13←全部。）