# 本地写作工作台设计

> 状态：Implemented v0.1  
> 更新日期：2026-08-12

## 1. 目标

工作台用于作者真实操作当前纵切：创建作品和章节、编辑章节任务、手写或修改 Markdown 正文、请求模型生成候选、观察持久化步骤、审阅并发布规范版本。它不是仅展示静态样例的前端，所有作品数据均通过 FastAPI 读写 PostgreSQL。

## 2. 页面信息架构

页面采用三栏结构：

1. 顶部作品栏：作品切换、作品总览、新建作品、新建章节、保存状态；
2. 左侧章节栏：作品当前稿字数、章节数量、关键字与状态过滤、章节号、标题、状态、字数；
3. 中央正文区：章节标题、Markdown 编辑/预览、字数、修订号、正文状态；
4. 右侧任务栏：本章叙事任务、目标字数、模型生成步骤与存储说明。

“作品总览”以阅读视图集中展示核心卖点、主题、全文主线、分卷大纲、结局约束、故事圣经、文风契约和禁写规则；编辑入口仍使用同一个 PostgreSQL 作品版本。大纲助手的未采纳候选是例外：它们仅暂存在当前标签页的 `sessionStorage`，可以刷新、切换和载入编辑，但不是作品事实；作者点击“保存规划”后才通过带版本号的 API 写入 PostgreSQL。

小屏幕下章节栏变为上方可滚动区域，正文和任务栏纵向排列。正文编辑使用衬线中文字体和接近纸张的阅读背景，控制台元素保持低对比度，降低长时间写作的视觉负担。

## 3. 大文本读取策略

章节目录端点只返回元数据，不连接 `artifacts.content_text`：

```text
GET /works/{work_id}/chapters?after=<chapter_no>&limit=100
  → chapter_number/title/status/version/revision/char_count
```

打开一章后才调用：

```text
GET /chapters/{chapter_id}
  → 元数据 + 当前修订的一份正文
```

因此 100 章乃至更长作品的目录成本与正文总长度无关。目录使用 `(work_id, chapter_number)` 唯一索引和章节号 keyset 游标；不使用不断变慢的深分页 offset。浏览器只保存当前作品 ID 这一 UI 偏好，不保存作品或正文事实。

## 4. 正文存储和版本

```text
chapters.latest_revision_id
  → chapter_revisions.prose_artifact_id
    → artifacts.content_text
```

- `artifacts.content_text` 是唯一正文内容副本，使用 PostgreSQL `text`；
- 每次保存创建新的不可变 artifact 和 chapter revision，不更新旧正文；
- 内容先统一为 NFC 与 LF 换行，再计算 SHA-256；
- 相同作品内完全相同的正文可复用同一 artifact，但修订记录仍独立；
- `chapter_revisions.char_count` 是目录显示缓存，不代替正文；
- `latest_revision_id` 指向当前工作稿，`is_canonical` 标记已发布规范稿，两者可以暂时不同；
- 保存携带 `expected_revision_number`，过期页面会收到 409，不会覆盖新版本；
- 单章默认硬上限 200,000 字符，防止错误上传无限大文本。

PostgreSQL 会通过 TOAST 自动处理较大的 `text` 值。MVP 的约百章、百万字级正文继续留在 PostgreSQL，以获得正文与版本元数据的一致事务。目录查询绝不选择正文列。进入更大规模后，只有已归档且长期不访问的旧修订可迁移到对象存储；当前稿与规范稿仍留在数据库，迁移必须保留哈希和透明读取接口。

## 5. 原始响应对象存储

供应商原始响应不属于小说真相，也不与正文混存。开发环境使用 `.novel_ai_objects/` 下的内容寻址对象存储：

```text
provider-responses/<sha256-prefix>/<sha256>.json.gz
```

JSON 先按稳定键序列化再计算 SHA-256，并以确定性 gzip 原子写入；数据库 `generation_runs.raw_response_uri` 只保存 `objects://` URI。目录已被 Git 忽略。生产环境可以在保持 URI/哈希契约的前提下替换为 S3/R2。

## 6. 生成与发布

交互式生成纵切为：

```text
持久化任务 → 编译精确上下文 → 独立进程调用模型
→ 结构 Schema → 正文纯净度门禁 → 保存模型修订
→ 人工审阅 → 发布规范版本
```

模型调用在独立 Python worker 中执行。Web 进程只创建任务并返回 `202 + run_id`，页面每约 1.8 秒查询状态；即使 Codex CLI 运行几十秒，章节浏览和保存仍保持响应。worker 认领任务时写入执行者与租约过期时间；失败、未启动或租约过期的任务可以恢复，有效租约中的任务不能重复启动。worker 意外退出时任务仍保留在数据库，不会伪装为成功。

章节生成优先召回前两章的当前修订；前章未发布时以“当前未发布工作稿”身份进入上下文，而不是被错误忽略。最近一章获得主要上下文预算，末尾 1,200 字同时进入显式连续性契约，要求先处理仍在进行的动作、对话和在场人物，再推进本章任务。

目标字数用于引导篇幅而非机械验收。系统将 85%～120% 作为推荐区间，但小幅偏差仍可直接进入待审；首稿低于目标 75% 时携带程序实测字数执行至多一次自然拓写。拓写要求补足已有事件中的行动、对话和后果，不允许以重复或新设定凑字。最终仅使用 50%～170% 的宽松范围拦截明显截断或异常膨胀，行文流畅、叙事完整和语言质量优先。

模型候选通过传输与确定性纯净度门禁后只进入 `REVIEW`，不会自动成为规范正文。人工编辑会创建新的 `HUMAN` 修订。点击发布时再次执行确定性纯净度检查，在同一事务中切换 canonical revision、递增作品提交序列并写入 outbox。

当前交互纵切尚未把事件抽取、软审校和正式状态变更合并进发布事务；因此页面将模型结果称为“候选正文”，不能视为已经完成完整章节记忆提交。完整工作流仍按 `CHAPTER_WORKFLOW_V1` 逐步实现。

## 7. 大纲助手

大纲助手使用与章节生成相同的默认供应商路由和独立 worker。规划编辑页提供“逐项填写 / 一句话生成”切换：前者直接编辑全部正式字段，后者只接收一句核心创意并扩展出完整规划。新建作品也可选择“创建并生成大纲”。每次调用创建新的工作流、生成 nonce 和上下文快照，模型必须完整返回全部规划字段，不能只补空字段或沿用上版；最近候选的核心方向和内容哈希用于提示并检测完全重复结果。生成成功后界面自动切回逐项填写，作者检查和修改后必须显式保存，候选才会成为正式作品设定。

候选流程为：

```text
作者意图 → 独立完整生成 → 结构化候选 → 浏览器临时候选历史
→ 载入表单 → 作者任意编辑 → 保存规划 → 正式作品设置
```

服务端候选 artifact 仅用于运行审计，状态是 `REVIEW`，不会自动修改 `works.settings_json`。正式保存继续使用 `expected_version`，避免多个页面互相覆盖。

## 8. Markdown 安全边界

正文原样保存 Markdown。浏览器预览只实现标题、段落、引用、换行和分隔线等小说常用子集；所有源文本先进行 HTML 转义，不执行原始 HTML、脚本、链接协议或内联事件。模型正文提示仍禁止 Markdown 包装，手写正文可以使用标题。预览结果不是规范正文的另一个存储副本。

## 9. 当前 API

| 操作 | 接口 |
| --- | --- |
| 作品列表/创建/详情 | `GET/POST /api/v1/works`、`GET /api/v1/works/{id}` |
| 章节目录/创建 | `GET/POST /api/v1/works/{id}/chapters` |
| 章节详情/元数据 | `GET/PATCH /api/v1/chapters/{id}` |
| 保存 Markdown 正文 | `PUT /api/v1/chapters/{id}/content` |
| 版本目录/按需读取旧版 | `GET /api/v1/chapters/{id}/revisions`、`GET .../{revision_id}` |
| 创建生成任务 | `POST /api/v1/chapters/{id}/generation-runs` |
| 创建/读取大纲候选 | `POST /api/v1/works/{id}/planning-generation-runs`、`GET /api/v1/workflow-runs/{id}/planning-candidate` |
| 查询/恢复任务 | `GET /api/v1/workflow-runs/{id}`、`GET /api/v1/chapters/{id}/generation-runs/latest`、`POST .../resume` |
| 发布正文版本 | `POST /api/v1/chapters/{id}/revisions/{revision_id}/publish` |

创建生成任务要求 `Idempotency-Key`。元数据保存要求 `expected_version`，正文保存要求 `expected_revision_number`。
