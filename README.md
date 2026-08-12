# Novel AI

面向长篇网络小说创作的、以结构化记忆和确定性工作流为核心的大模型辅助系统。

当前已完成第一条后端基础纵切：

- 版本化核心提示词目录、变量契约、内容指纹和 JSON Schema 校验；
- 正文严格输出包、传输完成检查、确定性纯净度扫描和独立语义审校契约；
- 不可变 artifact、输入指纹、依赖失效、工作流状态机和唯一物品归属投影；
- FastAPI 应用、SQLAlchemy 模型、Alembic 首版迁移、PostgreSQL JSONB 与 pgvector 基础；
- 章节工作流 v1 的可恢复步骤定义及单元测试。
- OpenAI Responses API、DeepSeek Chat Completions，以及本地测试专用 Codex 会话的统一模型网关。
- 可真实操作的本地写作工作台：作品主线/大纲/设定总览、章节目录、Markdown 正文、不可变版本、模型候选、人工发布。

## 本地启动

要求 Python 3.12+ 与 Docker。PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m novel_ai.main
```

服务默认监听 `http://127.0.0.1:8000`，健康检查为
`GET /api/v1/health`，提示词元数据为 `GET /api/v1/prompt-definitions`。

浏览器打开 [http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/) 进入写作工作台。当前本地数据库已经可以保存作品、章节任务和 Markdown 正文；章节模型生成在独立进程中执行，页面可持续显示步骤状态。每次保存都会产生不可变版本，模型生成结果需要人工确认后才能发布。

默认章节目标为 2,500 字，但它是创作目标而非机械配额：首稿小幅偏差可以直接进入待审，低于目标 75% 才触发至多一次质量优先的自然拓写；只有低于 50% 或高于 170% 的极端结果会被拒绝。生成后续章节时会加载前章的当前工作稿，即使前章尚未发布，也不会无上下文地跳过前章悬念。

作品规划支持“逐项填写 / 一句话生成”切换。作者可以手工编辑每个字段，也可以只写一句核心创意，让大纲助手从头生成简介、核心卖点、主题、全文主线、三卷大纲、结局约束、故事圣经、文风和禁写规则；生成后自动回到逐项编辑模式。候选先保存在当前浏览器会话中，可反复切换和编辑；点击“保存规划”后才成为作品正式设定。

正文热数据存放在 PostgreSQL 不可变 artifact 中，章节目录不会读取正文；打开某章才加载其当前版本。供应商原始响应以内容哈希寻址并压缩保存到 `.novel_ai_objects/`，不进入 Git。详细设计见 [本地写作工作台](docs/WRITING_WORKSPACE.md)。

## 模型供应商

当前支持：

- `openai`：使用 Responses API；`chatgpt` 是该供应商的输入别名，不代表抓取 ChatGPT 网页或复用 ChatGPT 订阅；
- `openai_codex_session`：使用官方 Codex CLI 和本机 ChatGPT 登录，仅限单用户本地开发测试；别名为 `codex_session`；
- `deepseek`：使用 Chat Completions API 和 JSON Output。

常规供应商在 `.env` 中配置 `NOVEL_AI_OPENAI_API_KEY` 和/或 `NOVEL_AI_DEEPSEEK_API_KEY`。如需使用订阅测试通道，先安装官方 Codex CLI，执行 `codex login` 并选择 ChatGPT 登录，再设置 `NOVEL_AI_CODEX_SESSION_ENABLED=true`。该通道会拒绝 API Key 登录、生产环境和无法可靠映射的生成参数；它不提供 API 级 SLA、固定输出 token 上限或并发保证。

模型名称、base URL 和超时均可由 `.env` 覆盖。当前工作区可设置 `NOVEL_AI_DEFAULT_MODEL_PROVIDER=openai_codex_session` 将其作为默认测试路由；生产配置应改回 `openai` 或 `deepseek`。`GET /api/v1/model-providers` 只返回能力、默认路由与是否已配置，不返回密钥或登录凭据。`chatgpt` 仍指向正式 OpenAI API，只有显式选择 `openai_codex_session` 或 `codex_session` 才会使用订阅测试通道。

三条通道的结构化结果最终都会再经过本地 JSON Schema 校验。reasoning 或 Codex 事件流只进入隔离的原始审计响应，不会与最终文本拼接；Codex 执行中如果出现命令、文件修改或其他工具项，本次结果直接拒绝。

## 核心提示词

核心提示词位于 `src/novel_ai/prompts/catalog/<prompt_key>/v<version>/`。每个版本包含：

- `manifest.json`：角色、必需变量、输出模式和 schema 路径；
- `system.md`、`user.md`：独立模板，不在业务代码中内联；
- `schema.json`：结构化输出契约。

已发布目录不得原地修改；行为变化新建 `v2`。运行时记录 key、version 与由全部文件计算出的 SHA-256 指纹。

## 验证

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic check
```

## 设计文档

- [系统与项目设计](docs/PROJECT_DESIGN.md)
- [核心数据模型](docs/CORE_DATA_MODEL.md)
- [模型供应商接入](docs/PROVIDER_INTEGRATION.md)
- [本地写作工作台](docs/WRITING_WORKSPACE.md)
