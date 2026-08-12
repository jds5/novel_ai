# ADR 0001：使用 Codex ChatGPT 会话作为本地测试 Provider

- 状态：Accepted
- 日期：2026-08-12

## 决策

阶段 0 原型允许显式选择 `openai_codex_session`，通过官方 Codex CLI 和当前操作系统用户的 ChatGPT 登录执行模型请求，以减少开发期 API 消耗。正式 OpenAI API 与 DeepSeek Provider 保留不变；`chatgpt` 别名仍指向 OpenAI API，避免已有调用无意切换计费与能力语义。

当前开发工作区将 `NOVEL_AI_DEFAULT_MODEL_PROVIDER` 设为 `openai_codex_session`；可复制的示例配置仍默认 `openai`，防止部署时自动启用本地订阅会话。

## 安全边界

- 只允许 `local`、`development`、`test` 环境和单一交互用户；
- 每次调用确认登录类型为 ChatGPT，API Key 登录直接拒绝；
- 子进程不继承 API Key、数据库地址或应用秘密；
- 使用临时空目录、只读沙箱、无审批、ephemeral 会话和忽略用户配置；
- 只从 `--output-last-message` 读取候选结果，JSONL 推理事件不拼接；
- 任意工具 item 或未知 item 使本次候选失败；
- 输出仍执行本地 schema、正文纯净度、一致性与两阶段提交门禁。

## 已知代价

- Codex CLI 是面向 agent 的执行面，不等同于通用推理 API；
- 不保证硬性输出 token 上限、固定模型快照、并发、吞吐、SLA 或长期协议兼容；
- system/user 只能以确定性角色对象序列化到单一 CLI 输入，角色隔离弱于 Responses API；
- OpenAI 严格 Schema 的传输限制可能窄于标准 JSON Schema；只允许带版本记录的语义等价规范化，复杂不兼容 Schema 需要发布新的提示词契约；
- CLI 版本或登录状态变化可能使测试中断，不能触发绕过或自动改用 API Key；
- 上线、多用户测试、批量压力测试和质量基准的最终确认仍必须使用目标正式 Provider。

## 退出条件

满足任一条件时，默认关闭该 Provider：进入共享开发环境或生产环境；需要可承诺的并发与成本核算；需要严格输出 token 限制；官方产品边界、认证方式或 CLI 协议不再支持当前用法。
