/* DOMjudge 9.0.1 team UI adaptation, GPL-2.0-or-later. See docs/UI_UPSTREAM.md. */
"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const MAX_SOURCE_BYTES = 512 * 1024;
  const INTENTS_KEY = "vpUiSubmissionIntents";
  const ACTIVE_KEY = "vpUiActiveSession";
  // Application.submit raises the account/session errors below before
  // Ledger.begin_operation and QojClient.submit. A known failure there must
  // not leave an orphan local "unknown" that blocks retry after re-login.
  // Generic provider, internal and transport errors remain uncertain.
  const DEFINITIVE_REJECTION_CODES = new Set([
    "VALIDATION_ERROR", "SUBMISSION_REJECTED", "LOGIN_REQUIRED",
    "ACCOUNT_UNKNOWN", "ACCOUNT_MISMATCH", "SESSION_NOT_RUNNING",
  ]);
  const state = {
    connected: false, sessions: [], session: null, contest: null, submissions: [],
    forms: new Map(), generation: 0, refreshPromise: null, refreshSession: null,
    intents: [], setupContest: null, submitting: false, formGeneration: 0,
    confirmPayload: null, reconcileOperation: null, lastError: null,
  };
  const modals = {};

  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) result.textContent = String(text);
    return result;
  }
  function icon(name) {
    const result = node("i", "fas fa-" + name);
    result.setAttribute("aria-hidden", "true");
    return result;
  }
  function button(label, className, action, iconName) {
    const result = node("button", className);
    result.type = "button";
    if (iconName) result.append(icon(iconName), " ");
    result.append(label);
    result.addEventListener("click", action);
    return result;
  }
  function showMessage(target, message, kind = "danger") {
    target.className = "alert alert-" + kind + (target.id === "notice" ? " mt-3" : "");
    target.textContent = message;
    target.classList.remove("d-none");
  }
  function hideMessage(target) { target.classList.add("d-none"); target.textContent = ""; }
  function message(error) {
    if (error?.code === "LOGIN_REQUIRED") return "请先在同一个 Firefox 的 QOJ 页面完成登录，然后重新读取比赛。";
    if (error?.code === "QOJ_ERROR" && /\b403\b/.test(error.message || "")) return "QOJ 拒绝了请求（403）。请先在原站完成浏览器验证，然后重试。";
    return error?.message || String(error || "操作未完成，请稍后重试。");
  }
  function fail(error) {
    state.lastError = {code: error?.code || "UI_ERROR", message: message(error)};
    showMessage($("notice"), message(error));
  }
  function current(sessionId, generation) {
    return state.session?.sessionId === sessionId && state.generation === generation;
  }
  async function call(method, args = {}) {
    const response = await browser.runtime.sendMessage({type: "vp.task", method, args});
    if (!response || response.ok !== true) {
      const error = new Error(response?.error?.message || "未连接到配套助手。请检查助手安装后重新打开页面。");
      error.code = response?.error?.code || "HELPER_UNAVAILABLE";
      throw error;
    }
    return response.result;
  }
  async function localGet(key) {
    const values = await browser.storage.local.get(key);
    return values[key];
  }
  async function persistIntents() {
    await browser.storage.local.set({[INTENTS_KEY]: state.intents});
  }
  async function changeIntent(operationId, patch) {
    const intent = state.intents.find(item => item.operationId === operationId);
    if (intent) Object.assign(intent, patch);
    await persistIntents();
  }
  function epoch(value) {
    if (value === undefined || value === null || value === "") return null;
    if (typeof value === "number") return value < 1e12 ? value * 1000 : value;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function formatDate(value) {
    const stamp = epoch(value);
    return stamp === null ? "—" : new Date(stamp).toLocaleString();
  }
  function formatElapsed(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    const seconds = Math.floor(Math.abs(Number(value)) / 1000);
    return (Number(value) < 0 ? "−" : "") + Math.floor(seconds / 3600) + ":" +
      String(Math.floor(seconds / 60) % 60).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  }
  function sessionState(session = state.session) {
    if (!session) return "none";
    if (session.state === "archived") return "archived";
    const start = epoch(session.startAt);
    if (start === null) return "prepared";
    return Date.now() - start >= session.durationMs ? "finished" : "running";
  }
  function canSubmit() { return Boolean(state.contest && sessionState() === "running" && !state.submitting); }
  function safeQojUrl(raw, fallback) {
    try {
      const value = new URL(raw);
      if (value.protocol === "https:" && value.hostname === "qoj.ac" && !value.username && !value.password) return value.href;
    } catch (_) { /* Ignore an invalid provider link. */ }
    return fallback;
  }
  function problemUrl(problem) {
    return safeQojUrl(problem.url, `https://qoj.ac/contest/${state.session.contestId}/problem/${problem.id}`);
  }
  function badge(label) { return node("span", "badge problem-badge", label || "?"); }
  function problemById(id) { return state.contest?.problems.find(item => String(item.id) === String(id)); }

  function renderNavigation() {
    const previous = state.session?.sessionId || "";
    $("session-select").replaceChildren();
    if (!state.sessions.length) $("session-select").append(new Option("No contest", ""));
    for (const session of state.sessions) {
      const title = session.title || "Contest " + session.contestId;
      $("session-select").append(new Option(title + (session.state === "archived" ? " · 已归档" : ""), session.sessionId));
    }
    $("session-select").value = previous;
    $("session-select").disabled = !state.sessions.length || state.submitting;
    $("new-session").disabled = !state.connected || state.submitting;
    $("empty-new-session").disabled = !state.connected;
    $("nav-scoreboard").disabled = !state.session;
    $("empty-state").hidden = Boolean(state.session) || !state.connected;
    $("contest-view").hidden = !state.session;
    renderClock();
  }
  function renderClock() {
    const session = state.session;
    if (!session) { $("timeleft").textContent = "no contest"; return; }
    const status = sessionState();
    const start = epoch(session.startAt);
    const elapsed = start === null ? 0 : Math.max(0, Date.now() - start);
    const remaining = Math.max(0, Number(session.durationMs) - elapsed);
    $("timeleft").textContent = status === "prepared" ? "not started" : status === "archived" ? "archived" : remaining ? formatElapsed(remaining) + " left" : "contest ended";
    const percentage = Math.min(100, Math.max(0, elapsed / Number(session.durationMs) * 100));
    $("contest-progress").style.width = percentage + "%";
    $("contest-progress").setAttribute("aria-valuenow", percentage.toFixed(1));
    $("session-state").textContent = {prepared: "已准备", running: "进行中", finished: "已结束", archived: "已归档"}[status];
    $("start-session").hidden = status !== "prepared";
    $("open-submit").disabled = !canSubmit();
    for (const item of document.querySelectorAll("[data-submit-problem]")) item.disabled = !canSubmit();
  }
  function renderSession() {
    const session = state.session;
    if (!session) return;
    $("contest-name").textContent = session.title || state.contest?.name || "Contest " + session.contestId;
    $("account-name").textContent = session.account || state.contest?.account || "请在 QOJ 登录";
    $("started-at").textContent = formatDate(session.startAt);
    $("qoj-contest-link").href = `https://qoj.ac/contest/${session.contestId}`;
    $("archive-session").disabled = session.state === "archived";
    $("sync-scoreboard").disabled = !session.ranklandUrl;
    $("rankland-status").textContent = session.ranklandUrl ? "已保存这场 VP 的榜单入口。" : "选择 RankLand 比赛后，在榜单设置中保存链接。";
    document.title = (session.title || "Contest " + session.contestId) + " — QOJ VP";
    renderClock();
  }
  function renderSummary() {
    const target = $("teamscoresummary");
    target.replaceChildren();
    if (!state.session || !state.contest) return;
    const table = node("table", "scoreboard vp-score-summary");
    const thead = node("thead");
    const header = node("tr", "scoreheader");
    header.append(node("th", "scoretn", state.session.account || state.contest.account || "This VP"), node("th", "vp-solved", "solved"));
    const body = node("tbody"), row = node("tr");
    row.append(node("td", "scoretn", state.session.title || state.contest.name));
    const progress = state.contest.problems.map(problem => {
      const attempts = state.submissions.filter(item => String(item.problemId) === String(problem.id) && item.state === "confirmed" &&
        typeof item.elapsedMs === "number" && Number.isFinite(item.elapsedMs) && item.elapsedMs >= 0 && item.elapsedMs < state.session.durationMs);
      const accepted = attempts.filter(item => item.verdict === "CORRECT").sort((a, b) => a.elapsedMs - b.elapsedMs)[0];
      const pending = attempts.some(item => item.pending);
      return {problem, attempts, accepted, pending};
    });
    row.append(node("td", "vp-solved", progress.filter(item => item.accepted).length));
    for (const {problem, attempts, accepted, pending} of progress) {
      header.append(node("th", "", problem.label));
      const cell = node("td", accepted ? "score_correct" : pending ? "score_pending" : attempts.length ? "score_incorrect" : "");
      const control = button("", "vp-problem-link", () => openSubmit(problem.id));
      control.dataset.submitProblem = problem.id;
      control.disabled = !canSubmit();
      control.setAttribute("aria-label", `${problem.label} — ${problem.name}，提交`);
      const value = node("div", "", accepted ? Math.floor(accepted.elapsedMs / 60000) : attempts.length ? "−" + attempts.length : "—");
      if (accepted) value.append(node("span", "", `${attempts.filter(item => item.elapsedMs <= accepted.elapsedMs).length} tries`));
      else if (pending) value.append(node("span", "", "pending"));
      control.append(value); cell.append(control); row.append(cell);
    }
    thead.append(header); body.append(row); table.append(thead, body); target.append(table);
  }
  function renderSubmissions() {
    const body = $("submissions-body"); body.replaceChildren();
    $("submissions-empty").hidden = Boolean(state.submissions.length);
    $("submissions-table").hidden = !state.submissions.length;
    const sorted = [...state.submissions].sort((a, b) => (epoch(b.submittedAt) || 0) - (epoch(a.submittedAt) || 0));
    for (const submission of sorted) {
      const row = node("tr", submission.pending ? "unseen" : "");
      if (submission.operationId) row.dataset.operationId = submission.operationId;
      if (submission.id) row.dataset.submissionId = submission.id;
      const time = node("td");
      const elapsed = submission.elapsedMs ?? (epoch(submission.submittedAt) !== null && epoch(state.session.startAt) !== null ? epoch(submission.submittedAt) - epoch(state.session.startAt) : null);
      time.append(node("span", "d-block px-1 py-1", formatElapsed(elapsed)));
      time.title = formatDate(submission.submittedAt);
      const problem = node("td", "probid"); problem.append(badge(submission.problemLabel));
      const language = node("td", "langid"); language.append(node("span", "d-block px-1 py-1", submission.language || "—"));
      const result = node("td");
      let text = submission.verdict || "UNKNOWN";
      if (submission.state === "unknown" || submission.state === "sending") text = "结果未确认";
      else if (submission.state === "rejected") text = "提交被拒绝";
      const css = text === "CORRECT" ? "sol_correct" : submission.pending || ["JUDGING", "UNKNOWN", "结果未确认"].includes(text) ? "sol_queued" : "sol_incorrect";
      const verdict = node("span", "sol " + css, text);
      verdict.title = submission.rawVerdict || text;
      result.append(node("span", "d-block px-1 py-1")); result.firstChild.append(verdict);
      const source = node("td");
      if (submission.id) {
        const link = node("a", "", "#" + submission.id);
        link.href = safeQojUrl(submission.url, "https://qoj.ac/submission/" + submission.id);
        link.target = "_blank"; link.rel = "noopener noreferrer"; source.append(link);
      } else if (submission.state === "unknown" && submission.operationId) {
        source.append(button("核对提交", "btn btn-outline-secondary btn-sm vp-reconcile", () => openReconcile(submission)));
      } else source.append(node("span", "small text-muted px-1", "—"));
      row.append(time, problem, language, result, source); body.append(row);
    }
    renderSummary();
  }
  function renderProblems() {
    const target = $("problems-list"); target.replaceChildren();
    if (!state.contest) return;
    $("problemset-title").textContent = state.contest.name + " problems";
    for (const problem of state.contest.problems) {
      const col = node("div", "col"), card = node("div", "card"), body = node("div", "card-body");
      const title = node("h2", "card-title"); title.append(badge(problem.label));
      body.append(title, node("h3", "card-subtitle mb-2 text-muted", problem.name));
      const actions = node("div", "text-center vp-problem-actions");
      const submit = button("Submit", "btn btn-success", () => openSubmit(problem.id), "cloud-upload-alt");
      submit.dataset.submitProblem = problem.id; submit.disabled = !canSubmit(); actions.append(submit);
      const links = node("div", "vp-problem-links d-flex flex-wrap gap-2 justify-content-center");
      const statement = node("a", "btn btn-secondary"); statement.append(icon("file-alt"), " statement"); statement.href = problemUrl(problem); statement.target = "_blank"; statement.rel = "noopener noreferrer";
      const pdf = button("PDF", "btn btn-secondary", () => downloadPdf(problem, pdf), "file-pdf"); pdf.dataset.pdfProblem = problem.id;
      const samples = button("samples", "btn btn-secondary", () => downloadSamples(problem, samples), "file-archive"); samples.dataset.samplesProblem = problem.id;
      links.append(statement, pdf, samples); actions.append(links);
      const status = node("p", "vp-problem-status text-muted mb-0"); status.id = "problem-status-" + problem.id; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
      body.append(actions, status); card.append(body); col.append(card); target.append(col);
    }
  }
  function route() {
    const problems = location.hash === "#problems" || location.hash === "#problemset";
    $("home-view").hidden = problems; $("problems-view").hidden = !problems;
    $("nav-home").classList.toggle("active", !problems);
    $("nav-problems").classList.toggle("active", problems);
    $(problems ? "nav-problems" : "nav-home").setAttribute("aria-current", "page");
    $(problems ? "nav-home" : "nav-problems").removeAttribute("aria-current");
  }

  async function listSessions(preferred) {
    const result = await call("list_sessions");
    state.sessions = result.sessions || [];
    const candidate = preferred || state.session?.sessionId || await localGet(ACTIVE_KEY);
    const chosen = state.sessions.find(item => item.sessionId === candidate) || state.sessions.find(item => item.state !== "archived") || state.sessions[0];
    if (chosen) await selectSession(chosen.sessionId);
    else { state.session = null; renderNavigation(); }
  }
  async function selectSession(sessionId) {
    if (state.submitting) return;
    const generation = ++state.generation;
    const session = await call("inspect_session", {sessionId});
    if (generation !== state.generation) return;
    state.session = session;
    state.contest = null; state.submissions = []; state.forms.clear();
    hideMessage($("history-warning")); hideMessage($("notice"));
    $("teamscoresummary").replaceChildren(); $("problems-list").replaceChildren();
    $("refresh-status").textContent = "正在读取比赛…";
    renderNavigation(); renderSession(); renderSubmissions(); route();
    await browser.storage.local.set({[ACTIVE_KEY]: sessionId});
    try {
      const contest = await call("qoj_contest", {contestId: state.session.contestId, sessionId});
      if (!current(sessionId, generation)) return;
      state.contest = contest;
      if (!Array.isArray(contest.problems)) throw new Error("比赛题表格式无法识别，请重新读取比赛。");
      renderSession(); renderProblems(); renderSummary(); renderClock();
      if (!contest.account) showMessage($("notice"), "尚未登录 QOJ。请在原站登录后刷新页面。", "warning");
    } catch (error) { if (current(sessionId, generation)) fail(error); }
    try { await refresh(false); await refresh(true); }
    catch (error) { if (current(sessionId, generation)) fail(error); }
  }
  async function refresh(refreshProvider = true) {
    if (!state.session || state.submitting) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    if (state.refreshPromise && state.refreshSession === sessionId) return state.refreshPromise;
    $("refresh-submissions").disabled = true;
    if (refreshProvider) $("refresh-status").textContent = "正在同步…";
    const promise = (async () => {
      const result = await call("qoj_submissions", {sessionId, refresh: refreshProvider});
      if (!current(sessionId, generation)) return;
      state.submissions = result.submissions || [];
      for (const submission of state.submissions) {
        const intent = state.intents.find(item => item.operationId === submission.operationId);
        if (intent && submission.state === "confirmed") Object.assign(intent, {state: "confirmed", submissionId: submission.id});
        if (intent && submission.state === "rejected") intent.state = "rejected";
      }
      await persistIntents();
      renderSubmissions();
      const coverage = result.coverage || {};
      if (coverage.warning || coverage.complete === false) showMessage($("history-warning"), coverage.warning || "部分提交历史尚未读取完整，下次刷新将继续核对。", "warning");
      else hideMessage($("history-warning"));
      $("refresh-status").textContent = refreshProvider ? "更新于 " + new Date().toLocaleTimeString() : "已读取保存的判定";
    })();
    state.refreshPromise = promise; state.refreshSession = sessionId;
    try { return await promise; }
    catch (error) {
      if (current(sessionId, generation)) $("refresh-status").textContent = "同步未完成；保留上次结果";
      throw error;
    } finally {
      if (state.refreshPromise === promise) { state.refreshPromise = null; state.refreshSession = null; }
      if (current(sessionId, generation)) $("refresh-submissions").disabled = false;
    }
  }

  function openSessionSetup() {
    state.setupContest = null; $("session-form").reset();
    $("prepare-session").disabled = true; hideMessage($("session-error")); hideMessage($("contest-preview"));
    modals.session.show();
  }
  function readContestId(value) {
    const input = value.trim();
    if (/^\d+$/.test(input)) return input;
    let url;
    try { url = new URL(input); } catch (_) { throw new Error("请输入 QOJ 比赛 ID 或比赛链接。"); }
    const match = url.pathname.match(/^\/contest\/(\d+)\/?$/);
    if (url.protocol !== "https:" || url.hostname !== "qoj.ac" || !match || url.username || url.password || url.hash) throw new Error("请输入 https://qoj.ac/contest/比赛ID 格式的链接。");
    return match[1];
  }
  async function loadSetupContest() {
    hideMessage($("session-error")); state.setupContest = null; $("prepare-session").disabled = true;
    $("load-contest").disabled = true;
    const entered = $("contest-input").value;
    try {
      const cid = readContestId(entered);
      showMessage($("contest-preview"), "正在读取比赛和登录账号…", "secondary");
      const contest = await call("qoj_contest", {contestId: cid});
      if ($("contest-input").value !== entered) return;
      if (!contest.account) throw new Error("请先在 Firefox 的 QOJ 页面登录，再点击读取比赛。");
      if (!Array.isArray(contest.problems) || !contest.problems.length) throw new Error("比赛题表为空，请检查原站参赛权限。");
      state.setupContest = contest;
      if (!$("session-title").value) $("session-title").value = contest.name;
      showMessage($("contest-preview"), `${contest.name} · ${contest.problems.length} problems · ${contest.account}`, "secondary");
      $("prepare-session").disabled = false;
    } catch (error) { hideMessage($("contest-preview")); showMessage($("session-error"), message(error)); }
    finally { $("load-contest").disabled = false; }
  }
  async function prepareSession(event) {
    event.preventDefault(); if (!state.setupContest) return;
    const source = state.setupContest;
    const durationMs = Number($("duration-input").value) * 60000;
    const started = $("start-input").value ? new Date($("start-input").value).getTime() : null;
    if (!Number.isFinite(durationMs) || durationMs <= 0) return;
    $("prepare-session").disabled = true; hideMessage($("session-error"));
    try {
      const args = {contestId: source.id, title: $("session-title").value.trim() || source.name,
        account: source.account, durationMs, ranklandUrl: $("rankland-input").value.trim() || undefined};
      if (started !== null) args.startAt = started;
      const session = await call("create_session", args);
      modals.session.hide(); await listSessions(session.sessionId);
      if (sessionState() === "prepared") showMessage($("notice"), "比赛已准备好。点击“开始本次 VP”记录开始时间。", "success");
    } catch (error) { showMessage($("session-error"), message(error)); }
    finally { $("prepare-session").disabled = !state.setupContest; }
  }
  async function startSession() {
    if (!state.session || !confirm("从现在开始本次 VP 的计时？")) return;
    $("start-session").disabled = true;
    try {
      state.session = await call("start_session", {sessionId: state.session.sessionId});
      const index = state.sessions.findIndex(item => item.sessionId === state.session.sessionId);
      if (index >= 0) state.sessions[index] = state.session;
      renderSession(); renderNavigation(); renderSummary();
      showMessage($("notice"), "VP 已开始。", "success");
    } catch (error) { fail(error); }
    finally { $("start-session").disabled = false; }
  }

  // File-size/time formatting is adapted directly from DOMjudge's domjudge.js.
  function humanReadableTimeDiff(seconds) {
    for (const [name, length] of [["years", 31536000], ["months", 2592000], ["days", 86400], ["hours", 3600], ["minutes", 60]]) {
      if (seconds / length >= 2) return Math.floor(seconds / length) + " " + name;
    }
    return Math.floor(Math.max(0, seconds)) + " seconds";
  }
  function humanReadableBytes(bytes) {
    for (const [name, length] of [["GB", 1073741824], ["MB", 1048576], ["KB", 1024]]) if (bytes / length >= 2) return Math.floor(bytes / length) + name;
    return Math.floor(bytes) + "B";
  }
  // The preferred aliases match qoj-submitter's choose_language exactly.
  function inferLanguage(filename, languages) {
    const ext = filename.split(".").pop().toLowerCase();
    const aliases = {cpp: "c++20", cc: "c++20", cxx: "c++20", "c++": "c++20", c: "c11", java: "java21", py: "python3", py3: "python3", kt: "kotlin", kts: "kotlin", rs: "rust"};
    const normalized = value => value.toLowerCase().replace(/[^a-z0-9+]/g, "");
    const desired = aliases[ext] || ext;
    const found = languages.filter(value => normalized(value) === normalized(desired));
    return found.length === 1 ? found[0] : "";
  }
  function resetConfirmation() {
    state.confirmPayload = null;
    for (const id of ["submit_problem_code", "submit_problem_problem"]) $(id).disabled = false;
    $("submit_problem_language").disabled = !$("submit_problem_language").options.length || !$("submit_problem_problem").value;
  }
  async function openSubmit(problemId) {
    if (!canSubmit()) { showMessage($("notice"), "请先开始一场正在进行的 VP，再提交代码。", "warning"); return; }
    $("submit-form").reset(); hideMessage($("submit-error")); hideMessage($("files_selected"));
    $("submit_problem_problem").replaceChildren(new Option("autodetect", ""));
    for (const problem of state.contest.problems) $("submit_problem_problem").append(new Option(problem.label + " - " + problem.name, problem.id));
    $("submit_problem_problem").value = problemId || "";
    $("submit_problem_language").replaceChildren(new Option("先选择题目", ""));
    $("submit_problem_language").disabled = true; $("language-status").textContent = "";
    $("submit-title").textContent = problemId ? "Submit problem " + problemById(problemId).label : "Submit";
    resetConfirmation(); modals.submit.show();
    if (problemId) await loadLanguages();
  }
  async function loadLanguages() {
    const problemId = $("submit_problem_problem").value;
    const generation = ++state.formGeneration, sessionId = state.session?.sessionId;
    $("submit_problem_language").replaceChildren(new Option(problemId ? "正在读取…" : "先选择题目", ""));
    $("submit_problem_language").disabled = true; $("language-status").textContent = "";
    if (!problemId) return;
    try {
      const key = sessionId + ":" + problemId;
      let form = state.forms.get(key);
      if (!form) { form = await call("qoj_problem_form", {sessionId, problemId}); state.forms.set(key, form); }
      if (generation !== state.formGeneration || state.session?.sessionId !== sessionId || $("submit_problem_problem").value !== problemId) return;
      const languages = form.languages || [];
      if (!languages.length) throw new Error("QOJ 未返回可用语言，请检查原站提交权限。");
      $("submit_problem_language").replaceChildren(new Option("autodetect", ""));
      for (const language of languages) $("submit_problem_language").append(new Option(language, language));
      $("submit_problem_language").disabled = false;
      const file = $("submit_problem_code").files[0];
      if (file) {
        const guessed = inferLanguage(file.name, languages);
        $("submit_problem_language").value = guessed;
        $("language-status").textContent = guessed ? "已按文件扩展名选择，可手动更改。" : "无法唯一推断语言，请手动选择。";
      }
    } catch (error) {
      if (generation === state.formGeneration) showMessage($("submit-error"), message(error));
    }
  }
  async function fileSelected() {
    resetConfirmation(); hideMessage($("submit-error"));
    const file = $("submit_problem_code").files[0]; if (!file) return;
    const details = $("files_selected"); details.replaceChildren();
    const list = node("ul");
    list.append(node("li", "", `${file.name}, size ${humanReadableBytes(file.size)}, last modified ${humanReadableTimeDiff((Date.now() - file.lastModified) / 1000)} ago`));
    details.append(list); details.classList.remove("d-none");
    if (file.size === 0 || file.size > MAX_SOURCE_BYTES) showMessage($("submit-error"), file.size === 0 ? "源文件为空，请检查选择的文件。" : "源文件超过 512 KiB，请检查选择的文件。");
    else if (Date.now() - file.lastModified > 5 * 60 * 1000) details.append(node("p", "text-warning-emphasis mt-2 mb-0", "None of the selected files have been recently modified."));
    // As in DOMjudge: only infer while the select is still on autodetect.
    if (!$("submit_problem_problem").value) {
      const stem = file.name.replace(/\.[^.]*$/, "").toUpperCase();
      const candidate = state.contest.problems.find(problem => problem.label.toUpperCase() === stem);
      if (candidate) { $("submit_problem_problem").value = candidate.id; await loadLanguages(); }
    } else if (!$("submit_problem_language").value) {
      const languages = [...$("submit_problem_language").options].map(option => option.value).filter(Boolean);
      $("submit_problem_language").value = inferLanguage(file.name, languages);
    }
  }
  function bytesBase64(bytes) {
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    return btoa(binary);
  }
  async function prepareSubmission() {
    if (!$("submit-form").reportValidity()) return;
    const file = $("submit_problem_code").files[0];
    if (!file || !file.size || file.size > MAX_SOURCE_BYTES) throw new Error("请选择非空且不超过 512 KiB 的源文件。");
    const sessionId = state.session.sessionId;
    const problemId = $("submit_problem_problem").value, language = $("submit_problem_language").value;
    const problem = problemById(problemId);
    if (!problem || !language || !canSubmit()) throw new Error("请核对比赛、题目、语言以及 VP 状态。");
    const data = new Uint8Array(await file.arrayBuffer());
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))].map(value => value.toString(16).padStart(2, "0")).join("");
    const fingerprint = [sessionId, problemId, language, hash].join(":");
    const unresolved = state.intents.find(item => item.fingerprint === fingerprint && ["sending", "unknown"].includes(item.state));
    if (unresolved) throw new Error("这份源码已有结果未确认的提交。请先刷新历史，并使用“核对提交”关联原站记录。");
    if (state.session.sessionId !== sessionId) throw new Error("比赛已切换，请重新选择文件。");
    state.confirmPayload = {sessionId, problemId, problemLabel: problem.label, language, filename: file.name,
      contentsBase64: bytesBase64(data), operationId: crypto.randomUUID(), fingerprint, sourceSha256: hash};
  }
  async function submit(event) {
    event.preventDefault(); if (state.submitting) return;
    hideMessage($("submit-error"));
    if (!state.confirmPayload) {
      try {
        await prepareSubmission();
        if (!state.confirmPayload) return;
        const chosen = state.confirmPayload;
        const problem = problemById(chosen.problemId);
        // Preserve DOMjudge's original explicit browser confirmation step.
        const question = "Main source file: " + chosen.filename + "\n\n" +
          "Contest: " + (state.session.title || state.contest.name) + "\n" +
          "Account: " + (state.session.account || state.contest.account) + "\n" +
          "Problem: " + chosen.problemLabel + " - " + problem.name + "\n" +
          "Language: " + chosen.language + "\n\nMake submission?";
        if (!confirm(question)) { resetConfirmation(); return; }
      } catch (error) { showMessage($("submit-error"), message(error)); return; }
    }
    const payload = {...state.confirmPayload};
    if (!canSubmit() || payload.sessionId !== state.session.sessionId) { showMessage($("submit-error"), "VP 状态已改变，请重新确认。"); return; }
    state.submitting = true;
    $("submit-send").disabled = true; $("submit-cancel").disabled = true;
    for (const id of ["submit_problem_code", "submit_problem_problem", "submit_problem_language"]) $(id).disabled = true;
    $("submit-form").setAttribute("aria-busy", "true");
    renderNavigation();
    const intent = {operationId: payload.operationId, sessionId: payload.sessionId,
      fingerprint: payload.fingerprint, filename: payload.filename, problemId: payload.problemId,
      problemLabel: payload.problemLabel, language: payload.language, state: "sending", createdAt: Date.now()};
    state.intents.push(intent);
    let attempted = false, closeAfter = false;
    try {
      await persistIntents(); // Refuse to send if the stable intent cannot be saved.
      attempted = true;
      delete payload.fingerprint; delete payload.sourceSha256;
      const result = await call("qoj_submit", payload);
      const submission = result.submission || {};
      const status = result.state || submission.state;
      await changeIntent(payload.operationId, {state: status === "confirmed" ? "confirmed" : status === "rejected" ? "rejected" : "unknown", submissionId: submission.id || null});
      state.confirmPayload = null;
      closeAfter = true;
      if (status === "confirmed") showMessage($("notice"), `Submission #${submission.id} received. 正在更新判定。`, "success");
      else if (status === "rejected") showMessage($("notice"), result.error?.message || "QOJ 拒绝了本次提交，请核对原站提示。", "danger");
      else showMessage($("notice"), "提交结果未确认。已保留记录，请核对 QOJ 历史；不会自动重发源码。", "warning");
    } catch (error) {
      const rejected = !attempted || DEFINITIVE_REJECTION_CODES.has(error.code);
      await changeIntent(payload.operationId, {state: rejected ? "rejected" : "unknown"}).catch(() => {});
      state.confirmPayload = null;
      showMessage($("submit-error"), rejected ? message(error) : "提交结果未确认。请关闭弹窗后核对原站提交历史；不会自动重发源码。");
      resetConfirmation();
    } finally {
      state.submitting = false;
      $("submit-send").disabled = false; $("submit-cancel").disabled = false;
      $("submit-form").removeAttribute("aria-busy"); renderNavigation();
      resetConfirmation();
      if (closeAfter) modals.submit.hide();
      await refresh(true).catch(fail);
    }
  }

  function saveArchive(base64, filename, type = "application/zip") {
    const decoded = atob(base64), bytes = Uint8Array.from(decoded, value => value.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], {type}));
    const link = node("a"); link.href = url; link.download = filename.replace(/[\\/]/g, "_"); document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  async function downloadSamples(problem, control) {
    control.disabled = true; const sessionId = state.session.sessionId;
    const target = $("problem-status-" + problem.id); target.textContent = "正在下载 samples…";
    try {
      const result = await call("qoj_samples", {sessionId, problemLabel: problem.label});
      if (!result.zipBase64) throw new Error("样例包未返回，请稍后重新下载。");
      saveArchive(result.zipBase64, result.zipFilename || `samples-${problem.label}.zip`);
      if (state.session?.sessionId === sessionId) target.textContent = result.warnings?.length ? result.warnings.map(String).join("；") : "samples 已下载。";
    } catch (error) { if (state.session?.sessionId === sessionId) target.textContent = message(error); }
    finally { control.disabled = false; }
  }
  async function downloadPdf(problem, control) {
    control.disabled = true; const sessionId = state.session.sessionId;
    const target = $("problem-status-" + problem.id); target.textContent = "正在打开题面 PDF…";
    try {
      const result = await call("problem.pdf", {sessionId, problemId: problem.id});
      if (result?.pdfBase64) saveArchive(result.pdfBase64, result.filename || `problem-${problem.label}.pdf`, "application/pdf");
      if (state.session?.sessionId === sessionId) {
        if (result?.pdfBase64) target.textContent = "PDF 下载已开始。";
        else if (result?.method === "original-pdf") target.textContent = "已打开原始题面 PDF。";
        else if (result?.method === "firefox-save-as-pdf") {
          const statuses = {
            saved: "题面 PDF 已保存。", replaced: "题面 PDF 已保存并替换原文件。",
            canceled: "已取消保存 PDF。", not_saved: "PDF 未保存，可在题面页重新导出。",
            not_replaced: "PDF 未替换原文件，可重新选择保存位置。",
          };
          target.textContent = statuses[result.status] || "请在 Firefox 的保存窗口完成 PDF 导出。";
        } else target.textContent = result?.message || (result?.mode === "html" || result?.mode === "print" ? "原题面为 HTML，请在 Firefox 中保存为 PDF。" : "题面已打开。");
      }
    } catch (error) { if (state.session?.sessionId === sessionId) target.textContent = message(error); }
    finally { control.disabled = false; }
  }
  function openRanklandSettings() {
    if (!state.session) return;
    $("rankland-url").value = state.session.ranklandUrl || ""; hideMessage($("rankland-error")); modals.rankland.show();
  }
  async function openScoreboard() {
    if (!state.session?.ranklandUrl) { openRanklandSettings(); return; }
    try {
      const result = await call("rankland.open", {sessionId: state.session.sessionId});
      $("rankland-status").textContent = result?.message || "已打开这场 VP 保存的 RankLand 榜单。";
    } catch (error) { $("rankland-status").textContent = message(error); }
  }
  async function syncScoreboard() {
    $("sync-scoreboard").disabled = true;
    try {
      const result = await call("rankland.sync", {sessionId: state.session.sessionId});
      $("rankland-status").textContent = result?.message || "判定同步已检查。";
    } catch (error) { $("rankland-status").textContent = message(error); }
    finally { $("sync-scoreboard").disabled = !state.session?.ranklandUrl; }
  }
  function openReconcile(submission) {
    state.reconcileOperation = submission.operationId;
    $("reconcile-form").reset(); hideMessage($("reconcile-error"));
    $("reconcile-description").textContent = `${submission.filename || "源文件"} · ${submission.problemLabel || "?"} · ${submission.language || "?"}`;
    $("submission-candidates").replaceChildren();
    for (const candidate of state.submissions.filter(item => item.id && item.problemId === submission.problemId)) {
      $("submission-candidates").append(new Option(`#${candidate.id} · ${candidate.language || ""} · ${formatDate(candidate.submittedAt)}`, candidate.id));
    }
    modals.reconcile.show();
  }

  async function initialize() {
    for (const id of ["session", "submit", "rankland", "reconcile"]) modals[id] = new bootstrap.Modal($(id + "-modal"));
    window.addEventListener("hashchange", route); route();
    $("session-select").addEventListener("change", event => selectSession(event.target.value).catch(fail));
    $("new-session").addEventListener("click", openSessionSetup);
    $("empty-new-session").addEventListener("click", openSessionSetup);
    $("load-contest").addEventListener("click", loadSetupContest);
    $("contest-input").addEventListener("input", () => { state.setupContest = null; $("prepare-session").disabled = true; hideMessage($("contest-preview")); });
    $("session-form").addEventListener("submit", prepareSession);
    $("start-session").addEventListener("click", startSession);
    $("refresh-submissions").addEventListener("click", () => refresh(true).catch(fail));
    $("open-submit").addEventListener("click", () => openSubmit());
    $("submit-form").addEventListener("submit", submit);
    $("submit_problem_code").addEventListener("change", () => fileSelected().catch(error => showMessage($("submit-error"), message(error))));
    $("submit_problem_problem").addEventListener("change", () => { resetConfirmation(); loadLanguages().catch(fail); });
    $("submit_problem_language").addEventListener("change", () => { if (state.confirmPayload) resetConfirmation(); });
    $("submit-modal").addEventListener("hide.bs.modal", event => { if (state.submitting) event.preventDefault(); });
    $("nav-scoreboard").addEventListener("click", openScoreboard);
    $("open-scoreboard").addEventListener("click", openScoreboard);
    $("rankland-settings").addEventListener("click", openRanklandSettings);
    $("sync-scoreboard").addEventListener("click", syncScoreboard);
    $("rankland-form").addEventListener("submit", async event => {
      event.preventDefault(); const control = event.submitter; control.disabled = true;
      try {
        state.session = await call("update_session", {sessionId: state.session.sessionId, ranklandUrl: $("rankland-url").value.trim()});
        const index = state.sessions.findIndex(item => item.sessionId === state.session.sessionId);
        if (index >= 0) state.sessions[index] = state.session;
        renderSession(); modals.rankland.hide();
      } catch (error) { showMessage($("rankland-error"), message(error)); }
      finally { control.disabled = false; }
    });
    $("reconcile-form").addEventListener("submit", async event => {
      event.preventDefault(); const control = event.submitter; control.disabled = true;
      try {
        await call("qoj_reconcile", {sessionId: state.session.sessionId, operationId: state.reconcileOperation, submissionId: $("reconcile-id").value.trim()});
        await changeIntent(state.reconcileOperation, {state: "confirmed", submissionId: $("reconcile-id").value.trim()});
        modals.reconcile.hide(); await refresh(true); showMessage($("notice"), "已关联原站提交。", "success");
      } catch (error) { showMessage($("reconcile-error"), message(error)); }
      finally { control.disabled = false; }
    });
    $("archive-session").addEventListener("click", async () => {
      if (!state.session || !confirm("归档这场 VP？历史记录和榜单入口仍会保留。")) return;
      try { const session = await call("archive_session", {sessionId: state.session.sessionId}); await listSessions(session.sessionId); }
      catch (error) { fail(error); }
    });
    setInterval(renderClock, 1000);
    setInterval(() => {
      if (!document.hidden && state.session && !state.submitting && (sessionState() === "running" || state.submissions.some(item => item.pending))) refresh(true).catch(error => { $("refresh-status").textContent = "同步未完成：" + message(error); });
    }, 5000);
    try {
      const saved = await localGet(INTENTS_KEY); state.intents = Array.isArray(saved) ? saved : [];
      await call("hello"); state.connected = true; $("connection").classList.add("d-none");
      await listSessions();
    } catch (error) {
      state.lastError = {code: error.code || "HELPER_UNAVAILABLE", message: message(error)};
      showMessage($("connection"), message(error), "danger");
      const retry = button("重新连接", "btn btn-outline-danger btn-sm ms-2", () => location.reload()); $("connection").append(retry);
    }
    renderNavigation();
  }
  // Read-only state and normal refresh/select calls for the VM acceptance harness.
  // No method bypasses the submit form's confirmation or sends source code.
  window.qojVpUi = Object.freeze({
    version: 1, refresh: () => refresh(true), selectSession,
    getState: () => ({connected: state.connected, session: state.session ? {...state.session} : null,
      contest: state.contest ? {id: state.contest.id, name: state.contest.name, problemCount: state.contest.problems?.length} : null,
      submissions: state.submissions.map(item => ({...item})), submitting: state.submitting,
      route: location.hash || "#home", lastError: state.lastError ? {...state.lastError} : null}),
  });
  initialize().catch(fail);
})();
