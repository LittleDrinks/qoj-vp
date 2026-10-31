/* DOMjudge 9.0.1 team UI adaptation, GPL-2.0-or-later. See docs/UI_UPSTREAM.md. */
"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const MAX_SOURCE_BYTES = 512 * 1024;
  const MAX_RESOURCE_BYTES = 64 * 1024 * 1024;
  const RESOURCE_CHUNK_BYTES = 256 * 1024;
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
    resources: new Map(), resourceActivity: new Map(), resourceInteractive: new Map(),
    resourceDownloads: new Set(), resourceJob: null, resourcesLoaded: false, resourceReading: false,
    resourceManifestError: "", resourceSummary: "", resourceReadSequence: 0, resourceMutation: 0,
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
    if (target.id === "notice") target.hidden = isProblemsRoute() && kind === "success";
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
  function submitAvailability(link, enabled) {
    if (link.tagName !== "A") { link.disabled = !enabled; return; }
    link.setAttribute("aria-disabled", String(!enabled));
    link.tabIndex = enabled ? 0 : -1;
    const visual = link.querySelector("span.btn");
    if (visual) {
      visual.classList.toggle("disabled", !enabled);
      if (enabled) visual.removeAttribute("disabled"); else visual.setAttribute("disabled", "");
    }
    if (enabled) {
      link.href = "#submit";
      link.setAttribute("data-ajax-modal", "");
      link.setAttribute("data-ajax-modal-after", "initSubmitModal");
    } else {
      link.removeAttribute("href");
      link.removeAttribute("data-ajax-modal");
      link.removeAttribute("data-ajax-modal-after");
    }
  }
  function cardSubmit(problem) {
    const link = node("a", "justify-content-center"), visual = node("span", "btn btn-success");
    visual.append(icon("cloud-upload-alt"), " Submit"); link.append(visual);
    link.dataset.submitProblem = problem.id;
    submitAvailability(link, canSubmit());
    link.addEventListener("click", event => {
      event.preventDefault();
      if (link.getAttribute("aria-disabled") === "true" || !canSubmit()) return;
      openSubmit(problem.id);
    });
    return link;
  }
  function actionBusy(control, busy) {
    if (control.tagName === "A") {
      control.classList.toggle("disabled", busy);
      if (busy) control.setAttribute("aria-disabled", "true"); else control.removeAttribute("aria-disabled");
    } else control.disabled = busy;
  }
  function regularClick(event) { return event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey; }
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
  function badge(label) {
    // Exact problemBadge fallback for an absent provider color: white, a
    // border with each RGB channel reduced by 64, and black foreground.
    // See pinned TwigExtension::problemBadge and Utils::hexToForegroundAndBorder.
    const outer = node("span", "badge problem-badge"), inner = node("span", "", label || "?");
    outer.style.backgroundColor = "#ffffff";
    outer.style.border = "1px solid #bfbfbf";
    inner.style.color = "#000000";
    outer.append(inner);
    return outer;
  }
  function contestName(contest) {
    return String(contest?.name || "").replace(/\s+-\s+(?:比赛主页\s+-\s+比赛|Dashboard\s+-\s+Contest)\s+-\s+QOJ\.ac\s*$/iu, "").trim() || "Contest " + (contest?.id || state.session?.contestId || "");
  }
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
    $("open-resources").disabled = !state.connected || !state.contest;
    $("empty-new-session").disabled = !state.connected;
    $("nav-scoreboard").setAttribute("aria-disabled", String(!state.session));
    if (state.session) $("nav-scoreboard").href = "#scoreboard"; else $("nav-scoreboard").removeAttribute("href");
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
    submitAvailability($("open-submit"), canSubmit());
    for (const item of document.querySelectorAll("[data-submit-problem]")) submitAvailability(item, canSubmit());
  }
  function renderSession() {
    const session = state.session;
    if (!session) return;
    $("open-resources").disabled = !state.connected || !state.contest;
    $("contest-name").textContent = session.title || state.contest?.name || "Contest " + session.contestId;
    $("account-name").textContent = session.account || state.contest?.account || "请在 QOJ 登录";
    $("started-at").textContent = formatDate(session.startAt);
    $("qoj-contest-link").href = `https://qoj.ac/contest/${session.contestId}`;
    const historyUrl = new URL(`https://qoj.ac/contest/${session.contestId}/submissions`);
    if (session.account) historyUrl.searchParams.set("submitter", session.account);
    $("qoj-history-link").href = historyUrl.href;
    $("archive-session").disabled = session.state === "archived";
    $("sync-scoreboard").disabled = !session.ranklandUrl;
    $("rankland-status").textContent = "";
    document.title = (session.title || "Contest " + session.contestId) + " — QOJ";
    renderClock();
  }
  function renderSummary() {
    const target = $("teamscoresummary");
    target.replaceChildren();
    if (!state.session || !state.contest) return;
    const account = state.session.account || state.contest.account || "—";
    const rankNote = "仅显示本地已确认进度，尚未读取 RankLand 排名。";
    const penaltyNote = "罚时未知：尚未读取 RankLand 完整计分规则及历史。";
    const finalVerdicts = new Set(["CORRECT", "WRONG-ANSWER", "TIMELIMIT", "RUN-ERROR", "COMPILER-ERROR", "NO-OUTPUT", "OUTPUT-LIMIT", "MEMORY-LIMIT", "PRESENTATION-ERROR"]);
    const progress = state.contest.problems.map(problem => {
      const attempts = state.submissions.filter(item => String(item.problemId) === String(problem.id) && item.state === "confirmed" &&
        typeof item.elapsedMs === "number" && Number.isFinite(item.elapsedMs) && item.elapsedMs >= 0 && item.elapsedMs < state.session.durationMs)
        .sort((a, b) => a.elapsedMs - b.elapsedMs || Number(a.id || 0) - Number(b.id || 0));
      const acceptedIndex = attempts.findIndex(item => !item.pending && item.verdict === "CORRECT");
      const accepted = acceptedIndex < 0 ? null : attempts[acceptedIndex];
      const beforeAccepted = accepted ? attempts.slice(0, acceptedIndex + 1) : attempts;
      // Original pass-fail scoreboard structure: compile errors do not count
      // as judged tries; unresolved verdicts remain separate pending tries.
      const judged = beforeAccepted.filter(item => !item.pending && finalVerdicts.has(item.verdict) && item.verdict !== "COMPILER-ERROR");
      const pending = beforeAccepted.filter(item => item.pending || !finalVerdicts.has(item.verdict)).length;
      return {problem, accepted, judged: judged.length, pending};
    });
    const solved = progress.filter(item => item.accepted).length;
    const teamCell = () => {
      const cell = node("td", "scoretn cl_FFFFFF"); cell.title = account;
      const link = node("a");
      link.append(node("span", "forceWidth", account), node("span", "univ forceWidth"));
      cell.append(link);
      return cell;
    };
    const columns = (table, ids) => {
      const group = node("colgroup");
      for (const id of ids) { const column = node("col"); if (id) column.id = id; group.append(column); }
      table.append(group);
    };
    const heading = (label, title, span) => {
      const cell = node("th", "", label); cell.title = title; cell.scope = "col";
      if (span) cell.colSpan = span;
      return cell;
    };
    // Literal single-team desktop/mobile topology from DOMjudge 9.0.1's
    // partials/scoreboard_table.html.twig. Missing provider facts stay unknown.
    const table = node("table", "d-none d-md-table scoreboard desktop-scoreboard center");
    columns(table, ["scoremedal", "scorerank", "scoreflags", "scoreteamname"]);
    columns(table, ["scoresolv", "scoretotal"]);
    const problemColumns = node("colgroup");
    for (const item of progress) problemColumns.append(node("col", "scoreprob"));
    table.append(problemColumns);
    const head = node("thead"), header = node("tr", "scoreheader"); header.dataset.static = "";
    header.append(heading("rank", "rank", 2), heading("team", "team name", 2), heading("score", "# solved / penalty time", 2));
    const row = node("tr", "sortorderswitch");
    const rank = node("td", "scorepl rank", "—"); rank.title = rankNote;
    const total = node("td", "scorett", "—"); total.title = penaltyNote;
    const count = node("td", "scorenc", solved); count.title = "本次练习已确认解题数。";
    row.append(node("td", "no-border"), rank, node("td", "scoreaf cl_FFFFFF"), teamCell(), count, total);
    for (const {problem, accepted, judged, pending} of progress) {
      const title = heading("", "problem " + problem.name);
      const statement = node("a"); statement.href = problemUrl(problem); statement.target = "_blank"; statement.rel = "noopener noreferrer";
      statement.append(badge(problem.label)); title.append(statement); header.append(title);
      const cell = node("td", "score_cell");
      if (judged || pending) {
        const link = node("a");
        const value = node("div", accepted ? "score_correct" : pending ? "score_pending" : "score_incorrect", accepted ? Math.floor(accepted.elapsedMs / 60000) : "\u00a0");
        const tries = pending ? judged + " + " + pending : String(judged);
        value.append(node("span", "", tries + (tries === "1" ? " try" : " tries")));
        link.append(value); cell.append(link);
      }
      row.append(cell);
    }
    const body = node("tbody"); head.append(header); body.append(row); table.append(head, body);

    const mobile = node("table", "d-md-none scoreboard mobile-scoreboard center");
    columns(mobile, ["scorerankmobile", "scoreflagsmobile", "scoreteamnamemobile"]);
    columns(mobile, ["scoresolvmobile"]);
    const mobileHead = node("thead"), mobileHeader = node("tr", "scoreheader"); mobileHeader.dataset.static = ""; mobileHeader.style.fontSize = "75%";
    mobileHeader.append(heading("rank", "rank"), heading("team", "team name", 2), heading("score", "# solved / penalty time", 1)); mobileHead.append(mobileHeader);
    const mobileBody = node("tbody"), mobileRow = node("tr", "sortorderswitch"); mobileRow.style.borderBottomWidth = "0"; mobileRow.style.height = "28px";
    const mobileScore = node("td", "scorenc", solved); mobileScore.rowSpan = 2;
    const mobileTotal = node("span", "scorett", "—"); mobileTotal.style.fontWeight = "normal"; mobileTotal.title = penaltyNote;
    mobileScore.append(node("br"), mobileTotal);
    mobileRow.append(node("td", "scorepl"), node("td", "scoreaf cl_FFFFFF"), teamCell(), mobileScore);
    const mobileProblems = node("tr"); mobileProblems.style.height = "32px";
    const mobileRankCell = node("td"), mobileRank = node("span", "d-block me-2 rank", "—"); mobileRank.title = rankNote; mobileRankCell.append(mobileRank);
    const mobileBadges = node("td"); mobileBadges.colSpan = 2;
    for (const {problem, accepted} of progress) {
      const item = badge(problem.label); item.style.fontSize = "x-small"; item.style.minWidth = "18px";
      if (!accepted) { item.style.backgroundColor = "#F5F5F5"; item.style.border = "1px solid linen"; item.firstChild.style.color = "silver"; }
      mobileBadges.append(item, " ");
    }
    mobileProblems.append(mobileRankCell, mobileBadges); mobileBody.append(mobileRow, mobileProblems); mobile.append(mobileHead, mobileBody);
    target.append(table, mobile);
  }
  function renderSubmissions() {
    const body = $("submissions-body"); body.replaceChildren();
    const visible = state.submissions.filter(item => item.inSession === true || Boolean(item.operationId));
    $("submissions-empty").hidden = Boolean(visible.length);
    $("submissions-table").hidden = !visible.length;
    const sorted = visible.sort((a, b) => (epoch(b.submittedAt) || 0) - (epoch(a.submittedAt) || 0));
    for (const submission of sorted) {
      const row = node("tr", submission.pending ? "unseen" : "");
      if (submission.operationId) row.dataset.operationId = submission.operationId;
      if (submission.id) row.dataset.submissionId = submission.id;
      const detailLink = () => {
        const link = node("a");
        if (submission.state === "confirmed" && submission.id) {
          link.href = safeQojUrl(submission.url, "https://qoj.ac/submission/" + submission.id);
          link.target = "_blank"; link.rel = "noopener noreferrer";
        }
        return link;
      };
      const time = node("td");
      const elapsed = submission.elapsedMs ?? (epoch(submission.submittedAt) !== null && epoch(state.session.startAt) !== null ? epoch(submission.submittedAt) - epoch(state.session.startAt) : null);
      const timeLink = detailLink(); timeLink.textContent = submission.inSession === true ? formatElapsed(elapsed) : "—"; time.append(timeLink);
      time.title = formatDate(submission.submittedAt) + (submission.inSession === false && epoch(submission.submittedAt) !== null ? " · 时间窗外" : "");
      const problem = node("td", "probid"), problemLink = detailLink(); problemLink.append(badge(submission.problemLabel)); problem.append(problemLink);
      const language = node("td", "langid"), languageLink = detailLink(); languageLink.textContent = submission.language || "—"; language.append(languageLink);
      const result = node("td");
      let text = submission.verdict || "UNKNOWN";
      if (submission.state === "unknown" || submission.state === "sending") text = "结果未确认";
      else if (submission.state === "rejected") text = "提交被拒绝";
      const css = text === "CORRECT" ? "sol_correct" : submission.pending || ["JUDGING", "UNKNOWN", "结果未确认"].includes(text) ? "sol_queued" : "sol_incorrect";
      const verdict = node("span", "sol " + css, text);
      verdict.title = submission.rawVerdict || text;
      const resultLink = detailLink(); resultLink.append(verdict); result.append(resultLink);
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
  function historyCoverageMessage(coverage, submissions) {
    const warning = String(coverage.warning || ""), notes = [];
    const unverified = submissions.filter(item => item.timeSource === "unverified-display").length;
    if (unverified) notes.push(`${unverified} 条记录时间未核实，不计入本次进度或榜单。`);
    const categories = [
      [/Cached history[^;]*/gi, "当前为缓存记录，可刷新判定。"],
      [/(?:#\d+:\s*)?detailed verdict unavailable[^;]*|Detailed verdicts remain unverified[^;]*/gi, "部分判定未核实，可稍后刷新。"],
      [/(?:#\d+:\s*)?numeric submission score is not verified|Some submission rows could not be verified/gi, "部分记录字段未核实，请在原站核对。"],
      [/History refresh reached its time budget[^;]*|A history page could not be verified[^;]*|Repeated history page detected[^;]*|History exceeded ten pages[^;]*/gi, "部分历史未读完，可刷新继续。"],
    ];
    let remaining = warning.replace(/#\d+:\s*absolute submission time is not verified/gi, "");
    for (const [pattern, note] of categories) {
      if (pattern.test(remaining)) { notes.push(note); pattern.lastIndex = 0; remaining = remaining.replace(pattern, ""); }
    }
    remaining = remaining.replace(/refresh to (?:retry|query QOJ)|refresh again to continue|[;\s.]/gi, "");
    if (remaining) notes.push("读取历史时有未确认项，请在原站核对。");
    if (!notes.length && coverage.complete === false) notes.push("部分历史尚未核实，可刷新继续。");
    return notes.join(" ");
  }
  function renderProblems() {
    const target = $("problems-list"); target.replaceChildren();
    if (!state.contest) return;
    $("problemset-title").textContent = contestName(state.contest) + " problems";
    for (const problem of state.contest.problems) {
      const col = node("div", "col"), card = node("div", "card"), body = node("div", "card-body");
      const title = node("h2", "card-title"); title.append(badge(problem.label));
      body.append(title, node("h3", "card-subtitle mb-2 text-muted", problem.name));
      const typeLabel = typeof problem.typeLabel === "string" ? problem.typeLabel.trim() : "";
      body.append(node("h4", "card-subtitle mb-2 text-muted", "Type: " + (typeLabel || "—")));
      const actions = node("div", "text-center");
      actions.append(cardSubmit(problem));
      // Same ordinary document flow as pinned partials/problem_list: the
      // centered Submit action, its exact 10px separator, then inline links.
      const separator = node("div"); separator.style.marginTop = "10px"; actions.append(separator);
      const statement = node("a", "btn btn-secondary"); statement.setAttribute("role", "button"); statement.append(icon("file-pdf"), " statement"); statement.href = problemUrl(problem); statement.target = "_blank"; statement.rel = "noopener noreferrer";
      statement.dataset.pdfProblem = problem.id;
      statement.addEventListener("click", event => {
        if (!regularClick(event)) return;
        event.preventDefault();
        if (statement.getAttribute("aria-disabled") !== "true") downloadPdf(problem, statement);
      });
      actions.append(statement);
      const resource = readyResource(problem.id);
      if (resource) {
        const link = node("a", "btn btn-secondary"); link.setAttribute("role", "button"); link.tabIndex = 0;
        link.dataset.resourceProblem = problem.id;
        if (resource.kind === "samples") link.dataset.samplesProblem = problem.id;
        link.append(icon("file-archive"), resource.kind === "samples" ? " samples" : " 附件");
        resourceDownloadAction(link, problem);
        actions.append(" ", link);
      }
      const status = node("p", "small text-muted mb-0"); status.hidden = true; status.id = "problem-status-" + problem.id; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
      body.append(actions, status); card.append(body); col.append(card); target.append(col);
    }
  }
  function isProblemsRoute() { return location.hash === "#problems" || location.hash === "#problemset"; }
  function route() {
    const problems = isProblemsRoute();
    $("home-view").hidden = problems; $("problems-view").hidden = !problems;
    $("nav-home").classList.toggle("active", !problems);
    $("nav-problems").classList.toggle("active", problems);
    $(problems ? "nav-problems" : "nav-home").setAttribute("aria-current", "page");
    $(problems ? "nav-home" : "nav-problems").removeAttribute("aria-current");
    $("notice").hidden = problems && $("notice").classList.contains("alert-success");
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
    state.resources.clear(); state.resourceActivity.clear(); state.resourceInteractive.clear();
    state.resourceJob = null; state.resourcesLoaded = false; state.resourceReading = false; state.resourceManifestError = ""; state.resourceSummary = "";
    state.resourceMutation = 0;
    hideMessage($("history-warning")); hideMessage($("notice"));
    $("teamscoresummary").replaceChildren(); $("problems-list").replaceChildren();
    $("refresh-status").textContent = "正在读取比赛…";
    renderNavigation(); renderSession(); renderSubmissions(); route();
    renderResourceModal();
    const resourceLoad = loadResourceManifest(sessionId, generation);
    await browser.storage.local.set({[ACTIVE_KEY]: sessionId});
    try {
      const contest = await call("qoj_contest", {contestId: state.session.contestId, sessionId});
      if (!current(sessionId, generation)) return;
      state.contest = {...contest, name: contestName(contest)};
      if (!Array.isArray(contest.problems)) throw new Error("比赛题表格式无法识别，请重新读取比赛。");
      renderSession(); renderProblems(); renderSummary(); renderClock(); renderResourceModal();
      if (!contest.account) showMessage($("notice"), "尚未登录 QOJ。请在原站登录后刷新页面。", "warning");
    } catch (error) { if (current(sessionId, generation)) fail(error); }
    await resourceLoad;
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
      const coverageMessage = historyCoverageMessage(coverage, state.submissions);
      if (coverageMessage) showMessage($("history-warning"), coverageMessage, "warning");
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
      state.setupContest = {...contest, name: contestName(contest)};
      if (!$("session-title").value) $("session-title").value = state.setupContest.name;
      showMessage($("contest-preview"), `${state.setupContest.name} · ${contest.problems.length} problems · ${contest.account}`, "secondary");
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
      if (sessionState() === "prepared") showMessage($("notice"), "已准备。点击 Start 开始。", "success");
    } catch (error) { showMessage($("session-error"), message(error)); }
    finally { $("prepare-session").disabled = !state.setupContest; }
  }
  async function startSession() {
    if (!state.session || !confirm("开始计时？仅启动本地计时，不开启 QOJ 官方 VP。")) return;
    $("start-session").disabled = true;
    try {
      state.session = await call("start_session", {sessionId: state.session.sessionId});
      const index = state.sessions.findIndex(item => item.sessionId === state.session.sessionId);
      if (index >= 0) state.sessions[index] = state.session;
      renderSession(); renderNavigation(); renderSummary();
      showMessage($("notice"), "计时已开始。", "success");
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
    $("submit_problem_language").disabled = ![...$("submit_problem_language").options].some(option => option.value);
  }
  async function openSubmit(problemId) {
    if (!canSubmit()) { showMessage($("notice"), "请先点击 Start，再提交代码。", "warning"); return; }
    $("submit-form").reset(); hideMessage($("submit-error")); hideMessage($("files_selected"));
    $("submit_problem_problem").replaceChildren(new Option("Select a problem", ""));
    for (const problem of state.contest.problems) $("submit_problem_problem").append(new Option(problem.label + " - " + problem.name, problem.id));
    $("submit_problem_problem").value = problemId || "";
    $("submit-problem-row").className = problemId ? "d-none" : "mb-3";
    $("submit_problem_language").replaceChildren(new Option("Select a language", ""));
    $("submit_problem_language").disabled = true; $("language-status").textContent = ""; $("language-status").hidden = true;
    $("submit-title").textContent = problemId ? "Submit problem " + problemById(problemId).name : "Submit";
    resetConfirmation(); modals.submit.show();
    await loadLanguages();
  }
  async function loadLanguages() {
    const selectedProblemId = $("submit_problem_problem").value;
    const problemId = selectedProblemId || state.contest?.problems[0]?.id;
    const previousLanguage = $("submit_problem_language").value;
    const generation = ++state.formGeneration, sessionId = state.session?.sessionId;
    $("submit_problem_language").replaceChildren(new Option("Select a language", ""));
    $("submit_problem_language").disabled = true; $("language-status").textContent = ""; $("language-status").hidden = true;
    if (!problemId) return;
    try {
      const key = sessionId + ":" + problemId;
      let form = state.forms.get(key);
      if (!form) { form = await call("qoj_problem_form", {sessionId, problemId}); state.forms.set(key, form); }
      if (generation !== state.formGeneration || state.session?.sessionId !== sessionId || $("submit_problem_problem").value !== selectedProblemId) return;
      const languages = form.languages || [];
      if (!languages.length) throw new Error("QOJ 未返回可用语言，请检查原站提交权限。");
      $("submit_problem_language").replaceChildren(new Option("Select a language", ""));
      for (const language of languages) $("submit_problem_language").append(new Option(language, language));
      $("submit_problem_language").disabled = false;
      const file = $("submit_problem_code").files[0];
      if (previousLanguage && languages.includes(previousLanguage)) {
        $("submit_problem_language").value = previousLanguage;
      } else if (file) {
        const guessed = inferLanguage(file.name, languages);
        $("submit_problem_language").value = guessed;
        $("language-status").textContent = ""; $("language-status").hidden = true;
      }
    } catch (error) {
      if (generation === state.formGeneration) showMessage($("submit-error"), message(error));
    }
  }
  async function fileSelected() {
    resetConfirmation(); hideMessage($("submit-error"));
    const file = $("submit_problem_code").files[0]; if (!file) return;
    const details = $("files_selected"); details.className = "alert d-none"; details.replaceChildren();
    const list = node("ul");
    const validName = /^[a-zA-Z0-9_][a-zA-Z0-9+_.-]*$/.test(file.name);
    const item = node("li", file.size === 0 ? "bg-warning" : validName ? "" : "bg-danger");
    item.append(node("span", "filename", file.name), ` size ${humanReadableBytes(file.size)}, last modified ${humanReadableTimeDiff((Date.now() - file.lastModified) / 1000)} ago` + (!validName ? ", invalid filename" : "") + (!file.size ? ", empty file" : ""));
    list.append(item);
    details.append(list); details.classList.remove("d-none");
    if (file.size === 0 || file.size > MAX_SOURCE_BYTES) showMessage($("submit-error"), file.size === 0 ? "源文件为空，请检查选择的文件。" : "源文件超过 512 KiB，请检查选择的文件。");
    if (Date.now() - file.lastModified > 5 * 60 * 1000) details.append(node("div", "alert alert-warning", "None of the selected files have been recently modified"));
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
    if (!problem || !language || !canSubmit()) throw new Error("请核对比赛、题目、语言和比赛状态。");
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
    if (!canSubmit() || payload.sessionId !== state.session.sessionId) { showMessage($("submit-error"), "比赛状态已改变，请重新确认。"); return; }
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

  function interactiveResource(problemId) {
    const id = String(problemId);
    if (state.resourceInteractive.has(id)) return state.resourceInteractive.get(id);
    const problem = problemById(id), entry = state.resources.get(id);
    return problem?.interactive === true || /interactive|交互/i.test(problem?.typeLabel || "") ||
      entry?.interactiveHint === true || entry?.lastAttempt?.interactiveHint === true;
  }
  function validReadyResource(entry) {
    if (entry?.status !== "ready" || !["samples", "attachment"].includes(entry.kind) ||
        !/^[a-f0-9]{64}$/.test(entry.resourceId || "") || !/^[a-f0-9]{64}$/.test(entry.sha256 || "") ||
        !Number.isSafeInteger(entry.totalBytes) || entry.totalBytes <= 0 || entry.totalBytes > MAX_RESOURCE_BYTES ||
        typeof entry.filename !== "string" || !entry.filename || entry.filename.length > 200 ||
        /[\\/:\x00-\x1f]/.test(entry.filename) || entry.filename === "." || entry.filename === "..") return false;
    return true;
  }
  function readyResource(problemId) {
    const entry = state.resources.get(String(problemId));
    if (!validReadyResource(entry) || entry.problemId !== String(problemId)) return null;
    if (interactiveResource(problemId) && entry.sampleSource === "inline-statement") return null;
    return entry;
  }
  async function loadResourceManifest(sessionId = state.session?.sessionId, generation = state.generation) {
    if (!sessionId) return;
    const sequence = ++state.resourceReadSequence, mutation = state.resourceMutation;
    state.resourceReading = true; renderResourceModal();
    try {
      const manifest = await call("resource_manifest", {sessionId});
      if (!current(sessionId, generation) || sequence !== state.resourceReadSequence || mutation !== state.resourceMutation) return;
      if (manifest?.origin !== "https://qoj.ac" || String(manifest.contestId) !== String(state.session.contestId) ||
          typeof manifest.account !== "string" || manifest.account.toLowerCase() !== String(state.session.account || "").toLowerCase() ||
          !Array.isArray(manifest.problems)) throw new Error("资源清单与当前比赛或账号不一致。");
      const entries = new Map();
      for (const entry of manifest.problems) {
        if (!entry || typeof entry.problemId !== "string" || entries.has(entry.problemId) || !["ready", "unknown"].includes(entry.status) || entry.status === "ready" && !validReadyResource(entry)) throw new Error("资源清单格式无法识别。");
        entries.set(entry.problemId, entry);
      }
      state.resources = entries; state.resourcesLoaded = true; state.resourceManifestError = "";
    } catch (error) {
      if (current(sessionId, generation) && sequence === state.resourceReadSequence && mutation === state.resourceMutation) state.resourceManifestError = message(error);
    } finally {
      if (current(sessionId, generation) && sequence === state.resourceReadSequence) {
        state.resourceReading = false; renderProblems(); renderResourceModal();
      }
    }
  }
  function resourceDownloadAction(control, problem) {
    const request = event => {
      event.preventDefault();
      if (control.getAttribute("aria-disabled") !== "true") downloadResource(problem, control);
    };
    control.addEventListener("click", request);
    control.addEventListener("auxclick", event => { if (event.button === 1) request(event); });
    control.addEventListener("mousedown", event => { if (event.button === 1) event.preventDefault(); });
    control.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); if (!event.repeat) request(event); }
    });
    actionBusy(control, state.resourceDownloads.has(state.session?.sessionId + ":" + problem.id));
  }
  function renderResourceModal() {
    const target = $("resources-list"); target.replaceChildren();
    const problems = state.contest?.problems || [], busy = Boolean(state.resourceJob) || state.resourceReading;
    let count = 0;
    for (const problem of problems) {
      const id = String(problem.id), entry = state.resources.get(id), ready = readyResource(id);
      if (ready) count++;
      const row = node("tr"), name = node("td"), status = node("td"), hint = node("td"), actions = node("td");
      name.append(badge(problem.label), " " + problem.name);
      const activity = state.resourceActivity.get(id);
      if (activity) status.textContent = activity;
      else if (ready) {
        status.append(node("span", "", (ready.kind === "samples" ? "samples" : "附件") + " · " + humanReadableBytes(ready.totalBytes)));
        if (ready.lastAttempt?.status === "unknown") status.append(node("div", "small text-warning", "本次未确认，保留旧包" + (ready.lastAttempt.code ? "（" + ready.lastAttempt.code + "）" : "")));
      } else status.textContent = entry?.status === "ready" && interactiveResource(id) && entry.sampleSource === "inline-statement" ? "需重新核对交互题附件" : entry?.lastAttempt?.status === "unknown" ? "未确认" + (entry.lastAttempt.code ? "（" + entry.lastAttempt.code + "）" : "") : "未准备";
      const checkbox = node("input", "form-check-input"); checkbox.type = "checkbox"; checkbox.checked = interactiveResource(id); checkbox.disabled = busy;
      checkbox.setAttribute("aria-label", problem.label + " 是交互题");
      checkbox.title = "已确认是交互题时勾选，不把交互对话整理为普通样例。";
      checkbox.addEventListener("change", () => { state.resourceInteractive.set(id, checkbox.checked); renderProblems(); renderResourceModal(); });
      hint.append(checkbox);
      if (ready) {
        const download = node("a", "btn btn-secondary btn-sm"); download.setAttribute("role", "button"); download.tabIndex = 0; download.textContent = "下载";
        resourceDownloadAction(download, problem); actions.append(download, " ");
      }
      const prepare = button(ready ? "刷新" : entry ? "重试" : "准备", "btn btn-outline-secondary btn-sm", () => prepareResources([id], Boolean(ready || entry)));
      prepare.disabled = busy; actions.append(prepare);
      row.append(name, status, hint, actions); target.append(row);
    }
    $("resources-summary").textContent = state.resourceReading ? "正在读取已准备的资源…" : state.resourceSummary || `${count}/${problems.length} 题可下载。准备会读取 QOJ；已有文件直接复用。`;
    if (state.resourceManifestError) showMessage($("resources-error"), state.resourceManifestError); else hideMessage($("resources-error"));
    $("prepare-resources").disabled = busy || !problems.length;
    $("refresh-resources").disabled = busy || !problems.length;
  }
  async function openResources() {
    if (!state.session) return;
    const loading = loadResourceManifest();
    modals.resources.show(); await loading;
  }
  async function prepareResources(problemIds, refresh = false) {
    if (!state.session || !state.contest || state.resourceJob || state.resourceReading) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    const ids = problemIds || state.contest.problems.map(problem => String(problem.id));
    const job = {sessionId, generation}; state.resourceJob = job;
    state.resourceManifestError = "";
    let prepared = 0, reused = 0, unknown = 0;
    try {
      for (const id of ids) {
        if (!current(sessionId, generation)) break;
        if (!refresh && readyResource(id)) { reused++; continue; }
        state.resourceActivity.set(id, "正在准备…"); state.resourceSummary = `正在准备 ${problemById(id)?.label || id}…`; renderResourceModal();
        try {
          const entry = await call("prepare_resource", {sessionId, problemId: id, interactiveHint: interactiveResource(id)});
          if (!current(sessionId, generation)) break;
          if (!entry || entry.problemId !== id || !["ready", "unknown"].includes(entry.status) || entry.status === "ready" && !validReadyResource(entry)) throw new Error("准备结果与题目不一致。");
          state.resourceMutation++; state.resources.set(id, entry); state.resourcesLoaded = true;
          state.resourceActivity.delete(id);
          if (readyResource(id) && entry.lastAttempt?.status !== "unknown") prepared++;
          else unknown++;
        } catch (error) {
          if (!current(sessionId, generation)) break;
          unknown++; state.resourceActivity.set(id, (readyResource(id) ? "本次未确认，保留旧包：" : "本次未确认：") + message(error));
        }
        renderProblems(); renderResourceModal();
      }
    } finally {
      if (state.resourceJob === job) {
        state.resourceJob = null;
        state.resourceSummary = `新准备 ${prepared}，复用 ${reused}，未确认 ${unknown}。`;
        renderResourceModal();
      }
    }
  }
  async function sha256(bytes) {
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    let hex = ""; for (const byte of digest) hex += byte.toString(16).padStart(2, "0");
    return hex;
  }
  async function downloadResource(problem, control) {
    const sessionId = state.session?.sessionId, generation = state.generation, id = String(problem.id);
    const entry = readyResource(id), key = sessionId + ":" + id;
    if (!entry || state.resourceDownloads.has(key)) return;
    state.resourceDownloads.add(key); actionBusy(control, true); control.setAttribute("aria-busy", "true");
    state.resourceManifestError = "";
    try {
      const bytes = new Uint8Array(entry.totalBytes);
      let offset = 0;
      while (offset < entry.totalBytes) {
        if (!current(sessionId, generation) || !readyResource(id) || readyResource(id).resourceId !== entry.resourceId) throw new Error("资源或比赛已改变，请重新下载。");
        state.resourceActivity.set(id, "正在读取 " + Math.floor(offset / entry.totalBytes * 100) + "%…"); renderResourceModal();
        const chunk = await call("resource_chunk", {sessionId, problemId: id, resourceId: entry.resourceId, offset, maxBytes: RESOURCE_CHUNK_BYTES});
        if (!current(sessionId, generation)) throw new Error("比赛已切换，请重新下载。");
        if (!chunk || chunk.problemId !== id || chunk.resourceId !== entry.resourceId || chunk.offset !== offset || chunk.totalBytes !== entry.totalBytes || chunk.sha256 !== entry.sha256 ||
            typeof chunk.bytesBase64 !== "string" || chunk.bytesBase64.length > Math.ceil(RESOURCE_CHUNK_BYTES / 3) * 4 ||
            !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(chunk.bytesBase64) || !/^[a-f0-9]{64}$/.test(chunk.chunkSha256 || "")) throw new Error("资源分块信息校验失败，未下载文件。");
        const decoded = atob(chunk.bytesBase64), part = new Uint8Array(decoded.length);
        for (let index = 0; index < decoded.length; index++) part[index] = decoded.charCodeAt(index);
        if (!part.length || part.length > RESOURCE_CHUNK_BYTES || chunk.nextOffset !== offset + part.length || chunk.nextOffset > entry.totalBytes ||
            chunk.eof !== (chunk.nextOffset === entry.totalBytes) || await sha256(part) !== chunk.chunkSha256) throw new Error("资源分块内容校验失败，未下载文件。");
        bytes.set(part, offset); offset = chunk.nextOffset;
      }
      if (await sha256(bytes) !== entry.sha256 || !current(sessionId, generation) || !readyResource(id) || readyResource(id).resourceId !== entry.resourceId) throw new Error("资源整包校验失败，未下载文件。");
      saveBlob(new Blob([bytes], {type: "application/zip"}), entry.filename);
      state.resourceActivity.set(id, "已校验并开始下载。");
    } catch (error) {
      if (current(sessionId, generation)) {
        state.resourceManifestError = message(error); state.resourceActivity.set(id, "未下载：" + message(error));
        renderResourceModal(); modals.resources.show();
      }
    } finally {
      state.resourceDownloads.delete(key); actionBusy(control, false); control.removeAttribute("aria-busy");
      if (current(sessionId, generation)) renderResourceModal();
    }
  }
  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = node("a"); link.href = url; link.download = filename.replace(/[\\/]/g, "_"); document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  function saveArchive(base64, filename, type = "application/zip") {
    const decoded = atob(base64), bytes = Uint8Array.from(decoded, value => value.charCodeAt(0));
    saveBlob(new Blob([bytes], {type}), filename);
  }
  async function downloadPdf(problem, control) {
    actionBusy(control, true); const sessionId = state.session.sessionId;
    const target = $("problem-status-" + problem.id); target.hidden = false; target.textContent = "正在打开题面 PDF…";
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
    finally { actionBusy(control, false); }
  }
  function openRanklandSettings() {
    if (!state.session) return;
    $("rankland-url").value = state.session.ranklandUrl || ""; hideMessage($("rankland-error")); modals.rankland.show();
  }
  async function openScoreboard() {
    if (!state.session?.ranklandUrl) { openRanklandSettings(); return; }
    try {
      const result = await call("rankland.open", {sessionId: state.session.sessionId});
      $("rankland-status").textContent = result?.message || "榜单已打开。";
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
    for (const id of ["session", "submit", "rankland", "reconcile", "resources"]) modals[id] = new bootstrap.Modal($(id + "-modal"));
    window.addEventListener("hashchange", route); route();
    $("session-select").addEventListener("change", event => selectSession(event.target.value).catch(fail));
    $("new-session").addEventListener("click", openSessionSetup);
    $("empty-new-session").addEventListener("click", openSessionSetup);
    $("load-contest").addEventListener("click", loadSetupContest);
    $("contest-input").addEventListener("input", () => { state.setupContest = null; $("prepare-session").disabled = true; hideMessage($("contest-preview")); });
    $("session-form").addEventListener("submit", prepareSession);
    $("start-session").addEventListener("click", startSession);
    $("open-resources").addEventListener("click", () => openResources().catch(fail));
    $("prepare-resources").addEventListener("click", () => prepareResources());
    $("refresh-resources").addEventListener("click", () => prepareResources(undefined, true));
    $("refresh-submissions").addEventListener("click", () => refresh(true).catch(fail));
    $("open-submit").addEventListener("click", event => {
      event.preventDefault();
      if ($("open-submit").getAttribute("aria-disabled") !== "true" && canSubmit()) openSubmit();
    });
    $("submit-form").addEventListener("submit", submit);
    $("submit_problem_code").addEventListener("change", () => fileSelected().catch(error => showMessage($("submit-error"), message(error))));
    $("submit_problem_problem").addEventListener("change", () => { resetConfirmation(); loadLanguages().catch(fail); });
    $("submit_problem_language").addEventListener("change", () => { if (state.confirmPayload) resetConfirmation(); });
    $("submit-modal").addEventListener("hide.bs.modal", event => { if (state.submitting) event.preventDefault(); });
    $("nav-scoreboard").addEventListener("click", event => {
      event.preventDefault();
      if ($("nav-scoreboard").getAttribute("aria-disabled") !== "true") openScoreboard();
    });
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
      if (!state.session || !confirm("归档这场练习？提交记录和榜单入口会保留。")) return;
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
      const entry = new URLSearchParams(location.search), requestedSession = entry.get("session");
      const preferred = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(requestedSession || "") ? requestedSession : undefined;
      await listSessions(preferred);
      if (preferred && state.session?.sessionId === preferred && entry.get("resources") === "1") await openResources();
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
      resources: [...state.resources.values()].map(item => ({...item})),
      resourcesLoaded: state.resourcesLoaded, resourceReading: state.resourceReading, resourcePreparing: Boolean(state.resourceJob),
      route: location.hash || "#home", lastError: state.lastError ? {...state.lastError} : null}),
  });
  initialize().catch(fail);
})();
