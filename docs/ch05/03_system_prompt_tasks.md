
   - 规划模式下 `req.system.stable` 非空且**普通/规划一致**；`req.system.environment` 非空。​
   - 规划模式 iter1 的 `req.reminder` 含完整提醒、含 `<system-reminder>`；iter2 为精简版（构造一个让循环多轮的脚本）。​
   - 规划模式 `req.tools` 仅只读；普通模式全量。​
   - reminder **不写入 conv 持久历史**（`conv.messages()` 不含 reminder 文本）。​
   - 缓存用量透传：fake 发 `Usage(cache_write=X, cache_read=Y)` → 收到的 `Event.usage` 携带 X/Y。​
​
**验证：** `pytest tests/test_agent.py` 通过；`pytest -p no:randomly tests/test_agent.py`（如启用 randomly 插件）。​
​
## T12: 全量编译测试与规范**文件：** —​
**依赖：** T1–T11​
**步骤：**​
1. `ruff format --check .`（统一格式）。​
2. `ruff check .`（import 分组、无告警）。​
3. `pytest`（全量单测通过）。​
4. （可选）`mypy src/mewcode` 通过子集检查。​
5. `python -m mewcode` 能正常启动。​
​
**验证：** 全部通过；检索输出无 api_key 明文。​
​
## 执行顺序​
​
```​
T1 ─┐​
T2 ─┼─→ T4(prompt 单测)​
T3 ─┘​
T5(工具描述，独立)​
​
T6(接口) ─┬─→ T7(anthropic) ─┐​
          └─→ T8(openai)    ─┤​
T1,T2,T3,T6 ─→ T9(agent) ────┼─→ T10(tui/smoke)​
                              └─→ T11(agent 单测)​
​
全部 ─→ T12(format/check/test)​
```