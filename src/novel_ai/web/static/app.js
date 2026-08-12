const state = {
  works: [], work: null, chapters: [], chapter: null, nextAfter: null,
  dirtyContent: false, dirtyMeta: false, preview: true, generationRunId: null,
  statusFilter: "ALL", revisions: [], viewingRevisionId: null,
  planningRunId: null, planningCandidates: [], activePlanningCandidateId: null,
  planningMode: "manual",
};

const $ = (id) => document.getElementById(id);
const api = async (path, options = {}) => {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：${response.status}`);
  }
  return response.status === 204 ? null : response.json();
};

const escapeHtml = (value) => value.replace(/[&<>"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[char]);
const renderInline = (value) => value
  .replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
  .replace(/\*([^*]+)\*/g, "<em>$1</em>");
const renderMarkdown = (source) => {
  const safe = escapeHtml(source.replace(/\r\n?/g, "\n"));
  const blocks = safe.split(/\n{2,}/).map((block) => {
    if (/^###\s+/.test(block)) return `<h3>${renderInline(block.replace(/^###\s+/, ""))}</h3>`;
    if (/^##\s+/.test(block)) return `<h2>${renderInline(block.replace(/^##\s+/, ""))}</h2>`;
    if (/^#\s+/.test(block)) return `<h1>${renderInline(block.replace(/^#\s+/, ""))}</h1>`;
    if (/^---+$/.test(block.trim())) return "<hr>";
    if (/^&gt;\s?/.test(block)) return `<blockquote>${renderInline(block.replace(/^&gt;\s?/gm, "").replace(/\n/g,"<br>"))}</blockquote>`;
    if (/^(?:-\s+.+\n?)+$/.test(block)) return `<ul>${block.split("\n").map((line) => `<li>${renderInline(line.replace(/^-\s+/, ""))}</li>`).join("")}</ul>`;
    if (/^(?:\d+\.\s+.+\n?)+$/.test(block)) return `<ol>${block.split("\n").map((line) => `<li>${renderInline(line.replace(/^\d+\.\s+/, ""))}</li>`).join("")}</ol>`;
    return `<p>${renderInline(block.replace(/\n/g, "<br>"))}</p>`;
  });
  return blocks.join("");
};
const visibleChars = (text) => [...text].filter((char) => !/\s/.test(char)).length;
const formatNumber = (value) => new Intl.NumberFormat("zh-CN").format(value || 0);
const chapterNumeral = (number) => `第 ${number} 章`;
const statusText = { PLANNED:"未开始", DRAFT:"草稿", GENERATING:"生成中", REVIEW:"待审", COMMITTED:"已发布" };

function toast(message) {
  $("toast").textContent = message; $("toast").classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => $("toast").classList.remove("show"), 2400);
}
function setSaveState(text) { $("save-state").textContent = text; }
function overviewHtml(value) { return value?.trim() ? renderMarkdown(value) : `<p class="empty-copy">尚未填写</p>`; }
const planningCacheKey = (workId) => `novel-ai-planning-candidates:${workId}`;
const planningPremiseKey = (workId) => `novel-ai-planning-premise:${workId}`;
function loadPlanningCandidates(workId) {
  try { return JSON.parse(sessionStorage.getItem(planningCacheKey(workId)) || "[]"); }
  catch { return []; }
}
function cachePlanningCandidates(workId, candidates) {
  let retained = [...candidates];
  while (retained.length) {
    try { sessionStorage.setItem(planningCacheKey(workId), JSON.stringify(retained)); return retained; }
    catch { retained = retained.slice(1); }
  }
  return [];
}

async function loadWorks(preferredId = null) {
  state.works = await api("/works");
  const select = $("work-select");
  select.innerHTML = state.works.length ? state.works.map((work) => `<option value="${work.id}">${escapeHtml(work.title)}</option>`).join("") : `<option value="">尚无作品</option>`;
  const id = preferredId || localStorage.getItem("novel-ai-work") || state.works[0]?.id;
  if (id && state.works.some((work) => work.id === id)) { select.value = id; await selectWork(id); }
  else { showEmpty(); }
}

async function selectWork(id) {
  state.work = await api(`/works/${id}`); localStorage.setItem("novel-ai-work", id);
  state.planningCandidates = loadPlanningCandidates(id); state.activePlanningCandidateId = null;
  $("work-title").textContent = state.work.title;
  $("work-progress").textContent = `${formatNumber(state.work.totalCharCount)} 字`;
  $("work-meta").textContent = `${state.work.chapterCount} 章 · 提交序列 ${state.work.commitSequence}`;
  $("work-progress-bar").style.width = `${Math.min(100, state.work.totalCharCount / Math.max(1, state.work.chapterCount * 2500) * 100)}%`;
  state.chapters = []; state.nextAfter = null; await loadChapters(false);
  if (state.chapters.length) await selectChapter(state.chapters[0].id); else showEmpty();
}

async function loadChapters(append) {
  if (!state.work) return;
  const query = append && state.nextAfter ? `?after=${state.nextAfter}&limit=100` : "?limit=100";
  const page = await api(`/works/${state.work.id}/chapters${query}`);
  state.chapters = append ? [...state.chapters, ...page.items] : page.items;
  state.nextAfter = page.nextAfter; $("load-more").hidden = !state.nextAfter; renderChapterList();
}

function renderChapterList() {
  const query = $("chapter-search").value.trim().toLowerCase();
  const items = state.chapters.filter((chapter) => (state.statusFilter === "ALL" || chapter.status === state.statusFilter) && (!query || (chapter.title || "").toLowerCase().includes(query) || String(chapter.chapterNumber).includes(query)));
  $("chapter-list").innerHTML = items.map((chapter) => `<li class="chapter-item status-${chapter.status} ${state.chapter?.id === chapter.id ? "active" : ""}" data-id="${chapter.id}"><span class="chapter-index">${String(chapter.chapterNumber).padStart(2,"0")}</span><span class="chapter-copy"><strong>${escapeHtml(chapter.title || "无题")}</strong><small><span><i class="status-dot"></i>${statusText[chapter.status] || chapter.status}</span><span>${formatNumber(chapter.charCount)} 字</span></small></span></li>`).join("");
  document.querySelectorAll(".chapter-item").forEach((item) => item.addEventListener("click", () => selectChapter(item.dataset.id)));
}

async function selectChapter(id) {
  if ((state.dirtyContent || state.dirtyMeta) && !confirm("当前修改尚未保存，确定切换章节吗？")) return;
  state.chapter = await api(`/chapters/${id}`); state.dirtyContent = false; state.dirtyMeta = false;
  state.viewingRevisionId = state.chapter.latestRevisionId;
  $("empty-state").hidden = true; $("editor-view").hidden = false;
  $("chapter-number").textContent = chapterNumeral(state.chapter.chapterNumber);
  $("chapter-title").value = state.chapter.title || "";
  $("chapter-content").value = state.chapter.content || "";
  $("generation-brief").value = state.chapter.generationBrief || "";
  $("target-count").value = state.chapter.targetCharCount;
  $("publish-button").disabled = !state.chapter.latestRevisionId || state.chapter.isCanonical;
  await loadRevisionHistory(); await loadLatestGeneration(); updateEditor(); renderChapterList(); setSaveState("已载入");
}

async function loadLatestGeneration() {
  if (!state.chapter) return;
  const run = await api(`/chapters/${state.chapter.id}/generation-runs/latest`);
  if (!run || run.status === "COMPLETED") {
    state.generationRunId = null; $("generation-card").hidden = true; return;
  }
  state.generationRunId = run.runId; $("generation-card").hidden = false; renderGeneration(run);
  if (["PLANNED", "RUNNING"].includes(run.status)) setTimeout(() => pollGeneration(run.runId), 1800);
}

async function loadRevisionHistory() {
  if (!state.chapter) return;
  const page = await api(`/chapters/${state.chapter.id}/revisions?limit=12`);
  state.revisions = page.items; renderRevisionHistory();
}
function renderRevisionHistory() {
  $("revision-list").innerHTML = state.revisions.length ? state.revisions.map((revision) => `<button class="revision-item ${state.viewingRevisionId === revision.id ? "active" : ""}" type="button" data-id="${revision.id}"><span>v${revision.revisionNumber}</span><div><strong>${revision.source === "MODEL" ? "模型候选" : "人工版本"}</strong><small>${formatNumber(revision.charCount)} 字 · ${new Date(revision.createdAt).toLocaleString("zh-CN", {month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"})}</small></div><i>${revision.isCanonical ? "已发布" : ""}</i></button>`).join("") : `<small>保存正文后将在这里形成版本。</small>`;
  document.querySelectorAll(".revision-item").forEach((item) => item.addEventListener("click", () => loadHistoricalRevision(item.dataset.id)));
}
async function loadHistoricalRevision(revisionId) {
  if (state.dirtyContent && !confirm("正文修改尚未保存，确定加载历史版本吗？")) return;
  try {
    const revision = await api(`/chapters/${state.chapter.id}/revisions/${revisionId}`);
    $("chapter-content").value = revision.content; state.viewingRevisionId = revision.id;
    state.dirtyContent = revision.id !== state.chapter.latestRevisionId;
    setSaveState(state.dirtyContent ? "旧版已载入，待另存" : "已载入当前版"); updateEditor(); renderRevisionHistory();
  } catch (error) { toast(error.message); }
}

function showEmpty() { $("editor-view").hidden = true; $("empty-state").hidden = false; }
function updateEditor() {
  if (!state.chapter) return;
  const content = $("chapter-content").value;
  $("markdown-preview").innerHTML = renderMarkdown(content);
  $("chapter-content").hidden = state.preview; $("markdown-preview").hidden = !state.preview;
  $("toggle-preview").textContent = state.preview ? "编辑" : "预览";
  $("char-count").textContent = `${formatNumber(visibleChars(content))} 字`;
  const historical = state.viewingRevisionId && state.viewingRevisionId !== state.chapter.latestRevisionId;
  const viewed = state.revisions.find((revision) => revision.id === state.viewingRevisionId);
  $("revision-label").textContent = historical && viewed ? `正在查看版本 ${viewed.revisionNumber}` : state.chapter.latestRevisionNumber ? `版本 ${state.chapter.latestRevisionNumber} · ${state.chapter.latestRevisionSource === "MODEL" ? "模型" : "人工"}` : "尚无版本";
  $("chapter-status").textContent = statusText[state.chapter.status] || state.chapter.status;
  $("brief-state").textContent = state.dirtyMeta ? "待保存" : "已同步";
  $("publish-button").disabled = Boolean(historical) || !state.chapter.latestRevisionId || state.chapter.isCanonical;
}

async function saveAll() {
  if (!state.chapter) return false;
  setSaveState("保存中…");
  try {
    if (state.dirtyMeta) {
      state.chapter = await api(`/chapters/${state.chapter.id}`, { method:"PATCH", body:JSON.stringify({ expectedVersion:state.chapter.version, title:$("chapter-title").value, generationBrief:$("generation-brief").value, targetCharCount:Number($("target-count").value) }) });
      state.dirtyMeta = false;
    }
    if (state.dirtyContent) {
      state.chapter = await api(`/chapters/${state.chapter.id}/content`, { method:"PUT", body:JSON.stringify({ content:$("chapter-content").value, expectedRevisionNumber:state.chapter.latestRevisionNumber }) });
      state.dirtyContent = false;
    }
    state.viewingRevisionId = state.chapter.latestRevisionId; await refreshListAndWork(); await loadRevisionHistory(); updateEditor(); setSaveState("已保存"); toast("新版本已保存"); return true;
  } catch (error) { setSaveState("保存失败"); toast(error.message); return false; }
}

async function refreshListAndWork() {
  if (!state.work) return;
  state.work = await api(`/works/${state.work.id}`);
  const page = await api(`/works/${state.work.id}/chapters?limit=100`); state.chapters = page.items; state.nextAfter = page.nextAfter;
  $("work-progress").textContent = `${formatNumber(state.work.totalCharCount)} 字`; $("work-meta").textContent = `${state.work.chapterCount} 章 · 提交序列 ${state.work.commitSequence}`;
  renderChapterList();
}

async function createWorkFromDialog(event) {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault(); const shouldGenerate = event.submitter?.value === "generate";
  const planningIntent = $("new-work-intent").value.trim();
  if (shouldGenerate && !planningIntent) {
    toast("请先输入一句话创意，再生成完整大纲");
    $("new-work-intent").focus();
    return;
  }
  try {
    const work = await api("/works", { method:"POST", body:JSON.stringify({ title:$("new-work-title").value, description:$("new-work-description").value }) });
    $("work-dialog").close(); $("work-form").reset(); await loadWorks(work.id); openWorkSettings(shouldGenerate ? "ai" : "manual");
    $("planning-intent").value = planningIntent;
    sessionStorage.setItem(planningPremiseKey(work.id), planningIntent);
    toast(shouldGenerate ? "作品已创建，正在生成整套规划" : "作品已创建，可继续编辑规划");
    if (shouldGenerate) generatePlanningCandidate();
  } catch (error) { toast(error.message); }
}
async function createChapterFromDialog(event) {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault(); if (!state.work) return;
  try {
    const chapter = await api(`/works/${state.work.id}/chapters`, { method:"POST", body:JSON.stringify({ title:$("new-chapter-title").value, generationBrief:$("new-chapter-brief").value, targetCharCount:Number($("new-chapter-target").value) }) });
    $("chapter-dialog").close(); $("chapter-form").reset(); $("new-chapter-target").value = 2500; await refreshListAndWork(); await selectChapter(chapter.id); toast("章节已创建");
  } catch (error) { toast(error.message); }
}
function openWorkOverview() {
  if (!state.work) return toast("请先创建作品");
  const settings = state.work.settings || {};
  $("overview-title").textContent = state.work.title;
  $("overview-description").textContent = state.work.description || "尚未填写作品简介";
  $("overview-pitch").innerHTML = overviewHtml(settings.core_pitch);
  $("overview-themes").innerHTML = overviewHtml(settings.themes);
  $("overview-main-plot").innerHTML = overviewHtml(settings.main_plot);
  $("overview-outline").innerHTML = overviewHtml(settings.outline_markdown);
  $("overview-ending").innerHTML = overviewHtml(settings.ending_constraints);
  $("overview-bible").innerHTML = overviewHtml(settings.story_bible);
  $("overview-style").innerHTML = overviewHtml(settings.style_contract);
  $("overview-forbidden").innerHTML = overviewHtml(settings.forbidden_content);
  $("overview-dialog").showModal();
}
function setPlanningMode(mode) {
  const normalized = mode === "ai" ? "ai" : "manual";
  state.planningMode = normalized;
  $("planning-manual-panel").hidden = normalized !== "manual";
  $("planning-ai-panel").hidden = normalized !== "ai";
  $("planning-mode-manual").classList.toggle("active", normalized === "manual");
  $("planning-mode-ai").classList.toggle("active", normalized === "ai");
  $("planning-mode-manual").setAttribute("aria-pressed", String(normalized === "manual"));
  $("planning-mode-ai").setAttribute("aria-pressed", String(normalized === "ai"));
  $("save-planning-button").disabled = normalized !== "manual";
}

function openWorkSettings(mode = "manual") {
  if (!state.work) return toast("请先创建作品");
  if ($("overview-dialog").open) $("overview-dialog").close();
  const settings = state.work.settings || {};
  $("settings-description").value = state.work.description || "";
  $("settings-pitch").value = settings.core_pitch || "";
  $("settings-themes").value = settings.themes || "";
  $("settings-main-plot").value = settings.main_plot || "";
  $("settings-outline").value = settings.outline_markdown || "";
  $("settings-ending").value = settings.ending_constraints || "";
  $("settings-bible").value = settings.story_bible || "";
  $("settings-style").value = settings.style_contract || "";
  $("settings-forbidden").value = settings.forbidden_content || "";
  $("planning-intent").value = sessionStorage.getItem(planningPremiseKey(state.work.id)) || "";
  state.planningCandidates = loadPlanningCandidates(state.work.id); renderPlanningCandidates();
  setPlanningMode(mode);
  $("settings-dialog").showModal();
}

function renderPlanningCandidates() {
  const container = $("planning-candidate-list");
  if (!state.planningCandidates.length) { container.innerHTML = "<small>尚无候选</small>"; return; }
  container.innerHTML = [...state.planningCandidates].reverse().map((candidate, index) => `<button class="candidate-item ${state.activePlanningCandidateId === candidate.candidateId ? "active" : ""}" type="button" data-candidate-id="${escapeHtml(candidate.candidateId)}"><strong>候选 ${state.planningCandidates.length - index} · ${escapeHtml(candidate.corePitch.slice(0, 28))}</strong><small>${new Date(candidate.generatedAt).toLocaleString("zh-CN", {month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"})}</small><small>${escapeHtml(candidate.provider || "模型生成")} · 点击载入编辑</small></button>`).join("");
  document.querySelectorAll(".candidate-item").forEach((item) => item.addEventListener("click", () => {
    const candidate = state.planningCandidates.find((entry) => entry.candidateId === item.dataset.candidateId);
    if (candidate) applyPlanningCandidate(candidate);
  }));
}

function applyPlanningCandidate(candidate) {
  $("settings-description").value = candidate.description || "";
  $("settings-pitch").value = candidate.corePitch || "";
  $("settings-themes").value = candidate.themes || "";
  $("settings-main-plot").value = candidate.mainPlot || "";
  $("settings-outline").value = candidate.outlineMarkdown || "";
  $("settings-ending").value = candidate.endingConstraints || "";
  $("settings-bible").value = candidate.storyBible || "";
  $("settings-style").value = candidate.styleContract || "";
  $("settings-forbidden").value = candidate.forbiddenContent || "";
  state.activePlanningCandidateId = candidate.candidateId; renderPlanningCandidates();
  setPlanningMode("manual");
  toast("完整大纲已载入，请逐项校订后保存");
}

async function generatePlanningCandidate() {
  if (!state.work) return;
  const workId = state.work.id;
  const button = $("generate-planning-button"); button.disabled = true;
  $("planning-generation-state").hidden = false;
  $("planning-generation-title").textContent = "正在独立生成整套规划";
  $("planning-generation-detail").textContent = "本次会完整重写全部规划字段，不会覆盖正式作品。";
  const explicitIntent = $("planning-intent").value.trim();
  if (!explicitIntent) {
    button.disabled = false; $("planning-generation-state").hidden = true;
    toast("请先输入一句话创意"); $("planning-intent").focus(); return;
  }
  const previous = loadPlanningCandidates(workId);
  try {
    const handle = await api(`/works/${workId}/planning-generation-runs`, {
      method:"POST", headers:{"Idempotency-Key":crypto.randomUUID()},
      body:JSON.stringify({
        authorIntent:explicitIntent,
        priorCorePitches:previous.slice(-5).map((item) => item.corePitch),
        priorCandidateHashes:previous.slice(-10).map((item) => item.contentHash),
      }),
    });
    state.planningRunId = handle.runId; pollPlanningGeneration(handle.runId, workId);
  } catch (error) {
    button.disabled = false; $("planning-generation-title").textContent = "生成失败";
    $("planning-generation-detail").textContent = error.message; toast(error.message);
  }
}

async function pollPlanningGeneration(runId, workId) {
  try {
    const run = await api(`/workflow-runs/${runId}`);
    if (state.work?.id === workId) $("planning-generation-detail").textContent = run.provider ? `${run.provider} · ${run.model || ""}` : "正在准备模型上下文……";
    if (["PLANNED","RUNNING"].includes(run.status)) return setTimeout(() => pollPlanningGeneration(runId, workId), 1800);
    if (state.work?.id === workId) $("generate-planning-button").disabled = false;
    if (run.status === "AWAITING_REVIEW") {
      const candidate = await api(`/workflow-runs/${runId}/planning-candidate`);
      candidate.generatedAt = new Date().toISOString(); candidate.provider = run.provider; candidate.model = run.model;
      const candidates = loadPlanningCandidates(workId).filter((item) => item.candidateId !== candidate.candidateId);
      const retained = cachePlanningCandidates(workId, [...candidates, candidate]);
      if (state.work?.id === workId) {
        state.planningCandidates = retained; applyPlanningCandidate(candidate);
        $("planning-generation-title").textContent = "新候选已生成";
        $("planning-generation-detail").textContent = "已载入编辑区；确认修改后请点击保存规划。";
      }
    } else if (state.work?.id === workId) {
      $("planning-generation-title").textContent = "生成失败";
      $("planning-generation-detail").textContent = run.error?.message || "生成失败，请重新点击生成";
      toast(run.error?.message || "大纲生成失败");
    }
  } catch (error) {
    if (state.work?.id === workId) {
      $("generate-planning-button").disabled = false;
      $("planning-generation-title").textContent = "生成失败"; $("planning-generation-detail").textContent = error.message; toast(error.message);
    }
  }
}
async function saveWorkSettings(event) {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  if (state.planningMode !== "manual") return toast("请先切换到逐项填写并检查生成结果");
  try {
    state.work = await api(`/works/${state.work.id}`, {method:"PATCH", body:JSON.stringify({
      expectedVersion:state.work.version,
      description:$("settings-description").value,
      corePitch:$("settings-pitch").value,
      themes:$("settings-themes").value,
      mainPlot:$("settings-main-plot").value,
      outlineMarkdown:$("settings-outline").value,
      endingConstraints:$("settings-ending").value,
      storyBible:$("settings-bible").value,
      styleContract:$("settings-style").value,
      forbiddenContent:$("settings-forbidden").value,
    })});
    $("settings-dialog").close(); openWorkOverview(); toast("作品规划与设定已保存");
  } catch (error) { toast(error.message); }
}

async function generateCandidate() {
  if (!state.chapter) return;
  if ((state.dirtyContent || state.dirtyMeta) && !(await saveAll())) return;
  $("generate-button").disabled = true; $("generation-card").hidden = false;
  try {
    const handle = await api(`/chapters/${state.chapter.id}/generation-runs`, { method:"POST", headers:{"Idempotency-Key": crypto.randomUUID()}, body:"{}" });
    state.generationRunId = handle.runId; pollGeneration(handle.runId);
  } catch (error) { $("generate-button").disabled = false; toast(error.message); }
}
async function pollGeneration(runId) {
  try {
    const run = await api(`/workflow-runs/${runId}`);
    if (runId !== state.generationRunId) return;
    renderGeneration(run);
    if (["PLANNED","RUNNING"].includes(run.status)) return setTimeout(() => pollGeneration(runId), 1800);
    $("generate-button").disabled = false;
    if (run.status === "AWAITING_REVIEW") { await selectChapter(state.chapter.id); toast("候选正文已生成，请审阅后发布"); }
    else if (run.status === "FAILED") toast(run.error?.message || "生成失败，可查看步骤后重试");
  } catch (error) { $("generate-button").disabled = false; toast(error.message); }
}
function renderGeneration(run) {
  $("generation-title").textContent = run.status === "AWAITING_REVIEW" ? "候选待审" : run.status === "FAILED" ? "生成失败" : "正在生成";
  $("generation-detail").textContent = run.error?.message || (run.provider ? `${run.provider} · ${run.model || ""}` : "正在准备上下文……");
  $("generation-steps").innerHTML = run.steps.map((step) => `<span class="${step.status === "SUCCEEDED" ? "done" : step.status === "FAILED" ? "failed" : ""}">${step.status === "SUCCEEDED" ? "✓" : step.status === "RUNNING" ? "●" : "○"} ${escapeHtml(step.key)}</span>`).join("");
  const expired = run.status === "RUNNING" && run.leaseExpiresAt && new Date(run.leaseExpiresAt) <= new Date();
  $("resume-generation").hidden = !(run.status === "FAILED" || run.status === "PLANNED" || expired);
}
async function resumeGeneration() {
  if (!state.generationRunId) return;
  $("resume-generation").disabled = true;
  try {
    const handle = await api(`/workflow-runs/${state.generationRunId}/resume`, {method:"POST", body:"{}"});
    renderGeneration({...handle, steps:[], provider:null, model:null, error:null, leaseExpiresAt:null});
    pollGeneration(handle.runId);
  } catch (error) { toast(error.message); }
  finally { $("resume-generation").disabled = false; }
}
async function publishCurrent() {
  if (!state.chapter?.latestRevisionId) return;
  if ((state.dirtyContent || state.dirtyMeta) && !(await saveAll())) return;
  if (!confirm("发布后该版本会成为规范正文。继续吗？")) return;
  try { state.chapter = await api(`/chapters/${state.chapter.id}/revisions/${state.chapter.latestRevisionId}/publish`, {method:"POST", body:"{}"}); await refreshListAndWork(); await loadRevisionHistory(); updateEditor(); $("publish-button").disabled = true; toast("章节已发布"); }
  catch (error) { toast(error.message); }
}

$("new-work-button").addEventListener("click", () => $("work-dialog").showModal());
$("work-settings-button").addEventListener("click", openWorkOverview);
$("overview-edit-button").addEventListener("click", () => openWorkSettings("manual"));
$("planning-mode-manual").addEventListener("click", () => setPlanningMode("manual"));
$("planning-mode-ai").addEventListener("click", () => setPlanningMode("ai"));
$("generate-planning-button").addEventListener("click", generatePlanningCandidate);
$("planning-intent").addEventListener("input", () => {
  if (state.work) sessionStorage.setItem(planningPremiseKey(state.work.id), $("planning-intent").value);
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $(button.dataset.closeDialog).close()));
$("new-chapter-button").addEventListener("click", () => state.work ? $("chapter-dialog").showModal() : $("work-dialog").showModal());
$("empty-create").addEventListener("click", () => state.work ? $("chapter-dialog").showModal() : $("work-dialog").showModal());
$("work-form").addEventListener("submit", createWorkFromDialog); $("chapter-form").addEventListener("submit", createChapterFromDialog);
$("settings-form").addEventListener("submit", saveWorkSettings);
$("work-select").addEventListener("change", (event) => selectWork(event.target.value));
$("chapter-search").addEventListener("input", renderChapterList); $("load-more").addEventListener("click", () => loadChapters(true));
$("status-filter").addEventListener("click", () => {
  const filters = ["ALL", "REVIEW", "DRAFT", "COMMITTED", "GENERATING", "PLANNED"];
  state.statusFilter = filters[(filters.indexOf(state.statusFilter) + 1) % filters.length];
  $("status-filter").textContent = state.statusFilter === "ALL" ? "全部状态" : statusText[state.statusFilter];
  renderChapterList();
});
$("collapse-rail").addEventListener("click", () => $("workspace").classList.toggle("rail-collapsed"));
$("toggle-preview").addEventListener("click", () => { state.preview = !state.preview; updateEditor(); });
$("chapter-content").addEventListener("input", () => { state.dirtyContent = true; setSaveState("未保存"); updateEditor(); });
["chapter-title","generation-brief","target-count"].forEach((id) => $(id).addEventListener("input", () => { state.dirtyMeta = true; setSaveState("未保存"); updateEditor(); }));
$("save-button").addEventListener("click", saveAll); $("generate-button").addEventListener("click", generateCandidate); $("publish-button").addEventListener("click", publishCurrent);
$("resume-generation").addEventListener("click", resumeGeneration);
document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveAll(); } });
window.addEventListener("beforeunload", (event) => { if (state.dirtyContent || state.dirtyMeta) { event.preventDefault(); event.returnValue = ""; } });

loadWorks().catch((error) => toast(error.message));
