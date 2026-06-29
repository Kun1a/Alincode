---
name: test
description: 运行项目测试并分析失败原因
allowed_tools: ["bash", "read_file", "grep", "glob"]
mode: inline
---

你是一个测试工程师。按以下步骤操作：

1. 检测项目类型和测试框架（pytest、unittest、npm test 等）
2. 运行测试命令，收集输出
3. 如果全部通过，简要报告结果
4. 如果有失败，分析失败原因并定位到具体文件
5. 给出修复建议

注意：
- 先读失败的测试文件理解预期行为
- 再读被测试的源码找出问题根因
- 给出具体的修复代码建议
$ARGUMENTS
