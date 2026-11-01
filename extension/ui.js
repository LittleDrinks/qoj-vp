/* DOMjudge 9.0.1 team UI adaptation, GPL-2.0-or-later. See docs/UI_UPSTREAM.md. */
"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const MAX_SOURCE_BYTES = 512 * 1024;
  const MAX_RESOURCE_BYTES = 64 * 1024 * 1024;
  const RESOURCE_CHUNK_BYTES = 256 * 1024;
  const MAX_MANUAL_BYTES = 8 * 1024 * 1024;
  const MAX_MANUAL_FILE_BYTES = 4 * 1024 * 1024;
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
    forms: new Map(), generation: 0, refreshPromise: null, refreshSession: null, refreshGeneration: null, refreshMode: null,
    sessionRequest: null, contestRequests: new Map(), historyRequests: new Map(),
    contestRefreshing: false, contestCached: false, contestError: "", historyLoaded: false,
    problemCards: new Map(), problemCardSession: null,
    intents: [], setupContest: null, submitting: false, formGeneration: 0,
    confirmPayload: null, reconcileOperation: null, lastError: null,
    resources: new Map(), resourceActivity: new Map(), resourceInteractive: new Map(),
    resourceDownloads: new Set(), resourceJob: null, resourcesLoaded: false, resourceReading: false,
    resourceManifestError: "", resourceSummary: "", resourceReadSequence: 0, resourceMutation: 0,
    ranklandSnapshot: null, ranklandSnapshotState: "unavailable", ranklandSnapshotMessage: "",
    ranklandRequestSequence: 0, ranklandRequest: null,
    scoreboardSource: null, scoreboardRequestSequence: 0, scoreboardRequest: null,
    juryRequest: null, adminBusy: false, manualProblem: null, manualSessionId: null, manualBusy: false, deleteSessionId: null,
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
  function showMessage(target, message, kind = "danger", operationId = null) {
    target.className = "alert alert-" + kind + (target.id === "notice" ? " mt-3" : "");
    target.textContent = message;
    target.classList.remove("d-none");
    if (target.id === "notice") {
      target.hidden = isProblemsRoute() && kind === "success";
      if (operationId) target.dataset.unresolvedOperationId = operationId;
      else delete target.dataset.unresolvedOperationId;
    }
  }
  function hideMessage(target) {
    target.classList.add("d-none"); target.textContent = "";
    if (target.id === "notice") delete target.dataset.unresolvedOperationId;
  }
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
    if (session.state === "finished") return "finished";
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
    const toggle = $("navbarDropdownContests"), menu = $("session-select");
    const disabled = !state.connected || state.submitting;
    const title = state.session ? state.session.title || "Contest " + state.session.contestId : "no contest";
    $("session-label").textContent = title;
    toggle.title = title;
    toggle.setAttribute("aria-label", "Change contest: " + title);
    toggle.setAttribute("aria-disabled", String(disabled));
    toggle.classList.toggle("disabled", disabled);
    if (disabled) toggle.setAttribute("tabindex", "-1"); else toggle.removeAttribute("tabindex");
    menu.dataset.currentContest = previous;
    const heading = node("a", "dropdown-item disabled", "Change Contest");
    heading.href = "#"; heading.tabIndex = -1; heading.setAttribute("aria-disabled", "true");
    menu.replaceChildren(heading);
    for (const session of state.sessions) {
      if (session.sessionId === previous) continue;
      const label = session.title || "Contest " + session.contestId;
      const link = node("a", "dropdown-item" + (disabled ? " disabled" : ""), label + (session.state === "archived" ? " · 已归档" : ""));
      const url = new URL(browser.runtime.getURL("ui.html"));
      url.searchParams.set("session", session.sessionId); url.hash = isJuryRoute() ? "#jury/contest/" + session.sessionId : location.hash;
      link.href = url.href; link.dataset.sessionId = session.sessionId;
      if (disabled) { link.tabIndex = -1; link.setAttribute("aria-disabled", "true"); }
      link.addEventListener("click", event => {
        if (!regularClick(event)) return;
        event.preventDefault();
        if (state.submitting || !state.connected) return;
        bootstrap.Dropdown.getInstance(toggle)?.hide();
        if (isJuryRoute()) { location.hash = "#jury/contest/" + session.sessionId; return; }
        selectSession(session.sessionId).catch(fail);
      });
      menu.append(link);
    }
    $("new-session").disabled = disabled;
    $("open-resources").disabled = !state.connected || !state.contest;
    $("nav-scoreboard").setAttribute("aria-disabled", String(!state.session));
    if (state.session) $("nav-scoreboard").href = "#scoreboard"; else $("nav-scoreboard").removeAttribute("href");
    $("empty-state").hidden = Boolean(state.session) || !state.connected || isJuryRoute();
    $("contest-view").hidden = !state.session || isJuryRoute();
    renderJuryList();
    renderClock();
  }
  function renderClock() {
    const session = state.session;
    if (!session) { $("timeleft").textContent = "no contest"; return; }
    const status = sessionState();
    const start = epoch(session.startAt);
    const end = epoch(session.finishedAt);
    const elapsed = start === null ? 0 : Math.max(0, Math.min(end ?? Date.now(), start + Number(session.durationMs)) - start);
    const remaining = Math.max(0, Number(session.durationMs) - elapsed);
    $("timeleft").textContent = status === "prepared" ? "not started" : status === "archived" ? "archived" : status === "finished" ? "contest ended" : formatElapsed(remaining) + " left";
    const percentage = Math.min(100, Math.max(0, elapsed / Number(session.durationMs) * 100));
    $("contest-progress").style.width = percentage + "%";
    $("contest-progress").setAttribute("aria-valuenow", percentage.toFixed(1));
    $("session-state").textContent = {prepared: "已准备", running: "进行中", finished: "已结束", archived: "已归档"}[status];
    $("start-session").hidden = status !== "prepared";
    $("finish-session").hidden = status !== "running";
    $("start-session").disabled = state.adminBusy;
    $("finish-session").disabled = state.adminBusy;
    $("archive-session").disabled = status === "archived" || status === "running" || state.adminBusy;
    $("delete-session").disabled = status === "running" || state.adminBusy || state.submitting;
    $("delete-session").title = status === "running" ? "先结束比赛，再删除本地记录。" : "删除这场本地比赛";
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
    $("qoj-clarifications-link").href = `https://qoj.ac/contest/${session.contestId}`;
    $("qoj-contest-link").textContent = session.contestId;
    $("jury-contest-title").textContent = "Contest " + (session.title || session.contestId);
    $("jury-duration").textContent = Math.round(session.durationMs / 60000) + " minutes";
    $("jury-title-input").value = session.title || "Contest " + session.contestId;
    $("jury-duration-input").value = session.durationMs / 60000;
    const editable = sessionState() === "prepared";
    for (const id of ["jury-title-input", "jury-duration-input", "jury-config-save"]) $(id).disabled = !editable || state.adminBusy;
    $("jury-config-note").textContent = editable ? "" : "比赛开始后名称和时长保持不变。";
    const historyUrl = new URL(`https://qoj.ac/contest/${session.contestId}/submissions`);
    if (session.account) historyUrl.searchParams.set("submitter", session.account);
    $("qoj-history-link").href = historyUrl.href;
    $("archive-session").disabled = session.state === "archived" || sessionState() === "running" || state.adminBusy;
    $("sync-scoreboard").disabled = !session.ranklandUrl;
    $("rankland-status").textContent = "";
    renderScoreboardSource();
    document.title = (session.title || "Contest " + session.contestId) + " — QOJ";
    renderClock();
  }
  function ranklandViewIdentity(raw) {
    try {
      const url = new URL(raw), query = url.searchParams;
      if (url.username || url.password || !query.get("contest") ||
          !(url.origin === "https://vp.xcpc.link" || url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname))) return null;
      return JSON.stringify([url.origin, query.get("contest"), query.get("run"), query.get("rule") || "auto",
        Number(query.get("count") ?? 50), Number(query.get("ratio") ?? 20), query.get("at") || "null", Number(query.get("from") || 0)]);
    } catch (_) { return null; }
  }
  function validRanklandSnapshot(snapshot, session = state.session) {
    const identity = ranklandViewIdentity(session?.ranklandUrl);
    const metric = value => Number.isSafeInteger(value) && value >= 0;
    return Boolean(identity && snapshot?.version === 1 && snapshot.sessionId === session?.sessionId &&
      snapshot.identity === identity && ranklandViewIdentity(snapshot.url) === identity &&
      metric(snapshot.score) && (snapshot.rank === null || metric(snapshot.rank)) &&
      (snapshot.penaltyMinutes === null || metric(snapshot.penaltyMinutes)) && metric(snapshot.observedAt));
  }
  function resetRanklandSnapshot() {
    state.ranklandRequestSequence++;
    state.ranklandRequest = null;
    state.ranklandSnapshot = null;
    state.ranklandSnapshotState = state.session?.ranklandUrl ? "unavailable" : "not_configured";
    state.ranklandSnapshotMessage = "";
  }
  function adoptRanklandUrl(raw) {
    const previous = ranklandViewIdentity(state.session?.ranklandUrl), incoming = ranklandViewIdentity(raw);
    if (!state.session || !previous || !incoming) return false;
    const url = new URL(raw);
    if (url.searchParams.get("run") !== state.session.sessionId) return false;
    const changed = previous !== incoming;
    if (changed) {
      const configured = JSON.parse(previous), updated = JSON.parse(incoming);
      if ([0, 1, 3, 4, 5].some(index => configured[index] !== updated[index]) ||
          configured[2] && configured[2] !== state.session.sessionId ||
          configured[6] !== "null" && configured[6] !== updated[6] ||
          state.session.ranklandPrepared === true || configured[7] !== 0) return false;
    }
    state.session.ranklandUrl = raw;
    const stored = state.sessions?.find(session => session.sessionId === state.session.sessionId);
    if (stored) stored.ranklandUrl = raw;
    if (changed) {
      state.ranklandSnapshot = null;
      state.ranklandSnapshotState = "unavailable";
      state.ranklandSnapshotMessage = "";
      renderSummary();
    }
    return true;
  }
  function refreshRanklandSnapshot(force = false) {
    const sessionId = state.session?.sessionId, generation = state.generation;
    const expectedUrl = state.session?.ranklandUrl;
    if (!sessionId || !ranklandViewIdentity(expectedUrl)) {
      resetRanklandSnapshot(); renderSummary();
      return Promise.resolve(null);
    }
    const key = JSON.stringify([sessionId, generation, expectedUrl]);
    if (!force && state.ranklandRequest?.key === key) return state.ranklandRequest.promise;
    const request = {key, sequence: ++state.ranklandRequestSequence, promise: null};
    state.ranklandRequest = request;
    const applicable = () => current(sessionId, generation) && state.session.ranklandUrl === expectedUrl &&
      state.ranklandRequestSequence === request.sequence;
    request.promise = (async () => {
      try {
        const result = await call("rankland.snapshot", {sessionId});
        if (!applicable()) return null;
        if (result?.url) adoptRanklandUrl(result.url);
        const snapshot = validRanklandSnapshot(result?.snapshot) ? result.snapshot : null;
        state.ranklandSnapshot = snapshot;
        state.ranklandSnapshotState = snapshot ? result.state === "live" ? "live" : "cached" :
          result?.state === "not_configured" ? "not_configured" : "unavailable";
        state.ranklandSnapshotMessage = String(result?.message || "");
        renderSummary();
        return result;
      } catch (_) {
        if (!applicable()) return null;
        if (!validRanklandSnapshot(state.ranklandSnapshot)) state.ranklandSnapshot = null;
        state.ranklandSnapshotState = state.ranklandSnapshot ? "cached" : "unavailable";
        state.ranklandSnapshotMessage = "暂时无法读取榜单。";
        renderSummary();
        return null;
      } finally {
        if (state.ranklandRequest === request) state.ranklandRequest = null;
      }
    })();
    return request.promise;
  }
  function renderSummary() {
    const target = $("teamscoresummary");
    target.replaceChildren();
    if (!state.session || !state.contest) return;
    const account = state.session.account || state.contest.account || "—";
    const snapshot = validRanklandSnapshot(state.ranklandSnapshot) ? state.ranklandSnapshot : null;
    const stale = snapshot && state.ranklandSnapshotState !== "live";
    const observed = snapshot ? (stale ? "上次同步 " : "更新于 ") + formatDate(snapshot.observedAt) : "";
    const rankNote = snapshot ? "RankLand · " + observed + (snapshot.rank === null ? " · 当前未排名" : "") :
      state.ranklandSnapshotMessage || "尚未读取 RankLand 排名。";
    const penaltyNote = snapshot ? "RankLand · " + observed + (snapshot.penaltyMinutes === null ? " · 未提供罚时" : "") : "尚未读取 RankLand 罚时。";
    const finalVerdicts = new Set(["CORRECT", "WRONG-ANSWER", "TIMELIMIT", "RUN-ERROR", "COMPILER-ERROR", "NO-OUTPUT", "OUTPUT-LIMIT", "MEMORY-LIMIT", "PRESENTATION-ERROR"]);
    const finished = epoch(state.session.finishedAt), started = epoch(state.session.startAt);
    const duration = finished !== null && started !== null ? Math.min(state.session.durationMs, Math.max(0, finished - started)) : state.session.durationMs;
    const progress = state.contest.problems.map(problem => {
      const attempts = state.submissions.filter(item => String(item.problemId) === String(problem.id) && item.state === "confirmed" &&
        item.inSession !== false && typeof item.elapsedMs === "number" && Number.isFinite(item.elapsedMs) && item.elapsedMs >= 0 && item.elapsedMs < duration)
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
    const solved = snapshot ? snapshot.score : progress.filter(item => item.accepted).length;
    const rankValue = snapshot?.rank ?? "—", penaltyValue = snapshot?.penaltyMinutes ?? "—";
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
    const rank = node("td", "scorepl rank", rankValue); rank.title = rankNote;
    const total = node("td", "scorett", penaltyValue); total.title = penaltyNote;
    const count = node("td", "scorenc", solved); count.title = snapshot ? "RankLand · " + observed : "本次练习已确认解题数。";
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
    const mobileTotal = node("span", "scorett", penaltyValue); mobileTotal.style.fontWeight = "normal"; mobileTotal.title = penaltyNote;
    mobileScore.append(node("br"), mobileTotal);
    mobileRow.append(node("td", "scorepl"), node("td", "scoreaf cl_FFFFFF"), teamCell(), mobileScore);
    const mobileProblems = node("tr"); mobileProblems.style.height = "32px";
    const mobileRankCell = node("td"), mobileRank = node("span", "d-block me-2 rank", rankValue); mobileRank.title = rankNote; mobileRankCell.append(mobileRank);
    const mobileBadges = node("td"); mobileBadges.colSpan = 2;
    for (const {problem, accepted} of progress) {
      const item = badge(problem.label); item.style.fontSize = "x-small"; item.style.minWidth = "18px";
      if (!accepted) { item.style.backgroundColor = "#F5F5F5"; item.style.border = "1px solid linen"; item.firstChild.style.color = "silver"; }
      mobileBadges.append(item, " ");
    }
    mobileProblems.append(mobileRankCell, mobileBadges); mobileBody.append(mobileRow, mobileProblems); mobile.append(mobileHead, mobileBody);
    target.append(table, mobile);
    if (stale) {
      const note = node("p", "small text-muted text-center mt-1 mb-0", "榜单上次同步于 " + formatDate(snapshot.observedAt));
      note.dataset.ranklandStatus = "cached"; note.title = state.ranklandSnapshotMessage || "打开 Scoreboard 可继续读取排名。";
      target.append(note);
    }
  }
  function renderSubmissions() {
    const body = $("submissions-body"); body.replaceChildren();
    const visible = state.submissions.filter(item => item.inSession === true || Boolean(item.operationId));
    $("submissions-empty").hidden = Boolean(visible.length);
    $("submissions-empty").textContent = state.historyLoaded === false ? "正在读取保存的提交记录…" : "No submissions";
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
    const hasTimeWarning = /absolute submission time is not verified/i.test(warning);
    const hasCachedWarning = /Cached history/i.test(warning);
    const categories = [
      [/(?:#\d+:\s*)?detailed verdict unavailable[^;]*|Detailed verdicts remain unverified[^;]*/gi, "部分判定未核实，可稍后刷新。"],
      [/(?:#\d+:\s*)?numeric submission score is not verified|Some submission rows could not be verified/gi, "部分记录字段未核实，请在原站核对。"],
      [/History refresh reached its time budget[^;]*|A history page could not be verified[^;]*|Repeated history page detected[^;]*|History exceeded ten pages[^;]*/gi, "部分历史未读完，可刷新继续。"],
    ];
    let remaining = warning.replace(/#\d+:\s*absolute submission time is not verified|Cached history[^;]*/gi, "");
    for (const [pattern, note] of categories) {
      if (pattern.test(remaining)) { notes.push(note); pattern.lastIndex = 0; remaining = remaining.replace(pattern, ""); }
    }
    remaining = remaining.replace(/refresh to (?:retry|query QOJ)|refresh again to continue|[;\s.]/gi, "");
    if (remaining) notes.push("读取历史时有未确认项，请在原站核对。");
    if (!notes.length && coverage.complete === false && !unverified && !hasTimeWarning && !hasCachedWarning) notes.push("部分历史尚未核实，可刷新继续。");
    return notes.join(" ");
  }
  function renderHistoryCoverage(coverage, submissions) {
    const warning = historyCoverageMessage(coverage, submissions);
    if (warning) showMessage($("history-warning"), warning, "warning"); else hideMessage($("history-warning"));
    const unverified = submissions.filter(item => item.timeSource === "unverified-display").length;
    const note = $("history-time-status");
    note.hidden = !unverified;
    note.textContent = unverified ? "部分历史记录的时间待核实，暂不计入本次进度或榜单。" : "";
    note.title = unverified ? `${unverified} 条历史记录尚未获得完整提交时间。` : "";
  }
  function renderProblems() {
    const target = $("problems-list");
    renderContestStatus();
    $("problemset-title").textContent = (state.contest ? contestName(state.contest) : state.session?.title || "Contest") + " problems";
    const sessionId = state.session?.sessionId || null;
    if (state.problemCardSession !== sessionId || !state.contest) {
      state.problemCards = new Map(); state.problemCardSession = sessionId;
      target.replaceChildren();
    }
    if (!state.contest) return;
    state.problemCards ||= new Map();
    const cards = [], retained = new Set();
    for (const problem of state.contest.problems) {
      const id = String(problem.id);
      let view = state.problemCards.get(id);
      if (!view) {
        const col = node("div", "col"), card = node("div", "card"), body = node("div", "card-body");
        const title = node("h2", "card-title"), problemBadge = badge(problem.label);
        title.append(problemBadge);
        const name = node("h3", "card-subtitle mb-2 text-muted"), type = node("h4", "card-subtitle mb-2 text-muted");
        body.append(title, name, type);
        const actions = node("div", "text-center");
        actions.append(cardSubmit(problem));
        // Keep the upstream button and its 10px separator in ordinary flow.
        // Only the inline download group changes when resource data arrives;
        // a pending refresh must not detach a hovered or focused Submit link.
        const separator = node("div"); separator.style.marginTop = "10px"; actions.append(separator);
        const statement = node("a", "btn btn-secondary"); statement.append(icon("file-pdf"), " statement");
        statement.target = "_blank"; statement.rel = "noopener noreferrer"; statement.dataset.statementProblem = problem.id;
        const downloads = node("span"); actions.append(statement, downloads);
        body.append(actions); card.append(body); col.append(card);
        view = {col, problemBadge, name, type, statement, downloads, downloadSignature: null};
        state.problemCards.set(id, view);
      }
      const label = view.problemBadge.firstChild || view.problemBadge;
      if (label.textContent !== String(problem.label || "?")) label.textContent = problem.label || "?";
      if (view.name.textContent !== problem.name) view.name.textContent = problem.name;
      const typeLabel = typeof problem.typeLabel === "string" ? problem.typeLabel.trim() : "";
      const typeText = "Type: " + (typeLabel || "—");
      if (view.type.textContent !== typeText) view.type.textContent = typeText;
      view.statement.href = problemUrl(problem);
      const resources = readyResources(problem.id);
      const signature = JSON.stringify(resources.map(resource => [resource.kind, resource.resourceId, resource.sha256, resource.totalBytes, resource.filename]));
      if (view.downloadSignature !== signature) {
        view.downloads.replaceChildren();
        for (const resource of resources) {
          const link = node("a", "btn btn-secondary"); link.setAttribute("role", "button"); link.tabIndex = 0;
          link.append(icon("file-archive"), resource.kind === "samples" ? " samples" : " 附件");
          resourceDownloadAction(link, problem, resource);
          view.downloads.append(" ", link);
        }
        view.downloadSignature = signature;
      }
      cards.push(view.col); retained.add(id);
    }
    for (const id of state.problemCards.keys()) if (!retained.has(id)) state.problemCards.delete(id);
    if (target.children.length !== cards.length || cards.some((card, index) => target.children[index] !== card)) target.replaceChildren(...cards);
    updateResourceBusyControls();
  }
  function renderContestStatus() {
    const notice = $("problemset-status"), retry = $("refresh-contest");
    notice.textContent = state.contestError ? (state.contest ? "题表更新未完成，保留已保存内容。" : "题表尚未载入，请重试。") :
      state.contestRefreshing ? (state.contest ? "显示已保存题表，正在更新…" : "正在读取题表；提交记录可在 Home 查看。") :
      state.contestCached ? "显示已保存题表。" : state.contest ? "" : "正在读取保存的题表…";
    notice.title = state.contestError || ""; notice.hidden = !notice.textContent;
    retry.hidden = !state.contestError; retry.disabled = state.contestRefreshing;
  }
  function isProblemsRoute() { return location.hash === "#problems" || location.hash === "#problemset"; }
  function isJuryRoute() { return location.hash === "#jury" || location.hash.startsWith("#jury/"); }
  function juryTarget() {
    const match = location.hash.match(/^#jury\/contest\/([a-f0-9-]{36})$/i);
    return match ? match[1] : null;
  }
  function renderJuryList() {
    const body = $("jury-contests-body"); body.replaceChildren();
    for (const session of state.sessions) {
      const row = node("tr"), label = node("td"), link = node("a", "", session.title || "Contest " + session.contestId);
      link.href = "#jury/contest/" + session.sessionId; link.dataset.jurySession = session.sessionId;
      label.append(link);
      row.append(node("td", "", session.contestId), label, node("td", "", session.account || "—"),
        node("td", "", {prepared:"未开始",running:"进行中",finished:"已结束",archived:"已归档"}[sessionState(session)]),
        node("td", "", formatDate(session.startAt)), node("td", "", Math.round(session.durationMs / 60000) + " min"));
      body.append(row);
    }
    $("jury-no-contests").hidden = state.sessions.length > 0;
    $("jury-contests-table").hidden = !state.sessions.length;
  }
  function route() {
    const problems = isProblemsRoute(), jury = isJuryRoute(), target = juryTarget();
    $("team-navigation").hidden = jury; $("team-submit-controls").hidden = jury; $("jury-entry").hidden = jury;
    $("jury-navigation").hidden = !jury; $("jury-view").hidden = !jury;
    $("navbar-brand").href = jury ? "#jury" : "#home";
    $("empty-state").hidden = jury || Boolean(state.session) || !state.connected;
    $("contest-view").hidden = jury || !state.session;
    $("home-view").hidden = problems || jury; $("problems-view").hidden = !problems || jury;
    $("jury-list-view").hidden = Boolean(target); $("jury-detail-view").hidden = !target || state.session?.sessionId !== target;
    $("nav-home").classList.toggle("active", !problems && !jury);
    $("nav-problems").classList.toggle("active", problems && !jury);
    $(problems ? "nav-problems" : "nav-home").setAttribute("aria-current", "page");
    $(problems ? "nav-home" : "nav-problems").removeAttribute("aria-current");
    $("notice").hidden = problems && $("notice").classList.contains("alert-success");
    if (jury) renderJuryList();
    if (target && state.connected && target !== state.session?.sessionId && state.juryRequest !== target) {
      if (!state.sessions.some(item => item.sessionId === target)) { location.hash = "#jury"; return; }
      state.juryRequest = target;
      selectSession(target).catch(fail).finally(() => { if (state.juryRequest === target) state.juryRequest = null; });
    }
  }

  async function listSessions(preferred) {
    const result = await call("list_sessions");
    state.sessions = result.sessions || [];
    const candidate = preferred || state.session?.sessionId || await localGet(ACTIVE_KEY);
    const chosen = state.sessions.find(item => item.sessionId === candidate) || state.sessions.find(item => item.state !== "archived") || state.sessions[0];
    if (chosen) await selectSession(chosen.sessionId);
    else { state.session = null; state.contest = null; state.submissions = []; state.resources.clear(); resetRanklandSnapshot(); renderNavigation(); route(); }
  }
  function sharedRead(requests, key, method, args) {
    if (requests.has(key)) return requests.get(key);
    const request = call(method, args).finally(() => { if (requests.get(key) === request) requests.delete(key); });
    requests.set(key, request);
    return request;
  }
  function verifiedContest(contest, session) {
    if (!contest || String(contest.id) !== String(session.contestId) || !Array.isArray(contest.problems) ||
        contest.account && session.account && contest.account.toLowerCase() !== session.account.toLowerCase()) {
      throw new Error("比赛题表与当前比赛不匹配，请重新读取。");
    }
    return {...contest, name: contestName(contest)};
  }
  function applyHistory(result) {
    if (!Array.isArray(result?.submissions) || result.account && state.session.account && result.account.toLowerCase() !== state.session.account.toLowerCase()) {
      throw new Error("提交记录与当前账号不匹配，请重新读取。");
    }
    state.submissions = result.submissions; state.historyLoaded = true;
    for (const submission of state.submissions) {
      const intent = state.intents.find(item => item.operationId === submission.operationId);
      if (intent && submission.state === "confirmed") Object.assign(intent, {state: "confirmed", submissionId: submission.id});
      if (intent && submission.state === "rejected") intent.state = "rejected";
      if (submission.operationId && $("notice").dataset.unresolvedOperationId === submission.operationId &&
          ["confirmed", "rejected"].includes(submission.state)) hideMessage($("notice"));
    }
    renderSubmissions(); renderHistoryCoverage(result.coverage || {}, state.submissions);
  }
  async function selectSession(sessionId) {
    if (state.submitting) return;
    if (state.sessionRequest?.sessionId === sessionId) return state.sessionRequest.promise;
    const generation = ++state.generation, sameSession = state.session?.sessionId === sessionId;
    const listed = state.sessions.find(item => item.sessionId === sessionId);
    $("refresh-submissions").disabled = true;
    if (!sameSession) {
      state.session = listed || null; state.contest = null; state.submissions = []; state.historyLoaded = false;
      state.forms.clear(); resetRanklandSnapshot();
      state.resources.clear(); state.resourceActivity.clear(); state.resourceInteractive.clear();
      state.resourceJob = null; state.resourcesLoaded = false; state.resourceReading = false;
      state.resourceManifestError = ""; state.resourceSummary = ""; state.resourceMutation = 0;
      state.contestCached = false; state.contestError = ""; state.contestRefreshing = false;
      renderHistoryCoverage({}, []); hideMessage($("notice"));
      $("refresh-status").textContent = "正在读取保存的记录…";
      $("refresh-submissions").disabled = true;
      renderNavigation(); renderSession(); renderSubmissions(); renderProblems(); renderResourceModal(); route();
    }
    const request = {sessionId, promise: null};
    request.promise = (async () => {
      try {
        const snapshot = await call("session_snapshot", {sessionId});
        if (generation !== state.generation) return;
        if (snapshot?.session?.sessionId !== sessionId) throw new Error("保存的比赛与当前选择不匹配。");
        state.session = snapshot.session;
        if (snapshot.contest) { state.contest = verifiedContest(snapshot.contest, state.session); state.contestCached = true; }
        applyHistory(snapshot.history);
        resetRanklandSnapshot();
        resetScoreboardSource();
        renderNavigation(); renderSession(); renderProblems(); renderResourceModal(); route();
        $("refresh-status").textContent = "已显示保存的提交记录";
        $("refresh-submissions").disabled = false;
        // The local snapshot is visible before any provider request starts.
        // Slow or failed network reads never hold navigation or clear it.
        browser.storage.local.set({[ACTIVE_KEY]: sessionId}).catch(() => {});
        persistIntents().catch(() => {});
        loadResourceManifest(sessionId, generation);
        refreshRanklandSnapshot();
        if (state.sessionRequest === request) state.sessionRequest = null;
        refreshContest().catch(() => {});
        refresh(true).catch(() => {});
        resolveScoreboardSource();
        return snapshot.session;
      } catch (error) {
        if (generation === state.generation) {
          state.contestError = message(error); renderContestStatus();
          $("refresh-status").textContent = "读取保存记录未完成，请重试。";
          $("refresh-submissions").disabled = false;
        }
        throw error;
      } finally { if (state.sessionRequest === request) state.sessionRequest = null; }
    })();
    state.sessionRequest = request;
    return request.promise;
  }
  async function refreshContest() {
    if (state.sessionRequest) {
      const pending = state.sessionRequest;
      await pending.promise;
      if (state.session?.sessionId !== pending.sessionId) return;
    }
    if (!state.session) return;
    const sessionId = state.session.sessionId, generation = state.generation, contestId = state.session.contestId;
    state.contestRefreshing = true; state.contestError = ""; renderContestStatus();
    try {
      const contest = await sharedRead(state.contestRequests, sessionId, "qoj_contest", {contestId, sessionId});
      if (!current(sessionId, generation)) return;
      state.contest = verifiedContest(contest, state.session); state.contestCached = false;
      renderSession(); renderProblems(); renderSummary(); renderClock(); renderResourceModal();
      resolveScoreboardSource(true);
      if (!contest.account) showMessage($("notice"), "尚未登录 QOJ。请在原站登录后刷新页面。", "warning");
    } catch (error) {
      if (current(sessionId, generation)) state.contestError = message(error);
      throw error;
    } finally { if (current(sessionId, generation)) { state.contestRefreshing = false; renderContestStatus(); } }
  }
  async function refresh(refreshProvider = true) {
    if (state.sessionRequest) {
      const pending = state.sessionRequest;
      await pending.promise;
      if (state.session?.sessionId !== pending.sessionId) return;
    }
    if (!state.session || state.submitting) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    if (state.refreshPromise && state.refreshSession === sessionId && state.refreshGeneration === generation && state.refreshMode === refreshProvider) return state.refreshPromise;
    $("refresh-submissions").disabled = true;
    if (refreshProvider) $("refresh-status").textContent = state.historyLoaded ? "正在更新判定；已保存记录可继续查看" : "正在同步判定…";
    const promise = (async () => {
      const result = await sharedRead(state.historyRequests, sessionId + ":" + refreshProvider, "qoj_submissions", {sessionId, refresh: refreshProvider});
      if (!current(sessionId, generation)) return;
      applyHistory(result);
      $("refresh-status").textContent = refreshProvider ? "更新于 " + new Date().toLocaleTimeString() : "已读取保存的判定";
      $("refresh-status").title = "";
      await persistIntents();
      return result;
    })();
    state.refreshPromise = promise; state.refreshSession = sessionId; state.refreshGeneration = generation; state.refreshMode = refreshProvider;
    try { return await promise; }
    catch (error) {
      if (current(sessionId, generation)) {
        $("refresh-status").textContent = "同步未完成；保留已保存记录";
        $("refresh-status").title = message(error);
      }
      throw error;
    } finally {
      if (state.refreshPromise === promise) { state.refreshPromise = null; state.refreshSession = null; state.refreshGeneration = null; state.refreshMode = null; }
      if (current(sessionId, generation)) $("refresh-submissions").disabled = Boolean(state.refreshPromise && state.refreshSession === sessionId && state.refreshGeneration === generation);
    }
  }

  function openSessionSetup() {
    if (!isJuryRoute() || !state.connected || state.submitting) return;
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
      location.hash = "#jury/contest/" + session.sessionId;
      if (sessionState() === "prepared") showMessage($("notice"), "已准备。可在比赛管理中开始计时。", "success");
    } catch (error) { showMessage($("session-error"), message(error)); }
    finally { $("prepare-session").disabled = !state.setupContest; }
  }
  async function startSession() {
    if (!isJuryRoute() || !state.session || sessionState() !== "prepared" || state.adminBusy || !confirm("开始计时？仅启动本地计时，不开启 QOJ 官方 VP。")) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    state.adminBusy = true;
    $("start-session").disabled = true;
    try {
      const session = await call("start_session", {sessionId});
      if (!current(sessionId, generation)) return;
      state.session = session;
      const index = state.sessions.findIndex(item => item.sessionId === state.session.sessionId);
      if (index >= 0) state.sessions[index] = state.session;
      renderSession(); renderNavigation(); renderSummary();
      showMessage($("notice"), "计时已开始。", "success");
    } catch (error) { if (current(sessionId, generation)) fail(error); }
    finally { state.adminBusy = false; $("start-session").disabled = false; renderClock(); }
  }

  async function saveJuryConfig(event) {
    event.preventDefault();
    if (!isJuryRoute() || !state.session || sessionState() !== "prepared" || state.adminBusy) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    const title = $("jury-title-input").value.trim(), durationMs = Number($("jury-duration-input").value) * 60000;
    hideMessage($("jury-config-error"));
    if (!title || !Number.isSafeInteger(durationMs) || durationMs < 60000 || durationMs > 20160 * 60000) {
      showMessage($("jury-config-error"), "请输入名称和 1–20160 分钟的比赛时长。"); return;
    }
    state.adminBusy = true; $("jury-config-save").disabled = true;
    try {
      const session = await call("update_session", {sessionId, title, durationMs});
      if (!current(sessionId, generation)) return;
      state.session = session; state.sessions = state.sessions.map(item => item.sessionId === sessionId ? session : item);
      renderSession(); renderNavigation(); showMessage($("notice"), "比赛设置已保存。", "success");
    } catch (error) { if (current(sessionId, generation)) showMessage($("jury-config-error"), message(error)); }
    finally {
      state.adminBusy = false;
      if (current(sessionId, generation)) {
        for (const id of ["jury-title-input", "jury-duration-input", "jury-config-save"]) $(id).disabled = sessionState() !== "prepared";
        renderClock();
      }
    }
  }
  async function finishSession() {
    if (!isJuryRoute() || !state.session || sessionState() !== "running" || state.adminBusy || !confirm("结束这场本地比赛？已有提交与榜单进度会保留。")) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    state.adminBusy = true; $("finish-session").disabled = true;
    try {
      const session = await call("finish_session", {sessionId});
      if (!current(sessionId, generation)) return;
      state.session = session; state.sessions = state.sessions.map(item => item.sessionId === sessionId ? session : item);
      renderSession(); renderNavigation(); renderSummary(); showMessage($("notice"), "比赛已结束。", "success");
    } catch (error) { if (current(sessionId, generation)) fail(error); }
    finally { state.adminBusy = false; $("finish-session").disabled = false; renderClock(); }
  }
  function openDeleteSession() {
    if (!isJuryRoute() || !state.session || sessionState() === "running" || state.adminBusy || state.submitting) return;
    state.deleteSessionId = state.session.sessionId;
    $("delete-contest-form").reset(); hideMessage($("delete-contest-error"));
    $("delete-contest-description").textContent = "删除 “" + (state.session.title || state.session.contestId) + "”？";
    modals["delete-contest"].show();
  }
  async function deleteSession(event) {
    event.preventDefault();
    const sessionId = state.deleteSessionId;
    if (!isJuryRoute() || !sessionId || state.adminBusy || !$("delete-contest-confirm").checked) return;
    state.adminBusy = true; $("delete-contest-send").disabled = true; hideMessage($("delete-contest-error"));
    try {
      const result = await call("delete_session", {sessionId, confirmed: true});
      if (result?.deleted !== true || result.sessionId !== sessionId) throw new Error("未确认比赛已删除，请刷新管理页核对。");
      state.intents = state.intents.filter(item => item.sessionId !== sessionId); await persistIntents();
      state.sessions = state.sessions.filter(item => item.sessionId !== sessionId);
      if (state.session?.sessionId === sessionId) { state.session = null; state.contest = null; state.submissions = []; state.generation++; }
      if (await localGet(ACTIVE_KEY) === sessionId) await browser.storage.local.remove(ACTIVE_KEY);
      modals["delete-contest"].hide(); location.hash = "#jury";
      await listSessions(); route(); showMessage($("notice"), "本地比赛已删除。", "success");
    } catch (error) { showMessage($("delete-contest-error"), message(error)); }
    finally { state.adminBusy = false; $("delete-contest-send").disabled = false; }
  }
  function renderManualMode() {
    const text = $("manual-samples-mode").value === "text";
    $("manual-samples-text-group").hidden = !text; $("manual-samples-files-group").hidden = text;
  }
  function openManualSamples(problem) {
    if (!isJuryRoute() || !state.session || !problemById(String(problem.id)) || state.manualBusy || state.resourceJob) return;
    state.manualProblem = String(problem.id); state.manualSessionId = state.session.sessionId;
    $("manual-samples-form").reset(); hideMessage($("manual-samples-error"));
    $("manual-samples-problem").textContent = problem.label + " — " + problem.name;
    // Check the stored package, including inline samples hidden by an
    // interactive hint. The helper requires consent to replace that data too.
    $("manual-samples-replace-group").hidden = !resourceDescriptors(state.resources.get(String(problem.id))).some(item => item.kind === "samples");
    renderManualMode();
    const show = () => modals["manual-samples"].show();
    if ($("resources-modal").classList.contains("show")) {
      $("resources-modal").addEventListener("hidden.bs.modal", show, {once: true}); modals.resources.hide();
    } else show();
  }
  function bytesBase64(bytes) {
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 32768) binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
    return btoa(binary);
  }
  async function manualSamplesPayload() {
    if ($("manual-samples-mode").value === "text") {
      const input = $("manual-sample-input").value, output = $("manual-sample-output").value;
      if (!input && !output) throw new Error("请粘贴样例输入或输出。");
      const files = [{name: "1.in", bytes: new TextEncoder().encode(input)}, {name: "1.ans", bytes: new TextEncoder().encode(output)}];
      if (files.some(item => item.bytes.length > MAX_MANUAL_FILE_BYTES)) throw new Error("单个样例文件不能超过 4 MiB。");
      return {files: files.map(item => ({name: item.name, base64: bytesBase64(item.bytes)}))};
    }
    const files = Array.from($("manual-samples-files").files || []);
    if (!files.length || files.length > 1000) throw new Error("请选择一个样例 ZIP，或最多 1000 个输入/输出文件。");
    if (files.reduce((sum, file) => sum + file.size, 0) > MAX_MANUAL_BYTES) throw new Error("样例文件总计不能超过 8 MiB。");
    if (files.length === 1 && /\.zip$/i.test(files[0].name)) return {zipBase64: bytesBase64(new Uint8Array(await files[0].arrayBuffer()))};
    if (files.some(file => !/\.(?:in|ans|out)$/i.test(file.name))) throw new Error("请选择同名的 .in 和 .ans / .out 文件，或一个 ZIP。");
    if (files.some(file => file.size > MAX_MANUAL_FILE_BYTES)) throw new Error("单个样例文件不能超过 4 MiB。");
    return {files: await Promise.all(files.map(async file => ({name: file.name, base64: bytesBase64(new Uint8Array(await file.arrayBuffer()))})))};
  }
  async function importManualSamples(event) {
    event.preventDefault();
    const sessionId = state.manualSessionId, generation = state.generation, problemId = state.manualProblem;
    if (!isJuryRoute() || !sessionId || !problemId || state.manualBusy || !current(sessionId, generation)) return;
    hideMessage($("manual-samples-error"));
    if (!$("manual-samples-replace-group").hidden && !$("manual-samples-replace").checked) {
      showMessage($("manual-samples-error"), "请确认是否替换已有样例。"); return;
    }
    state.manualBusy = true; $("manual-samples-save").disabled = true;
    try {
      const payload = await manualSamplesPayload();
      if (!current(sessionId, generation)) throw new Error("比赛已切换，请重新选择题目。");
      const result = await call("import_samples", {sessionId, problemId, ...payload, confirmedReplace: $("manual-samples-replace").checked});
      if (!current(sessionId, generation)) return;
      if (result?.problemId !== problemId || !resourceDescriptors(result).some(item => item.kind === "samples" && item.sampleSource === "manual")) throw new Error("未确认手动样例保存成功，请重新读取资源。");
      state.resourceMutation++; state.resources.set(problemId, result); state.resourceManifestError = "";
      state.resourceSummary = "手动样例已保存，可在 Problemset 下载。";
      renderProblems(); state.manualBusy = false; modals["manual-samples"].hide();
    } catch (error) {
      if (current(sessionId, generation)) {
        if (error?.code === "CONFIRMATION_REQUIRED") {
          $("manual-samples-replace-group").hidden = false;
          $("manual-samples-replace").checked = false;
          showMessage($("manual-samples-error"), "这道题已有样例。请勾选替换确认后重新保存。");
        } else showMessage($("manual-samples-error"), message(error));
      }
    }
    finally {
      state.manualBusy = false; $("manual-samples-save").disabled = false;
      // The resource modal may have rendered during the request, including
      // while hidden. Release its real controls after both success and error.
      renderResourceModal();
    }
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
    if (!canSubmit()) { showMessage($("notice"), "比赛尚未开始。请在比赛管理中开始计时。", "warning"); return; }
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
      else showMessage($("notice"), "提交结果未确认。已保留记录，请核对 QOJ 历史；不会自动重发源码。", "warning", payload.operationId);
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
  function resourceDescriptors(entry) {
    if (entry?.status !== "ready" || typeof entry.problemId !== "string") return [];
    // An explicit downloads list is authoritative. Malformed split metadata
    // must never silently expose the legacy combined ZIP instead.
    const downloads = Object.hasOwn(entry, "downloads") ? entry.downloads : [entry];
    if (!Array.isArray(downloads) || !downloads.length || downloads.length > 2) return [];
    const kinds = new Set();
    for (const resource of downloads) {
      if (!validReadyResource(resource) || resource.problemId !== entry.problemId || kinds.has(resource.kind)) return [];
      kinds.add(resource.kind);
    }
    return [...downloads].sort((left, right) => Number(left.kind === "attachment") - Number(right.kind === "attachment"));
  }
  function readyResources(problemId) {
    const id = String(problemId), entry = state.resources.get(id);
    if (entry?.problemId !== id) return [];
    return resourceDescriptors(entry).filter(resource => !(resource.kind === "samples" && resource.sampleSource === "inline-statement" && interactiveResource(id)));
  }
  function readyResource(problemId, kind, resourceId) {
    return readyResources(problemId).find(resource => (kind === undefined || resource.kind === kind) && (resourceId === undefined || resource.resourceId === resourceId)) || null;
  }
  function resourceDownloadKey(problemId, resource, sessionId = state.session?.sessionId) {
    return JSON.stringify([sessionId, String(problemId), resource.kind, resource.resourceId]);
  }
  function updateResourceBusyControls() {
    for (const control of document.querySelectorAll("[data-resource-problem][data-resource-kind][data-resource-id]")) {
      const resource = {kind: control.dataset.resourceKind, resourceId: control.dataset.resourceId};
      const busy = state.resourceDownloads.has(resourceDownloadKey(control.dataset.resourceProblem, resource));
      actionBusy(control, busy);
      if (busy) control.setAttribute("aria-busy", "true"); else control.removeAttribute("aria-busy");
    }
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
        if (!entry || typeof entry.problemId !== "string" || entries.has(entry.problemId) || !["ready", "unknown"].includes(entry.status) || entry.status === "ready" && !resourceDescriptors(entry).length) throw new Error("资源清单格式无法识别。");
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
  function resourceDownloadAction(control, problem, resource) {
    control.dataset.resourceProblem = String(problem.id);
    control.dataset.resourceKind = resource.kind;
    control.dataset.resourceId = resource.resourceId;
    if (resource.kind === "samples") control.dataset.samplesProblem = String(problem.id);
    else control.dataset.attachmentProblem = String(problem.id);
    const request = event => {
      event.preventDefault();
      if (control.getAttribute("aria-disabled") !== "true") downloadResource(problem, control, resource);
    };
    control.addEventListener("click", request);
    control.addEventListener("auxclick", event => { if (event.button === 1) request(event); });
    control.addEventListener("mousedown", event => { if (event.button === 1) event.preventDefault(); });
    control.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); if (!event.repeat) request(event); }
    });
    const busy = state.resourceDownloads.has(resourceDownloadKey(problem.id, resource));
    actionBusy(control, busy);
    if (busy) control.setAttribute("aria-busy", "true");
  }
  function renderResourceModal() {
    const target = $("resources-list"); target.replaceChildren();
    const problems = state.contest?.problems || [], busy = Boolean(state.resourceJob) || state.resourceReading;
    let count = 0;
    for (const problem of problems) {
      const id = String(problem.id), entry = state.resources.get(id), downloads = readyResources(id), ready = downloads.length > 0;
      if (ready) count++;
      const row = node("tr"), name = node("td"), status = node("td"), hint = node("td"), actions = node("td");
      name.append(badge(problem.label), " " + problem.name);
      const activity = state.resourceActivity.get(id);
      if (activity) status.textContent = activity;
      else if (ready) {
        for (const resource of downloads) {
          const progress = state.resourceActivity.get(resourceDownloadKey(id, resource));
          status.append(node("div", "", (resource.kind === "samples" ? "samples" : "附件") + (resource.sampleSource === "manual" ? "（手动）" : "") + " · " + (progress || humanReadableBytes(resource.totalBytes))));
        }
        if (entry.lastAttempt?.status === "unknown") status.append(node("div", "small text-warning", "本次未确认，保留旧包" + (entry.lastAttempt.code ? "（" + entry.lastAttempt.code + "）" : "")));
      } else status.textContent = entry?.status === "ready" && interactiveResource(id) && resourceDescriptors(entry).some(resource => resource.sampleSource === "inline-statement") ? "需重新核对交互题附件" : entry?.lastAttempt?.status === "unknown" ? "未确认" + (entry.lastAttempt.code ? "（" + entry.lastAttempt.code + "）" : "") : "未准备";
      const checkbox = node("input", "form-check-input"); checkbox.type = "checkbox"; checkbox.checked = interactiveResource(id); checkbox.disabled = busy;
      checkbox.setAttribute("aria-label", problem.label + " 是交互题");
      checkbox.title = "已确认是交互题时勾选，不把交互对话整理为普通样例。";
      checkbox.addEventListener("change", () => { state.resourceInteractive.set(id, checkbox.checked); renderProblems(); renderResourceModal(); });
      hint.append(checkbox);
      for (const resource of downloads) {
        const download = node("a", "btn btn-secondary btn-sm"); download.setAttribute("role", "button"); download.tabIndex = 0; download.textContent = resource.kind === "samples" ? "samples" : "附件";
        resourceDownloadAction(download, problem, resource); actions.append(download, " ");
      }
      const prepare = button(ready ? "刷新" : entry ? "重试" : "准备", "btn btn-outline-secondary btn-sm", () => prepareResources([id], Boolean(ready || entry)));
      prepare.dataset.prepareProblem = id; prepare.disabled = busy; actions.append(prepare, " ");
      const manual = button("添加样例", "btn btn-outline-primary btn-sm", () => openManualSamples(problem));
      manual.dataset.manualSamples = id; manual.disabled = busy || state.manualBusy; actions.append(manual);
      row.append(name, status, hint, actions); target.append(row);
    }
    $("resources-summary").textContent = state.resourceReading ? "正在读取已准备的资源…" : state.resourceSummary || `${count}/${problems.length} 题可下载。准备会读取 QOJ；已有文件直接复用。`;
    if (state.resourceManifestError) showMessage($("resources-error"), state.resourceManifestError); else hideMessage($("resources-error"));
    $("prepare-resources").disabled = busy || !problems.length;
    $("refresh-resources").disabled = busy || !problems.length;
  }
  async function openResources() {
    if (!state.session || !isJuryRoute()) return;
    const loading = loadResourceManifest();
    modals.resources.show(); await loading;
  }
  async function prepareResources(problemIds, refresh = false) {
    if (!isJuryRoute() || !state.session || !state.contest || state.resourceJob || state.resourceReading || state.manualBusy) return;
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
          if (!entry || entry.problemId !== id || !["ready", "unknown"].includes(entry.status) || entry.status === "ready" && !resourceDescriptors(entry).length) throw new Error("准备结果与题目不一致。");
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
  async function downloadResource(problem, control, resource) {
    const sessionId = state.session?.sessionId, generation = state.generation, id = String(problem.id);
    const selected = readyResource(id, resource?.kind, resource?.resourceId);
    if (!selected) return;
    const entry = {...selected}, key = resourceDownloadKey(id, entry, sessionId);
    if (state.resourceDownloads.has(key)) return;
    const unchanged = () => {
      const latest = readyResource(id, entry.kind, entry.resourceId);
      return latest && latest.sha256 === entry.sha256 && latest.totalBytes === entry.totalBytes && latest.filename === entry.filename;
    };
    state.resourceDownloads.add(key); actionBusy(control, true); control.setAttribute("aria-busy", "true");
    updateResourceBusyControls();
    state.resourceManifestError = "";
    try {
      const bytes = new Uint8Array(entry.totalBytes);
      let offset = 0;
      while (offset < entry.totalBytes) {
        if (!current(sessionId, generation) || !unchanged()) throw new Error("资源或比赛已改变，请重新下载。");
        state.resourceActivity.set(key, "正在读取 " + Math.floor(offset / entry.totalBytes * 100) + "%…"); renderResourceModal();
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
      if (await sha256(bytes) !== entry.sha256 || !current(sessionId, generation) || !unchanged()) throw new Error("资源整包校验失败，未下载文件。");
      saveBlob(new Blob([bytes], {type: "application/zip"}), entry.filename);
      state.resourceActivity.set(key, "已校验并开始下载。");
    } catch (error) {
      if (current(sessionId, generation)) {
        state.resourceManifestError = message(error); state.resourceActivity.set(key, "未下载：" + message(error));
        renderResourceModal();
        if (isJuryRoute()) modals.resources.show(); else showMessage($("notice"), "下载失败：" + message(error));
      }
    } finally {
      state.resourceDownloads.delete(key); actionBusy(control, false); control.removeAttribute("aria-busy");
      if (current(sessionId, generation)) { updateResourceBusyControls(); renderResourceModal(); }
    }
  }
  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = node("a"); link.href = url; link.download = filename.replace(/[\\/]/g, "_"); document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  function scoreboardFallback() {
    const rankland = state.session?.ranklandUrl;
    return rankland ? {source: "rankland", state: "configured", url: rankland} :
      {source: "qoj", state: "unverified", url: `https://qoj.ac/contest/${state.session?.contestId || ""}`};
  }
  function renderScoreboardSource() {
    const source = state.scoreboardSource || scoreboardFallback();
    const link = $("scoreboard-source-link"); link.textContent = source.source === "rankland" ? "RankLand" : "QOJ";
    link.href = source.url;
    $("scoreboard-source-status").textContent = source.source === "rankland" ? (source.state === "matched" ? "已自动匹配" : "已配置") :
      state.scoreboardRequest ? "正在检查可用榜单…" : source.state === "unavailable" ? "暂无法匹配 RankLand，使用原站榜单" : "使用原站榜单";
  }
  function resetScoreboardSource() {
    state.scoreboardRequestSequence++; state.scoreboardRequest = null; state.scoreboardSource = null;
    renderScoreboardSource();
  }
  async function resolveScoreboardSource(force = false) {
    if (!state.session) return null;
    const sessionId = state.session.sessionId, generation = state.generation, initialUrl = state.session.ranklandUrl || null;
    if (!force && state.scoreboardRequest?.sessionId === sessionId && state.scoreboardRequest.generation === generation) return state.scoreboardRequest.promise;
    const request = {sessionId, generation, sequence: ++state.scoreboardRequestSequence, promise: null};
    state.scoreboardRequest = request; renderScoreboardSource();
    request.promise = (async () => {
      try {
        const result = await call("scoreboard.resolve", {sessionId, ...(force ? {refresh: true} : {})});
        if (!current(sessionId, generation) || request.sequence !== state.scoreboardRequestSequence || (state.session.ranklandUrl || null) !== initialUrl) return null;
        if (!result || !["rankland", "qoj"].includes(result.source)) throw new Error("未知榜单来源");
        if (result.session && result.session.sessionId !== sessionId) throw new Error("榜单比赛不匹配");
        let url;
        if (result.source === "rankland") {
          url = result.session?.ranklandUrl || result.url;
          if (!ranklandViewIdentity(url) || new URL(url).searchParams.get("run") !== sessionId) throw new Error("榜单链接与本次比赛不匹配");
          const changed = state.session.ranklandUrl !== url;
          state.session = {...state.session, ranklandUrl: url};
          state.sessions = state.sessions.map(item => item.sessionId === sessionId ? {...item, ranklandUrl: url} : item);
          if (changed) { resetRanklandSnapshot(); refreshRanklandSnapshot(true); }
        } else {
          // An existing explicit RankLand selection always wins over a late
          // unmatched result, including after the Jury form was edited.
          if (initialUrl) return null;
          url = safeQojUrl(result.url, `https://qoj.ac/contest/${state.session.contestId}`);
        }
        state.scoreboardSource = {source: result.source, state: result.state, url, checkedAt: result.checkedAt};
        $("sync-scoreboard").disabled = !state.session.ranklandUrl;
        return state.scoreboardSource;
      } catch (_) {
        if (current(sessionId, generation) && request.sequence === state.scoreboardRequestSequence && (state.session.ranklandUrl || null) === initialUrl)
          state.scoreboardSource = {...scoreboardFallback(), state: initialUrl ? "configured" : "unavailable"};
        return null;
      } finally {
        if (state.scoreboardRequest === request) state.scoreboardRequest = null;
        if (current(sessionId, generation)) renderScoreboardSource();
      }
    })();
    return request.promise;
  }
  function openRanklandSettings() {
    if (!state.session || !isJuryRoute()) return;
    $("rankland-url").value = state.session.ranklandUrl || ""; hideMessage($("rankland-error")); modals.rankland.show();
  }
  async function openScoreboard() {
    if (!state.session) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    try {
      const result = await call("scoreboard.open", {sessionId});
      if (!current(sessionId, generation)) return;
      if (result?.source === "rankland" && result.url) adoptRanklandUrl(result.url);
      $("rankland-status").textContent = result?.message || (result?.source === "qoj" ? "已打开 QOJ 榜单。" : "榜单已打开。");
      await resolveScoreboardSource(true);
      if (current(sessionId, generation) && state.session.ranklandUrl) await refreshRanklandSnapshot(true);
    } catch (error) { if (current(sessionId, generation)) showMessage($("notice"), "榜单打开失败：" + message(error)); }
  }
  async function syncScoreboard() {
    if (!state.session || !isJuryRoute()) return;
    const sessionId = state.session.sessionId, generation = state.generation;
    $("sync-scoreboard").disabled = true;
    try {
      const result = await call("rankland.sync", {sessionId});
      if (!current(sessionId, generation)) return;
      $("rankland-status").textContent = result?.message || "判定同步已检查。";
      await refreshRanklandSnapshot(true);
    } catch (error) { if (current(sessionId, generation)) $("rankland-status").textContent = message(error); }
    finally { if (current(sessionId, generation)) $("sync-scoreboard").disabled = !state.session?.ranklandUrl; }
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
    for (const id of ["session", "submit", "rankland", "reconcile", "resources", "manual-samples", "delete-contest"]) modals[id] = new bootstrap.Modal($(id + "-modal"));
    window.addEventListener("hashchange", route); route();
    $("new-session").addEventListener("click", openSessionSetup);
    $("jury-config-form").addEventListener("submit", saveJuryConfig);
    $("finish-session").addEventListener("click", finishSession);
    $("delete-session").addEventListener("click", openDeleteSession);
    $("delete-contest-form").addEventListener("submit", deleteSession);
    $("manual-samples-mode").addEventListener("change", renderManualMode);
    $("manual-samples-form").addEventListener("submit", importManualSamples);
    $("manual-samples-modal").addEventListener("hide.bs.modal", event => { if (state.manualBusy) event.preventDefault(); });
    $("manual-samples-modal").addEventListener("hidden.bs.modal", () => { if (isJuryRoute() && state.session?.sessionId === state.manualSessionId) modals.resources.show(); });
    $("load-contest").addEventListener("click", loadSetupContest);
    $("contest-input").addEventListener("input", () => { state.setupContest = null; $("prepare-session").disabled = true; hideMessage($("contest-preview")); });
    $("session-form").addEventListener("submit", prepareSession);
    $("start-session").addEventListener("click", startSession);
    $("open-resources").addEventListener("click", () => openResources().catch(fail));
    $("prepare-resources").addEventListener("click", () => prepareResources());
    $("refresh-resources").addEventListener("click", () => prepareResources(undefined, true));
    $("refresh-contest").addEventListener("click", () => refreshContest().catch(() => {}));
    $("refresh-submissions").addEventListener("click", () => {
      refresh(true).catch(() => {});
      refreshRanklandSnapshot(true);
    });
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
    $("rankland-settings").addEventListener("click", openRanklandSettings);
    $("sync-scoreboard").addEventListener("click", syncScoreboard);
    $("rankland-form").addEventListener("submit", async event => {
      event.preventDefault(); const control = event.submitter; control.disabled = true;
      const sessionId = state.session.sessionId, generation = state.generation;
      try {
        const updated = await call("update_session", {sessionId, ranklandUrl: $("rankland-url").value.trim()});
        if (!current(sessionId, generation)) return;
        state.session = updated;
        resetRanklandSnapshot(); resetScoreboardSource();
        const index = state.sessions.findIndex(item => item.sessionId === state.session.sessionId);
        if (index >= 0) state.sessions[index] = state.session;
        renderSession(); renderSummary(); modals.rankland.hide();
        refreshRanklandSnapshot(true); resolveScoreboardSource(true);
      } catch (error) { if (current(sessionId, generation)) showMessage($("rankland-error"), message(error)); }
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
      if (!isJuryRoute() || !state.session || sessionState() === "running" || !confirm("归档这场比赛？提交记录和榜单入口会保留。")) return;
      try { const session = await call("archive_session", {sessionId: state.session.sessionId}); await listSessions(session.sessionId); }
      catch (error) { fail(error); }
    });
    setInterval(renderClock, 1000);
    setInterval(() => {
      if (!document.hidden && state.session && !state.submitting && (sessionState() === "running" || state.submissions.some(item => item.pending))) refresh(true).catch(() => {});
    }, 5000);
    setInterval(() => {
      if (!document.hidden && state.connected && state.session && !state.submitting) refreshRanklandSnapshot();
    }, 10000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.connected && state.session) refreshRanklandSnapshot(true);
    });
    try {
      const saved = await localGet(INTENTS_KEY); state.intents = Array.isArray(saved) ? saved : [];
      await call("hello"); state.connected = true; $("connection").classList.add("d-none");
      const entry = new URLSearchParams(location.search), requestedSession = entry.get("session");
      const preferred = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(requestedSession || "") ? requestedSession : undefined;
      await listSessions(preferred);
      if (preferred && state.session?.sessionId === preferred && entry.get("resources") === "1") {
        location.hash = "#jury/contest/" + preferred; route(); await openResources();
      }
    } catch (error) {
      state.lastError = {code: error.code || "HELPER_UNAVAILABLE", message: message(error)};
      showMessage($("connection"), message(error), "danger");
      const retry = button("重新连接", "btn btn-outline-danger btn-sm ms-2", () => location.reload()); $("connection").append(retry);
    }
    renderNavigation(); route();
  }
  // Read-only state and normal refresh/select calls for the VM acceptance harness.
  // No method bypasses the submit form's confirmation or sends source code.
  window.qojVpUi = Object.freeze({
    version: 1, refresh: async () => {
      const results = await Promise.all([refresh(true), refreshRanklandSnapshot(true)]);
      return results[0];
    }, selectSession,
    getState: () => ({connected: state.connected, session: state.session ? {...state.session} : null,
      contest: state.contest ? {id: state.contest.id, name: state.contest.name, problemCount: state.contest.problems?.length} : null,
      submissions: state.submissions.map(item => ({...item})), submitting: state.submitting,
      resources: [...state.resources.values()].map(item => ({...item})),
      resourcesLoaded: state.resourcesLoaded, resourceReading: state.resourceReading, resourcePreparing: Boolean(state.resourceJob),
      rankland: {state: state.ranklandSnapshotState,
        snapshot: validRanklandSnapshot(state.ranklandSnapshot) ? {...state.ranklandSnapshot} : null},
      route: location.hash || "#home", lastError: state.lastError ? {...state.lastError} : null}),
  });
  initialize().catch(fail);
})();
