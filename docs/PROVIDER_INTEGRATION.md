# 模型供应商接入设计

> 状态：Implemented v0.2  
> 更新日期：2026-08-12

## 1. 目标与边界

应用层只依赖统一的 `ModelRequest`、`ProviderResponse` 和 `GatewayOutput`，不读取供应商 SDK 对象。供应商适配器负责请求格式、响应项选择、结束状态和错误归一化；提示词版本、上下文快照、正文门禁及正式提交仍由上层工作流负责。

正式运行中的“支持 ChatGPT”由 OpenAI API 供应商实现，`chatgpt` 仍是其路由别名。为降低阶段 0 原型成本，系统另提供显式的 `openai_codex_session` 测试通道：它只调用官方 Codex CLI、只接受本机用户的 ChatGPT 登录，不抓取网页、不读取 Cookie、不接受 API Key 登录。该通道仅限 `local`、`development`、`test` 环境，不能作为生产、多租户、共享账号或 SLA 后端。

## 2. 能力矩阵

| 能力 | OpenAI API | OpenAI Codex Session | DeepSeek |
| --- | --- | --- | --- |
| 接口 | Responses API | 官方 `codex exec` CLI | Chat Completions API |
| 用途 | 正式/测试 | 本地单用户测试 | 正式/测试 |
| 结构化输出 | 严格 JSON Schema | `--output-schema` | JSON Object |
| 最终文本来源 | assistant `output_text` | `--output-last-message` 文件 | `message.content` |
| 推理隔离 | reasoning item 分离 | JSONL 事件流与最终文件分离 | `reasoning_content` 分离 |
| 完成判断 | response status 与 incomplete details | 退出码、事件流、非空最终文件 | `finish_reason` |
| 输出 token 硬上限 | 支持 | 不保证 | 支持 |
| 本地 schema 校验 | 必须 | 必须 | 必须 |
| 生产可用 | 是 | 否 | 是 |
| 当前流式实现 | 未开放 | 未开放 | 未开放 |

DeepSeek 官方文档特别说明 JSON Output 仍可能返回空内容，且 `finish_reason=length` 时内容可能被截断。因此网关只把 `stop + 非空 content` 归一化为完成；空内容、长度限制、资源不足都作为不可提交的 `INCOMPLETE`。

## 3. 请求契约

统一请求包括：

- 精确模型名；
- system/user 最终渲染文本；
- 最大输出 token；
- 可选 JSON Schema 与 schema 名；
- 可选温度、reasoning effort 和 thinking 开关。

适配器不得向 system/user 文本追加隐式行为指令，否则上下文快照不再等于实际发送内容。DeepSeek 结构化请求若提示中没有明确出现 `JSON`，适配器直接拒绝；提示词作者必须在版本化模板中修正。

OpenAI 请求使用 `store=false`，结构化输出映射到 `text.format.type=json_schema` 且 `strict=true`。DeepSeek 映射到 `response_format.type=json_object`，随后由网关使用同一个本地 schema 验证。

OpenAI 严格模式要求 `const`、同类型 `enum` 等节点显式携带 JSON 类型。已发布提示词 Schema 保持不可变；OpenAI API 与 Codex Session 共用版本化的语义等价规范化器，只补充可确定推导的 `type`，不删除或放宽约束。原始 Schema、实际发送 Schema 和规范化器版本均可追踪；无法语义等价转换的 Schema 不得由适配器猜测改写。

Codex CLI 没有 Responses API 的 system/user 双角色调用面，因此适配器只做确定性 JSON 序列化：`system_instructions` 与 `user_request` 的值逐字来自已渲染提示词，不附加新的创作指令。该实际传输文本进入隔离原始调用记录。提示词本身仍必须来自 `src/novel_ai/prompts/catalog/`；供应商适配器不得内联正文写作、提取或审校提示词。

Codex 会话不可靠支持 `temperature`、`thinking_enabled` 和硬性 `max_output_tokens`。前两者一旦传入立即报配置错误；后者作为统一请求预算保留，但能力元数据明确标记为不保证。需要严格 token 截断语义的测试必须改用 API。

## 4. 响应隔离

适配器只从供应商指定的最终响应位置生成 `final_text`：

- OpenAI：assistant message 中的 `output_text`；
- OpenAI Codex Session：`--output-last-message` 指定文件的完整内容；
- DeepSeek：唯一 choice 的 `message.content`。

OpenAI reasoning item、Codex JSONL 事件流和 DeepSeek `reasoning_content` 只进入隔离原始响应；它们不会与 `final_text` 拼接。Codex 事件只允许 `reasoning` 和 `agent_message`，若出现命令执行、文件修改、MCP、搜索或未知 item，即使 CLI 最终返回文本也拒绝本次结果。意外工具调用、多个最终消息、未知内容项、拒绝、截断、空响应或无效响应结构均不能生成业务 artifact。

原始响应可进入隔离对象存储用于审计。关系数据库只保存供应商、端点、模型快照、请求/响应 ID、响应状态、结束原因、输出项类型、系统指纹、token、耗时和原始对象 URI，不在审计元数据中复制正文或推理内容。

## 5. 错误与重试

统一错误携带稳定 code、供应商、HTTP 状态和 `retryable`：

- 超时、网络错误、429、5xx：可重试；
- 缺少密钥、认证失败、非法请求、不支持的参数：不可盲目重试；
- 截断、空响应、schema 不匹配：可生成新 attempt，但旧产物不可复用；
- 内容过滤或明确拒绝：进入策略处置或人工审核，不按普通瞬时错误循环重试。
- Codex 未登录、使用 API Key 登录、生产环境启用或模型不可用：不可重试；订阅用量限制可在额度恢复后重试。

实际重试次数和退避由持久化工作流控制，适配器自身不做隐式重试，避免产生不可见的额外成本和重复调用。

## 6. 配置

| 环境变量 | 说明 |
| --- | --- |
| `NOVEL_AI_DEFAULT_MODEL_PROVIDER` | 默认模型路由；本地可设为 `openai_codex_session`，生产应使用正式 Provider |
| `NOVEL_AI_OPENAI_API_KEY` | OpenAI API 密钥 |
| `NOVEL_AI_OPENAI_BASE_URL` | 默认 `https://api.openai.com` |
| `NOVEL_AI_OPENAI_DEFAULT_MODEL` | OpenAI 默认模型 |
| `NOVEL_AI_CODEX_SESSION_ENABLED` | 是否显式开启本地订阅测试通道，默认 `false` |
| `NOVEL_AI_CODEX_SESSION_EXECUTABLE` | 官方 Codex CLI 路径或命令名 |
| `NOVEL_AI_CODEX_SESSION_DEFAULT_MODEL` | Codex 会话默认模型 |
| `NOVEL_AI_CODEX_SESSION_TIMEOUT_SECONDS` | 单次 Codex 生成超时 |
| `NOVEL_AI_CODEX_SESSION_AUTH_TIMEOUT_SECONDS` | 登录状态检查超时 |
| `NOVEL_AI_DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `NOVEL_AI_DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `NOVEL_AI_DEEPSEEK_DEFAULT_MODEL` | DeepSeek 默认模型 |
| `NOVEL_AI_MODEL_REQUEST_TIMEOUT_SECONDS` | 单次 HTTP 超时 |

密钥只从运行环境读取，Pydantic 使用秘密类型承载；能力 API 和日志不得输出密钥。Codex 子进程使用白名单环境变量，显式剥离 OpenAI/DeepSeek API Key、数据库连接串及其他应用秘密，确保订阅测试不会静默退化成 API Key 调用。每次生成前执行 `codex login status`，只有明确的 ChatGPT 登录状态才继续。

Codex 生成固定使用：临时空工作目录、`read-only` 沙箱、`never` 审批、ephemeral 会话、忽略用户配置、关闭 Git 仓库要求。这样不让项目 `AGENTS.md`、用户插件、MCP 或工作区文件混入小说提示上下文。模型若仍尝试调用内置工具，事件门禁会拒绝该结果。

## 7. 测试策略

默认测试使用 `httpx.MockTransport` 或假的 Codex 子进程 runner，不访问网络、不消耗 token。覆盖严格 schema 请求、reasoning 隔离、截断、空/错误结构、429 归一化、ChatGPT 登录限定、子进程环境秘密剥离、工具事件拒绝和本地 schema 二次校验。真实 Codex 会话 smoke test 必须由开发者显式运行，不得进入默认 CI。

## 8. 官方参考

- [OpenAI 模型与 Responses API 建议](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI 模型目录](https://developers.openai.com/api/docs/models)
- [OpenAI Developer Community](https://developers.openai.com/community)（展示 Codex app-server/harness 生态，不作为生产 SLA 或通用 API 授权依据）
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [DeepSeek Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)
