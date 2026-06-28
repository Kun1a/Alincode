"""记忆更新 Prompt 模板。"""

MEMORY_UPDATE_PROMPT = """你正在为编程助手的长期记忆做更新。请分析以下最近对话，判断是否有值得记住的信息。

记忆分为四类：
- user_preference: 用户偏好（如回复风格、语言偏好、工作习惯）
- correction_feedback: 纠正反馈（用户指出错误或要求修改）
- project_knowledge: 项目知识（技术栈、架构、约定）
- reference_material: 参考资料（外部链接、文档引用）

记忆分两级存放：
- project: 与当前项目相关的信息（项目知识、参考资料）
- user: 跨项目通用的信息（用户偏好、纠正反馈）

返回 JSON 数组，每个元素描述一个操作。如果无需更新，返回空数组 []。

操作格式：
  {{"action":"create","level":"project","type":"project_knowledge","title":"...","slug":"...","content":"..."}}
  {{"action":"update","level":"user","filename":"user_preference_terse.md","title":"...","content":"..."}}
  {{"action":"delete","level":"project","filename":"project_knowledge_old.md"}}

注意：
- slug 全小写、下划线分隔，如 "api_conventions"、"terse_replies"
- 去重：如果已存在相似笔记，使用 update 而非 create
- 不要调用任何工具，只输出 JSON 数组
- 如果最近对话中没有值得记住的信息，返回 []

当前记忆索引：

{index}

最近对话：

{conversation}"""
