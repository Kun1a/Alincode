# AlinCode Windows 便携版

## 使用方法

1. 解压整个压缩包到本地目录，不要只复制 `AlinCode.exe`。
2. 双击 `AlinCode.exe` 启动。
3. 首次启动创建本机 Profile，并填写自己的 API Key、模型和项目目录。
4. 后续启动选择 Profile 并输入本机密码。

无需安装 Python 或 Node.js。Windows SmartScreen 可能提示未签名应用；请只运行来自可信朋友的压缩包。

## 数据与安全

- Profile、API Key、对话历史和本地 token 统计只保存在当前 Windows 用户的数据目录。
- API Key 由 Windows DPAPI 加密，不能在其他 Windows 用户账户中直接读取。
- token 用量是 AlinCode 的本地统计，不是 API 供应商账户余额。
- 每位使用者应填写自己的 API Key，不要共用或发送密钥。

## 项目目录与自定义指令

在设置中填写的「项目目录」是 Agent 读写文件、执行命令和加载项目级自定义内容的目录。

可在该目录放置以下文件：

- `ALINCODE.md`：项目指令文件。重新打开 AlinCode 后会加载它；支持使用 `@include 相对文件名` 引入同目录中的其他 Markdown 文件。
- `.Alincode/ALINCODE.md`：项目内部的补充指令文件。
- `.Alincode/skills/<技能名>/SKILL.md`：项目级 Skill。添加或修改后，下一轮对话会自动重新扫描。

不要使用旧的 `MEWCODE.md` 文件名；该版本不会加载它。

## 常见问题

**新建对话会要求重新登录吗？** 不会。它会保留当前已解锁的 Profile，并创建一条新的空对话。

**程序无法启动怎么办？** 确认没有移动或删除 `_internal` 目录，然后重新从压缩包完整解压。
