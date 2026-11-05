"use strict";
(() => {
  const HOST = "org.littledrinks.qoj_vp";
  const methods = new Set(["hello", "create_session", "start_session", "list_sessions", "inspect_session", "archive_session", "update_session",
    "qoj_contest", "qoj_bind_virtual", "qoj_confirm_virtual_start", "qoj_problem_form", "qoj_samples", "qoj_submit", "qoj_submissions", "qoj_reconcile", "rankland_queue", "rankland_ack", "rankland_ack_batch", "rankland_plan", "refresh_sessions", "prepare_rankland",
    "resource_manifest", "prepare_resource", "resource_chunk", "import_samples", "delete_session", "finish_session", "session_snapshot"]);
  const ranklandIdentity = raw => VpRanklandProtocol.identity(raw);
  async function rememberRanklandUrl(raw) {
    const identity = ranklandIdentity(raw);
    await browser.storage.local.set({["rankland-url-v1:" + identity]: {url:raw,identity,observedAt:Date.now()}});
  }
  async function restoredRanklandUrl(raw) {
    const identity = ranklandIdentity(raw), key = "rankland-url-v1:" + identity;
    const saved = (await browser.storage.local.get(key))[key];
    try { if (saved?.identity === identity && ranklandIdentity(saved.url) === identity) return saved.url; }
    catch (_) { /* An invalid or old cache cannot change this session's target. */ }
    return raw;
  }
  // SPA replaceState updates (join team, pause, speed) must survive closing the
  // tab immediately, without waiting for the next score poll or content timer.
  browser.tabs?.onUpdated?.addListener((_tabId, change) => {
    if (!change.url) return;
    try {
      const url = new URL(change.url);
      if (url.origin === "https://vp.xcpc.link" && url.searchParams.has("at")) {
        rememberRanklandUrl(url.href).catch(() => {});
      }
    } catch (_) { /* No valid replay identity to save. */ }
  });
  const openingRankland = new Map();
  const ranklandGuardEvents = [];
  async function matchingRanklandTabs(expectedUrl, sessionId) {
    const identity = ranklandIdentity(expectedUrl);
    const gate = new URL("/", expectedUrl);
    gate.searchParams.set("qoj-vp-transfer", sessionId || new URL(expectedUrl).searchParams.get("run"));
    return (await browser.tabs.query({})).filter(item => {
      try { return item.url === gate.href || ranklandIdentity(item.url) === identity; } catch (_) { return false; }
    });
  }
  const readingRanklandScores = new Map();
  function validRanklandScore(snapshot, session) {
    try {
      const nonnegative = value => Number.isSafeInteger(value) && value >= 0;
      const rank = value => value === null || (Number.isSafeInteger(value) && value > 0);
      return snapshot?.version === 1 && snapshot.sessionId === session.sessionId &&
        snapshot.identity === ranklandIdentity(session.ranklandUrl) && ranklandIdentity(snapshot.url) === snapshot.identity &&
        typeof snapshot.ownName === "string" && snapshot.ownName.length > 0 && snapshot.ownName.length <= 200 &&
        typeof snapshot.targetKey === "string" && snapshot.targetKey.length > 0 && snapshot.targetKey.length <= 4096 &&
        rank(snapshot.rank) && nonnegative(snapshot.score) && (snapshot.penaltyMinutes === null || nonnegative(snapshot.penaltyMinutes)) &&
        Array.isArray(snapshot.ranks) && snapshot.ranks.length > 0 && snapshot.ranks.length <= 12 &&
        snapshot.ranks.every(item => typeof item.label === "string" && item.label.length <= 80 && rank(item.value)) &&
        Number.isFinite(snapshot.elapsedMs) && snapshot.elapsedMs >= 0 && typeof snapshot.running === "boolean" &&
        Number.isSafeInteger(snapshot.observedAt) && snapshot.observedAt > 0 && snapshot.observedAt <= Date.now() + 5000;
    } catch (_) { return false; }
  }
  async function readRanklandScore(session) {
    const url = session.ranklandUrl || null;
    if (!url) return {state: "not_configured", snapshot: null, url};
    if (session.startAt === null || session.state === "prepared") return {state: "not_started", snapshot:null, url};
    const key = "rankland-score-v1:" + session.sessionId + ":" + ranklandIdentity(url);
    const saved = (await browser.storage.local.get(key))[key];
    const cached = validRanklandScore(saved, session) ? saved : null;
    const fallback = (reason, state = "unavailable") => ({state: cached ? "cached" : state, snapshot: cached, reason, url});
    const tabs = await matchingRanklandTabs(url, session.sessionId);
    if (!tabs.length) return fallback("TAB_CLOSED");
    if (tabs.length !== 1) return fallback("MULTIPLE_TABS", "attention");
    let deadline;
    try {
      const query = async () => {
        const message = {type: "vp.rankland.snapshot", sessionId: session.sessionId, expectedUrl: url, durationMs:session.durationMs};
        try { return await browser.tabs.sendMessage(tabs[0].id, message); }
        catch (_) {
          const frames = await browser.scripting.executeScript({target: {tabId: tabs[0].id}, files: ["rankland-protocol.js", "rankland-content.js"]});
          if (frames.some(frame => frame.error)) throw new Error("BRIDGE_UNAVAILABLE");
          return browser.tabs.sendMessage(tabs[0].id, message);
        }
      };
      const result = await Promise.race([query(), new Promise((_, reject) => {
        deadline = setTimeout(() => reject(new Error("BRIDGE_UNAVAILABLE")), 3000);
      })]);
      if (!result?.ready) return fallback(result?.reason || "PAGE_NOT_READY");
      if (!validRanklandScore(result.snapshot, session) || Date.now() - result.snapshot.observedAt > 15000) return fallback("SNAPSHOT_MISMATCH");
      const {version, sessionId, identity, targetKey, ownName, rank, ranks, score, penaltyMinutes, elapsedMs, running, observedAt} = result.snapshot;
      const snapshot = {version, sessionId, url, identity, targetKey, ownName, rank, ranks, score, penaltyMinutes, elapsedMs, running, observedAt};
      await browser.storage.local.set({[key]: snapshot});
      await rememberRanklandUrl(result.snapshot.url);
      return {state: "live", snapshot, url};
    } catch (_) { return fallback("BRIDGE_UNAVAILABLE"); }
    finally { clearTimeout(deadline); }
  }
  async function ranklandScore(sessionId) {
    const session = await native("inspect_session", {sessionId});
    const key = JSON.stringify([sessionId, session.ranklandUrl || null]);
    if (!readingRanklandScores.has(key)) {
      const task = (async () => {
        const result = await readRanklandScore(session);
        const statusKey = "rankland-sync-status:" + sessionId;
        const status = (await browser.storage.local.get(statusKey))[statusKey];
        return {...result, ...(status?.identity === (session.ranklandUrl ? ranklandIdentity(session.ranklandUrl) : null) ? {syncStatus:status} : {})};
      })().finally(() => readingRanklandScores.delete(key));
      readingRanklandScores.set(key, task);
    }
    return readingRanklandScores.get(key);
  }
  function native(method, args = {}) {
    return new Promise((resolve, reject) => {
      const id = crypto.randomUUID();
      let port;
      try { port = browser.runtime.connectNative(HOST); }
      catch (_) { reject(new Error("NATIVE_HELPER_UNAVAILABLE")); return; }
      const task = {id, method, httpTabId: args.httpTabId, finished: false};
      const finish = (error, result) => {
        if (task.finished) return;
        task.finished = true;
        clearTimeout(deadline);
        try { port.disconnect(); } catch (_) { /* Already exited. */ }
        if (error) reject(error); else resolve(result);
      };
      const deadline = setTimeout(() => finish(new Error(method === "qoj_submit" ? "SUBMISSION_OUTCOME_UNKNOWN" : "TASK_TIMEOUT")), 180000);
      port.onMessage.addListener(async message => {
        if (message.id !== id || task.finished) return;
        if (message.type === "http.request") {
          let reply;
          try { reply = {response: await VpTransport.http(message.request, task)}; }
          catch (error) { reply = {error: {code: /^[A-Z_]+$/.test(error.message) ? error.message : "BROWSER_HTTP_FAILED", message: "Browser request could not be confirmed"}}; }
          if (!task.finished) {
            try { port.postMessage({type: "http.response", id, requestId: message.requestId, ...reply}); }
            catch (_) { finish(new Error("NATIVE_HELPER_DISCONNECTED")); }
          }
        } else if (message.type === "result") {
          if (message.ok) finish(null, {...message.result, helperPid: message.pid, nativePortClosed: true});
          else {
            const error = new Error(message.error?.message || "Native task failed");
            error.code = message.error?.code || "NATIVE_ERROR";
            finish(error);
          }
        }
      });
      port.onDisconnect.addListener(() => { if (!task.finished) finish(new Error(method === "qoj_submit" ? "SUBMISSION_OUTCOME_UNKNOWN" : "NATIVE_HELPER_UNAVAILABLE")); });
      try { port.postMessage({type: "task", id, method, args}); }
      catch (error) { finish(error); }
    });
  }
  async function openWorkbench() {
    const url = browser.runtime.getURL("ui.html");
    const tab = (await browser.tabs.query({url}))[0];
    return tab ? browser.tabs.update(tab.id, {active: true}) : browser.tabs.create({url});
  }
  async function openBoundSession(session, {prepare, active}) {
    const url = new URL(browser.runtime.getURL("ui.html"));
    url.searchParams.set("session", session.sessionId);
    if (prepare) { url.searchParams.set("resources", "1"); url.searchParams.set("prepare", "1"); }
    url.hash = prepare ? "#jury/contest/" + session.sessionId : "#home";
    const tab = (await browser.tabs.query({})).find(item => {
      try { const found = new URL(item.url); return found.origin === url.origin && found.pathname === url.pathname && found.searchParams.get("session") === session.sessionId; }
      catch (_) { return false; }
    });
    if (tab && !prepare) {
      try {
        const response = await browser.tabs.sendMessage(tab.id, {type:"vp.qoj.started", sessionId:session.sessionId});
        if (response?.handled) return browser.tabs.update(tab.id, {active});
      } catch (_) { /* A stale workbench can be restored from the durable session. */ }
    }
    return tab ? browser.tabs.update(tab.id, {url:url.href, active}) : browser.tabs.create({url:url.href, active});
  }
  const qojLifecycle = VpQojLifecycle.create({native:(...args) => native(...args), openSession:openBoundSession});
  const resourcePreparationJobs = new Map();
  function resourceRequestCid(message, sender) {
    const cid = String(message?.cid || ""), url = new URL(sender.url || "about:blank");
    const match = url.pathname.match(/^\/contest\/(\d+)\/?$/);
    if (sender.id !== browser.runtime.id || !Number.isInteger(sender.tab?.id) || sender.frameId !== 0 ||
        url.origin !== "https://qoj.ac" || !/^\d{1,20}$/.test(cid) || !match || match[1] !== cid) {
      throw Object.assign(new Error("请从对应的 QOJ 比赛页面准备题目文件。"), {code: "RESOURCE_SENDER_MISMATCH"});
    }
    return cid;
  }
  async function resourceContest(cid, tabId) {
    const tab = await browser.tabs.get(tabId), url = new URL(tab.url || "about:blank");
    if (url.origin !== "https://qoj.ac" || !new RegExp("^/contest/" + cid + "/?$").test(url.pathname)) throw new Error("比赛页面已改变，请重新打开准备入口。");
    const contest = await native("qoj_contest", {contestId: cid, httpTabId: tabId});
    if (String(contest.id) !== cid || typeof contest.account !== "string" || !contest.account || !Array.isArray(contest.problems) || !contest.problems.length ||
        contest.problems.some(problem => !/^\d{1,20}$/.test(String(problem.id)))) throw new Error("请先在 QOJ 登录并确认比赛题表可见。");
    return contest;
  }
  function resourceSessions(sessions, cid, account) {
    return sessions.filter(session => String(session.contestId) === cid &&
      typeof session.account === "string" && session.account.toLowerCase() === account.toLowerCase() &&
      ["prepared", "running"].includes(session.state)).sort((a, b) => Number(b.state === "prepared") - Number(a.state === "prepared"));
  }
  function resourceCacheReady(entry) {
    return entry?.status === "ready" && ["samples", "attachment"].includes(entry.kind) &&
      /^[a-f0-9]{64}$/.test(entry.resourceId || "") && /^[a-f0-9]{64}$/.test(entry.sha256 || "") &&
      Number.isSafeInteger(entry.totalBytes) && entry.totalBytes > 0 && entry.totalBytes <= 64 * 1024 * 1024 &&
      !(entry.sampleSource === "inline-statement" && (entry.interactiveHint === true || entry.lastAttempt?.interactiveHint === true));
  }
  async function resourceProgress(job) {
    const progress = {type: "vp.resources.progress", jobId: job.jobId, cid: job.cid, sessionId: job.sessionId,
      done: job.done, total: job.total, ready: job.ready, unknown: job.unknown};
    await Promise.allSettled([...job.tabs].map(async tabId => {
      const tab = await browser.tabs.get(tabId), url = new URL(tab.url || "about:blank");
      if (url.origin === "https://qoj.ac" && new RegExp("^/contest/" + job.cid + "/?$").test(url.pathname)) {
        await browser.tabs.sendMessage(tabId, progress, {frameId: 0});
      }
    }));
  }
  async function runResourcePreparation(job, contest, tabId) {
    const sessions = (await native("list_sessions")).sessions || [];
    let session = resourceSessions(sessions, job.cid, contest.account)[0];
    if (!session) {
      const title = String(contest.name || "").replace(/\s+-\s+(?:比赛主页\s+-\s+比赛|Dashboard\s+-\s+Contest)\s+-\s+QOJ\.ac\s*$/iu, "").trim();
      session = await native("create_session", {contestId: job.cid, account: contest.account, title: title || "QOJ Contest " + job.cid, durationMs: 18000000});
      await browser.storage.local.set({sessions: (await native("list_sessions")).sessions});
    }
    job.sessionId = session.sessionId;
    const manifest = await native("resource_manifest", {sessionId: session.sessionId});
    if (manifest.origin !== "https://qoj.ac" || String(manifest.contestId) !== job.cid ||
        String(manifest.account || "").toLowerCase() !== contest.account.toLowerCase() || !Array.isArray(manifest.problems)) throw new Error("资源清单与当前账号或比赛不一致。");
    const cached = new Map(manifest.problems.map(entry => [entry.problemId, entry]));
    await resourceProgress(job);
    for (const problem of contest.problems) {
      const id = String(problem.id), previous = cached.get(id);
      if (resourceCacheReady(previous)) job.ready++;
      else {
        try {
          const interactiveHint = problem.interactive === true || /interactive|交互/i.test(problem.typeLabel || "") ||
            previous?.interactiveHint === true || previous?.lastAttempt?.interactiveHint === true;
          const entry = await native("prepare_resource", {sessionId: session.sessionId, problemId: id, interactiveHint, httpTabId: tabId});
          if (entry.problemId !== id) throw new Error("资源题号不一致。");
          if (resourceCacheReady(entry)) job.ready++;
          if (!resourceCacheReady(entry) || entry.lastAttempt?.status === "unknown") job.unknown++;
        } catch (_) {
          // The backend preserves any previous verified object. A failed GET
          // cannot establish absence and never invokes a VP/submit action.
          if (resourceCacheReady(previous)) job.ready++;
          job.unknown++;
        }
      }
      job.done++;
      await resourceProgress(job);
    }
    return {jobId: job.jobId, cid: job.cid, sessionId: job.sessionId, done: job.done, total: job.total, ready: job.ready, unknown: job.unknown};
  }
  async function prepareResourceContest(message, sender) {
    const cid = resourceRequestCid(message, sender), contest = await resourceContest(cid, sender.tab.id);
    const key = cid + ":" + contest.account.toLowerCase();
    let job = resourcePreparationJobs.get(key);
    if (!job) {
      job = {jobId: crypto.randomUUID(), cid, tabs: new Set(), sessionId: null, done: 0, total: contest.problems.length, ready: 0, unknown: 0};
      resourcePreparationJobs.set(key, job);
      job.promise = runResourcePreparation(job, contest, sender.tab.id).finally(() => {
        if (resourcePreparationJobs.get(key) === job) resourcePreparationJobs.delete(key);
      });
    }
    job.tabs.add(sender.tab.id);
    return job.promise;
  }
  async function openResourceContest(message, sender) {
    const cid = resourceRequestCid(message, sender), contest = await resourceContest(cid, sender.tab.id);
    const sessions = resourceSessions((await native("list_sessions")).sessions || [], cid, contest.account);
    const session = message.sessionId ? sessions.find(item => item.sessionId === message.sessionId) : sessions[0];
    if (!session) throw new Error("请先准备这场比赛的题目文件。");
    const url = new URL(browser.runtime.getURL("ui.html"));
    url.searchParams.set("session", session.sessionId); url.searchParams.set("resources", "1");
    const base = new URL(browser.runtime.getURL("ui.html"));
    const tab = (await browser.tabs.query({})).find(item => {
      try { const found = new URL(item.url); return found.protocol === base.protocol && found.hostname === base.hostname && found.pathname === base.pathname; } catch (_) { return false; }
    });
    const opened = tab ? await browser.tabs.update(tab.id, {url: url.href, active: true}) : await browser.tabs.create({url: url.href});
    return {cid, sessionId: session.sessionId, tabId: opened.id};
  }
  async function ranklandTab(session, activate) {
    if (!session.ranklandUrl) throw new Error("请先为本次会话配置 RankLand 比赛链接。");
    if (!session.startAt) throw new Error("请先开始本次会话。");
    const target = new URL(session.ranklandUrl);
    if (target.origin !== "https://vp.xcpc.link" && !["http://127.0.0.1", "http://localhost"].some(prefix => target.origin.startsWith(prefix + ":"))) throw new Error("RANKLAND_ORIGIN_DENIED");
    const identity = ranklandIdentity(target.href);
    if (!openingRankland.has(identity)) {
      const opening = (async () => {
        const matches = await matchingRanklandTabs(session.ranklandUrl, session.sessionId);
        if (matches.length > 1) throw new Error("同一场 VP 打开了多个榜单页，请保留一个后再继续，以免原站存档互相覆盖。");
        if (matches[0]) return matches[0];
        const created = await browser.tabs.create({url: await restoredRanklandUrl(session.ranklandUrl), active: false});
        // Keep the coalescing promise until Tab.url has the intended identity.
        // tabs.create can resolve while a new tab still reports about:blank.
        for (let n = 0; n < 100; n++) {
          const current = await browser.tabs.get(created.id);
          try { if (ranklandIdentity(current.url) === identity) return current; } catch (_) { /* Initial blank document. */ }
          await VpTransport.pause(100);
        }
        throw new Error("榜单正在打开，请等待页面加载后再试。");
      })();
      openingRankland.set(identity, opening);
      opening.finally(() => openingRankland.delete(identity)).catch(() => {});
    }
    const tab = await openingRankland.get(identity);
    return activate ? browser.tabs.update(tab.id, {active: true}) : tab;
  }
  async function performSync(sessionId, open = false) {
    let session = await native("inspect_session", {sessionId});
    if (!session.ranklandUrl) return {state: "not_configured", synced: 0, message: "请先配置这场 VP 的 RankLand 比赛链接。"};
    if (session.state === "archived" || session.startAt == null || session.startAt > Date.now())
      return {state:"inactive",synced:0,message:"比赛尚未开始或已归档。"};
    const autoKey = "rankland-auto-sync:" + sessionId;
    if (open) await browser.storage.local.set({[autoKey]:true});
    const auto = open || (await browser.storage.local.get(autoKey))[autoKey] === true;
    if(!auto) return {state:"inactive",synced:0,message:"外部榜单自动同步未开启。"};
    const refreshed = open ? await providerRead("qoj_submissions", {sessionId, refresh:true}) : null;
    if (auto) session = await native("prepare_rankland", {sessionId});
    const incomplete = refreshed?.coverage?.complete === false || session.lastHistoryRefreshComplete === false;
    const plan = await native("rankland_plan", {sessionId});
    if (!open && plan.planToken && session.ranklandSyncedPlanToken===plan.planToken) {
      const previous=(await browser.storage.local.get("rankland-sync-status:"+sessionId))["rankland-sync-status:"+sessionId];
      return {...previous,state:plan.pendingCount || plan.blockedCount || incomplete ? "waiting":"ready",
        pending:plan.pendingCount || 0,blocked:plan.blockedCount || 0,needsRefresh:incomplete,
        url:session.ranklandUrl,identity:ranklandIdentity(session.ranklandUrl),observedAt:Date.now()};
    }
    let tab;
    const matches = await matchingRanklandTabs(session.ranklandUrl, session.sessionId);
    if (matches.length > 1) return {state: "attention", synced: 0, message: "同一场 VP 打开了多个榜单页。请保留一个，避免原站的多个页面互相覆盖进度。"};
    if (auto) tab = await ranklandTab(session, false);
    else {
      tab = matches[0];
    }
    if (!tab) return {state: "waiting_for_scoreboard", synced: 0, message: "判定已保留，打开这场 VP 的榜单后继续同步。"};
    let ready, teamPrepared = false;
    const recovering = new URL(tab.url).searchParams.get("qoj-vp-transfer") === sessionId;
    if (recovering) ready = {ready:true};
    for (let n = 0; !recovering && n < 80; n++) {
      try {
        ready = await browser.tabs.sendMessage(tab.id, {type: "vp.rankland.ready", sessionId, expectedUrl: session.ranklandUrl, durationMs:session.durationMs});
        if (ready?.reason === 'TEAM_REQUIRED' && !teamPrepared) {
          teamPrepared = true;
          ready = await browser.tabs.sendMessage(tab.id, {type: "vp.rankland.prepare", sessionId,
            expectedUrl: session.ranklandUrl, teamName: session.account, durationMs:session.durationMs});
        }
        if (ready?.ready || (ready?.reason && !['CONTEST_LOADING', 'STORAGE_NOT_READY', 'TEAM_REQUIRED'].includes(ready.reason))) break;
      } catch (_) { /* Navigating. */ }
      if (n === 15) {
        const frames = await browser.scripting.executeScript({target: {tabId: tab.id}, files: ["rankland-protocol.js", "rankland-content.js"]});
        if (frames.some(frame => frame.error)) throw new Error("RANKLAND_BRIDGE_LOAD_FAILED");
      }
      await VpTransport.pause(150);
    }
    // A finished replay has no record form. Its validated v2 archive can still
    // receive a managed projection while the replay document is unloaded.
    if (!ready?.ready && ready?.reason !== "RECORD_FORM_CHANGED") {
      const reasons = {
        TEAM_REQUIRED: "请在 RankLand 加入我的队伍后再同步，已确认的判定仍保留。",
        TEAM_NAME_REQUIRED: "请先在工作台读取比赛并确认 QOJ 登录账号，再同步榜单。",
        TEAM_FORM_ALREADY_OPEN: "请先完成 RankLand 已打开的队伍信息窗口，再同步。",
        TEAM_GUARD_BLOCKED: "请只保留这场 VP 的一个 RankLand 页面，再同步。",
        TEAM_STATE_CHANGED: "RankLand 队伍或页面已改变，请核对原站后再同步。",
        TEAM_FORM_CHANGED: "RankLand 加入队伍表单不可用，请在原站加入我的队伍后再同步。",
        TEAM_SETUP_NOT_CONFIRMED: "RankLand 尚未确认加入队伍，请核对原站后再同步。",
        TEAM_SETUP_FAILED: "RankLand 队伍准备未完成，请核对原站后再同步。",
        START_OFFSET_OUT_OF_RANGE: "本地 VP 进度已达到 RankLand 比赛时长，请核对两边比赛与开始时间。",
        SOURCE_LOAD_ERROR: "RankLand 比赛加载失败，请在原站重试；已确认的判定仍保留。",
        RECORD_FORM_CHANGED: "RankLand 记录提交表单不可用，请在原站核对；已确认的判定仍保留。",
        STORAGE_FORMAT_CHANGED: "RankLand 存档格式发生变化，请先核对原站存档。",
        SESSION_MISMATCH: "RankLand 页面与本次 VP 不一致，请从工作台重新打开。"
      };
      return {state: "page_not_ready", synced: 0, reason: ready?.reason || 'BRIDGE_NOT_READY',
        message: reasons[ready?.reason] || "RankLand 页面尚未就绪，已确认的判定仍保留。"};
    }
    if (!recovering) {
      const current = await browser.tabs.get(tab.id);
      if (ranklandIdentity(current.url) === ranklandIdentity(session.ranklandUrl)) await rememberRanklandUrl(current.url);
    }
    try {
      const delivered = await VpRanklandTransfer.sync({session, plan, tabId:tab.id});
      const acknowledgements = (plan.allItems || []).map(item => ({queueId:item.queueId, revision:item.revision, state:"synced"}));
      const ack = await native("rankland_ack_batch", {sessionId, acknowledgements, planToken:plan.planToken});
      const pending = plan.pendingCount || 0, blocked = plan.blockedCount || 0;
      const status = {state:ack.accepted ? pending || blocked || incomplete ? "waiting" : "ready" : "waiting",
        synced:delivered.synced, pending, blocked, observedAt:Date.now(), url:session.ranklandUrl,
        identity:ranklandIdentity(session.ranklandUrl),
        needsRefresh:incomplete,
        message:!ack.accepted ? "判定又有更新，下一次同步将继续补齐。" : incomplete ?
          "已同步现有判定；QOJ 暂未完整更新，稍后自动重试。" : pending || blocked ?
          `榜单已更新，${pending} 条待判或待核实${blocked ? `，${blocked} 条等待同题较早提交` : ""}；判定后自动补齐。` : "已确认的判定均已同步。"};
      await browser.storage.local.set({["rankland-sync-status:" + sessionId]:status});
      return status;
    } catch (error) {
      const messages = {
        RANKLAND_UNOWNED_CONFLICT:"原站已有相同的手工记录，无法确认归属；请先核对。",
        RANKLAND_OWNERSHIP_CONFLICT:"原站已同步记录被修改或重置，已保留备份，请先核对。",
        RANKLAND_JOURNAL_CONFLICT:"上次同步之后存档发生变化，已保留两份记录，请先核对。",
        RANKLAND_VERSION_CHANGED:"RankLand 页面版本已变化，判定已保留，需更新兼容适配。",
        RANKLAND_MULTIPLE_WRITERS:"请只保留这场比赛的一个 RankLand 页面，再同步。"
      };
      const status = {state:"attention",synced:0,pending:plan.pendingCount || 0,observedAt:Date.now(),
        url:session.ranklandUrl,identity:ranklandIdentity(session.ranklandUrl), reason:error.code || "RANKLAND_SYNC_FAILED",
        message:messages[error.code] || "榜单同步尚未确认，判定与恢复记录已保留，可再次同步。"};
      await browser.storage.local.set({["rankland-sync-status:" + sessionId]:status});
      return status;
    }
  }
  async function sync(sessionId, open=false) {
    const retryKey="rankland-sync-retry:"+sessionId;
    if(open) await browser.storage.local.set({[retryKey]:null});
    let result;
    try {result=await performSync(sessionId,open);}
    catch(error) {
      // Persist failures even before the transfer starts (e.g. QOJ is offline).
      const session=await native("inspect_session",{sessionId}).catch(()=>null);
      result={state:"retrying",synced:0,reason:error.code || "SYNC_UNAVAILABLE",
        message:"暂时无法同步；已有判定保留，稍后重试。",url:session?.ranklandUrl,
        identity:session?.ranklandUrl ? ranklandIdentity(session.ranklandUrl):null};
      await saveSyncStatus(sessionId,result,retryKey);
      if(open) throw error;
      return result;
    }
    return saveSyncStatus(sessionId,result,retryKey);
  }
  async function saveSyncStatus(sessionId,result,retryKey) {
    const enabled=(await browser.storage.local.get("rankland-auto-sync:"+sessionId))["rankland-auto-sync:"+sessionId]===true;
    const session=await native("inspect_session",{sessionId}).catch(()=>null);
    let identity=null;
    try {identity=session?.ranklandUrl ? ranklandIdentity(session.ranklandUrl):null;} catch (_) {}
    // A previous target's in-flight export must not overwrite the new target's status/backoff.
    if(result.identity && result.identity!==identity) return {...result,enabled};
    result={...result,identity,url:session?.ranklandUrl,enabled,observedAt:Date.now()};
    const failed=["attention","retrying","page_not_ready","waiting_for_scoreboard"].includes(result.state);
    const previous=(await browser.storage.local.get(retryKey))[retryKey];
    const attempts=failed ? (previous?.attempts || 0)+1 : 0;
    const suspended=failed && /CONFLICT|MULTIPLE_WRITERS|VERSION_CHANGED|SCHEMA_CHANGED|STORAGE_FORMAT_CHANGED/.test(result.reason || "");
    await browser.storage.local.set({["rankland-sync-status:"+sessionId]:result,
      [retryKey]:{attempts,suspended,nextAt:failed ? Date.now()+Math.min(300000,30000*2**Math.min(attempts-1,4)):0}});
    return result;
  }
  async function autoSync(sessionId) {
    if(syncUnavailable(sessionId)) return;
    const key="rankland-auto-sync:"+sessionId;
    if((await browser.storage.local.get(key))[key]!==true) return;
    const retryKey="rankland-sync-retry:"+sessionId;
    const retry=(await browser.storage.local.get(retryKey))[retryKey];
    if(retry?.suspended || retry?.nextAt>Date.now()) return;
    await exclusiveSync(sessionId);
  }
  async function continueExports() {
    // Separate from Judger polling: finished contests can still have an
    // undelivered revision even after their final history pass succeeded.
    const stored=await browser.storage.local.get(null);
    const ids=Object.keys(stored).filter(key=>key.startsWith("rankland-auto-sync:") && stored[key]===true)
      .map(key=>key.slice("rankland-auto-sync:".length));
    await Promise.allSettled(ids.map(id=>autoSync(id)));
  }
  async function syncStatus(sessionId) {
    const session=await native("inspect_session",{sessionId});
    let identity=null;
    try {identity=session.ranklandUrl ? ranklandIdentity(session.ranklandUrl):null;} catch (_) {}
    const saved=(await browser.storage.local.get("rankland-sync-status:"+sessionId))["rankland-sync-status:"+sessionId];
    const enabled=(await browser.storage.local.get("rankland-auto-sync:"+sessionId))["rankland-auto-sync:"+sessionId]===true;
    return {...(saved?.identity===identity ? saved:{}),enabled,identity,url:session.ranklandUrl,observedAt:Date.now(),
      message:saved?.identity===identity && enabled ? saved.message : enabled ? "自动同步已开启。" : "外部榜单自动同步未开启。"};
  }
  const synchronizing = new Map();
  const syncOpening = new Map();
  const deletingSessions = new Map();
  const deletedSessions = new Set();
  function syncUnavailable(id) {
    if (deletedSessions.has(id)) return Object.assign(new Error("这场本地比赛已删除。"), {code: "SESSION_DELETED"});
    if (deletingSessions.has(id)) return Object.assign(new Error("正在等待榜单同步完成并删除这场本地比赛。"), {code: "SESSION_DELETING"});
    return null;
  }
  function exclusiveSync(id, open = false) {
    const blocked = syncUnavailable(id);
    if (blocked) return Promise.reject(blocked);
    if (synchronizing.has(id) && open && !syncOpening.get(id)) {
      // A background pass may have neither refreshed QOJ nor opened a board.
      // Joining it must not silently discard the user's explicit one-click action.
      return synchronizing.get(id).catch(() => {}).then(() => exclusiveSync(id, true));
    }
    if (!synchronizing.has(id)) {
      syncOpening.set(id, open);
      synchronizing.set(id, sync(id, open).finally(() => { synchronizing.delete(id); syncOpening.delete(id); }));
    }
    return synchronizing.get(id);
  }
  function deleteSession(args) {
    const id = args.sessionId;
    // Check each caller, including one joining an already confirmed deletion.
    if (args.confirmed !== true) return Promise.reject(Object.assign(new Error("请确认删除这场本地比赛。"), {code: "CONFIRMATION_REQUIRED"}));
    if (deletingSessions.has(id)) return deletingSessions.get(id);
    const blocked = syncUnavailable(id);
    if (blocked) return Promise.reject(blocked);
    const inFlight = synchronizing.get(id);
    // Install the barrier before starting asynchronous work. A refresh which
    // finishes later must not create another writer while deletion is pending.
    const deletion = Promise.resolve().then(async () => {
      try { await inFlight; } catch (_) { /* A failed sync does not prevent local deletion. */ }
      const result = await native("delete_session", args);
      if (result.deleted !== true || result.sessionId !== id) throw new Error("DELETE_NOT_CONFIRMED");
      // Keep this tombstone even if refreshing the browser cache fails. Late
      // qoj_submissions/qoj_submit responses can still request automatic sync.
      deletedSessions.add(id);
      await browser.storage.local.set({["rankland-auto-sync:"+id]:false});
      try { await browser.storage.local.set({sessions: (await native("list_sessions")).sessions}); }
      catch (_) { return {...result, sessionsRefreshFailed: true}; }
      return result;
    }).finally(() => deletingSessions.delete(id));
    deletingSessions.set(id, deletion);
    return deletion;
  }
  const providerReads = new Map();
  function providerRead(method, args) {
    if (method !== "qoj_contest" && !(method === "qoj_submissions" && args.refresh !== false)) return native(method, args);
    // An F5 creates a new UI context while the previous native task continues.
    // Join only identical reads; writes and local snapshots stay independent.
    const normalized = {...args};
    if (method === "qoj_submissions") normalized.refresh = true;
    const key = JSON.stringify([method, Object.keys(normalized).sort().map(name => [name, normalized[name]])]);
    if (!providerReads.has(key)) {
      const pending = native(method, args).finally(() => providerReads.delete(key));
      providerReads.set(key, pending);
    }
    return providerReads.get(key);
  }
  const resolvingScoreboards = new Map();
  let helperInfo;
  function qojBoardUrl(contest, session) {
    const fallback = "https://qoj.ac/contest/" + session.contestId;
    try {
      const url = new URL(contest?.scoreboardUrl);
      if (url.origin !== "https://qoj.ac" || url.username || url.password || url.hash) return fallback;
      if (!["/contest/" + session.contestId + "/standings", "/results/QOJ" + session.contestId].includes(url.pathname.replace(/\/$/, ""))) return fallback;
      if ([...url.searchParams].some(([key, value]) => key !== "mode" || value !== "pc2") || [...url.searchParams].length > 1) return fallback;
      return url.href;
    } catch (_) { return fallback; }
  }
  async function resolveScoreboard(sessionId, refresh = false) {
    const snapshot = await native("session_snapshot", {sessionId});
    let {session, contest} = snapshot;
    const configured = current => ({source: "rankland", state: "configured", url: current.ranklandUrl, session: current});
    if (session.ranklandUrl) return configured(session);
    const fallback = reason => ({source: "qoj", state: "unavailable", reason, url: qojBoardUrl(contest, session), session});
    // Isolated guest suites never contact public providers implicitly.
    if (!helperInfo) helperInfo = native("hello").catch(error => { helperInfo = null; throw error; });
    if ((await helperInfo).fixture) return {...fallback("FIXTURE"), state: "unmatched"};
    if (!contest?.scoreboardUrl) {
      try { contest = await providerRead("qoj_contest", {contestId: session.contestId, sessionId}); }
      catch (_) { /* Cached title/problems and the original contest link remain usable. */ }
    }
    if (!contest) return fallback("CONTEST_UNAVAILABLE");
    const signature = JSON.stringify([session.account, session.contestId, session.durationMs, contest.name, contest.title, contest.titles,
      contest.scoreboardUrl, contest.problems?.map(problem => [problem.id, problem.label])]);
    const key = "scoreboard-source-v1:" + sessionId;
    const saved = (await browser.storage.local.get(key))[key];
    let result = !refresh && saved?.signature === signature && Date.now() - saved.checkedAt >= 0 &&
      Date.now() - saved.checkedAt < (["unavailable", "unverified"].includes(saved.result?.state) ? 30000 : 3600000) ? saved.result : null;
    if (!result) {
      result = await VpScoreboardSources.resolve(contest, session.durationMs);
      await browser.storage.local.set({[key]: {signature, checkedAt: Date.now(), result}});
    }
    // The native compare-and-set prevents a slow automatic match from
    // overwriting a setting edited in Jury while public metadata was loading.
    if (result.source === "rankland" && result.state === "matched") {
      session = await native("update_session", {sessionId, ranklandUrl: result.ranklandUrl,
        expectedRanklandUrl: null, expectedDurationMs: session.durationMs});
      if (session.ranklandUrl) {
        await browser.storage.local.set({sessions: (await native("list_sessions")).sessions});
        return {...result, ...configured(session), state: "matched"};
      }
      result = {...result, source: "qoj", state: "unverified", reason: "SESSION_CHANGED"};
    }
    const current = await native("inspect_session", {sessionId});
    if (current.ranklandUrl) return configured(current);
    return {...result, source: "qoj", url: qojBoardUrl(contest, current), session: current};
  }
  function scoreboardSource(args) {
    if (!resolvingScoreboards.has(args.sessionId)) {
      const task = resolveScoreboard(args.sessionId, args.refresh === true).finally(() => resolvingScoreboards.delete(args.sessionId));
      resolvingScoreboards.set(args.sessionId, task);
    }
    return resolvingScoreboards.get(args.sessionId);
  }
  const board = VpBoard.create({readSnapshot:sessionId=>native("session_snapshot",{sessionId}),
    sources:VpScoreboardSources,cache:VpBoardCache,engine:VpBoardEngine});
  async function dispatch(method, args) {
    if (method.startsWith("judger.")) {
      const action=method.slice(7);method=action==="prepare_resource"?action:"qoj_"+action;
    }
    if (method === "board.snapshot") return board.snapshot(args.sessionId, {refresh:args.refresh === true});
    if (method === "qoj.virtual.open") {
      const session = await native("inspect_session", args);
      if (session.qojVirtual?.mode !== "qoj-native") throw new Error("QOJ_VIRTUAL_NOT_BOUND");
      const url = "https://qoj.ac/contest/" + session.contestId + "/virtual/register";
      const existing = (await browser.tabs.query({url}))[0];
      return existing ? browser.tabs.update(existing.id, {active:true}) : browser.tabs.create({url,active:true});
    }
    if (method === "scoreboard.resolve") return scoreboardSource(args);
    if (method === "scoreboard.open") {
      const url = new URL(browser.runtime.getURL("ui.html"));
      url.searchParams.set("session", args.sessionId); url.hash="scoreboard";
      const tab=await browser.tabs.create({url:url.href,active:true});
      return {source:"local",tabId:tab.id,url:url.href};
    }
    if (method === "rankland.snapshot") return ranklandScore(args.sessionId);
    if (method === "rankland.open") {
      const blocked = syncUnavailable(args.sessionId);
      if (blocked) throw blocked;
      const session = await native("prepare_rankland", args);
      const changed = syncUnavailable(args.sessionId);
      if (changed) throw changed;
      const tab = await ranklandTab(session, true);
      await browser.storage.local.set({["rankland-auto-sync:"+args.sessionId]:true});
      exclusiveSync(args.sessionId).catch(() => {});
      return {tabId: tab.id, url: session.ranklandUrl};
    }
    if (method === "rankland.sync") return exclusiveSync(args.sessionId, true);
    if (method === "rankland.status") return syncStatus(args.sessionId);
    if (method === "rankland.stop") {
      await browser.storage.local.set({["rankland-auto-sync:"+args.sessionId]:false});
      // Finish an already-started transaction before reporting that sync stopped.
      await synchronizing.get(args.sessionId)?.catch(()=>{});
      return syncStatus(args.sessionId);
    }
    if (method === "delete_session") return deleteSession(args);
    if (!methods.has(method)) throw new Error("UNKNOWN_METHOD");
    const result = await providerRead(method, args);
    if (["create_session", "start_session", "finish_session", "archive_session", "update_session"].includes(method)) {
      await browser.storage.local.set({sessions: (await native("list_sessions")).sessions});
    }
    // Return judge results immediately; optional export has its own retries.
    if(args.sessionId && (["qoj_submit","qoj_reconcile","update_session","finish_session"].includes(method) ||
        method==="qoj_submissions" && args.refresh!==false)) autoSync(args.sessionId).catch(()=>{});
    return result;
  }
  browser.runtime.onMessage.addListener((message, sender) => {
    if (["vp.qoj.registration", "vp.qoj.prepare", "vp.qoj.startIntent", "vp.qoj.checkStart"].includes(message?.type)) {
      const action = {"vp.qoj.registration":"registration", "vp.qoj.prepare":"prepare", "vp.qoj.startIntent":"startIntent", "vp.qoj.checkStart":"check"}[message.type];
      return qojLifecycle[action](message, sender).then(result => ({ok:true,result}), error => ({ok:false,error:{code:error.code || "QOJ_VIRTUAL_FAILED",message:error.message}}));
    }
    if (["vp.resources.prepareContest", "vp.resources.openContest"].includes(message?.type)) {
      const action = message.type === "vp.resources.prepareContest" ? prepareResourceContest : openResourceContest;
      return action(message, sender).then(result => ({ok: true, result}), error => ({ok: false, error: {code: error.code || "RESOURCE_PREPARATION_FAILED", message: error.message}}));
    }
    if (sender.id === browser.runtime.id && message?.type === "vp.rankland.guard" && sender.tab?.id && message.expectedUrl) {
      try {
        if (ranklandIdentity(sender.url) !== ranklandIdentity(message.expectedUrl)) {
          ranklandGuardEvents.push({code: "SENDER_IDENTITY_MISMATCH", tabId: sender.tab.id, at: Date.now()});
          return Promise.resolve({allowed: false, code: "SENDER_IDENTITY_MISMATCH"});
        }
        return matchingRanklandTabs(message.expectedUrl, message.sessionId).then(matches => {
          const allowed = matches.length === 1 && matches[0].id === sender.tab.id;
          const result = {allowed, code: allowed ? "UNIQUE_WRITER" : "WRITER_COUNT_MISMATCH", tabCount: matches.length};
          ranklandGuardEvents.push({...result, tabId: sender.tab.id, matchingTabIds: matches.map(tab => tab.id), at: Date.now()});
          if (ranklandGuardEvents.length > 30) ranklandGuardEvents.shift();
          return result;
        });
      } catch (_) { return Promise.resolve({allowed: false, code: "IDENTITY_UNAVAILABLE"}); }
    }
    if (sender.id !== browser.runtime.id || !sender.url?.startsWith(browser.runtime.getURL(""))) return undefined;
    if (message?.type === "vp.diagnostics") return Promise.resolve({ok: true, result: {http: VpTransport.diagnostics(), ranklandGuards: ranklandGuardEvents.slice(-30)}});
    if (message?.type !== "vp.task") return undefined;
    return dispatch(message.method, message.args || {}).then(result => ({ok: true, result}), error => ({ok: false, error: {code: error.code || "BROWSER_ERROR", message: error.message}}));
  });
  browser.action.onClicked.addListener(() => openWorkbench().catch(() => {}));
  browser.runtime.onInstalled.addListener(() => openWorkbench().catch(() => {}));
  const registrationRequests = {urls:["https://qoj.ac/contest/*/virtual/register*"]};
  browser.webRequest?.onBeforeRequest?.addListener(details => { qojLifecycle.submitted(details).catch(() => {}); }, registrationRequests);
  browser.webRequest?.onCompleted?.addListener(details => { qojLifecycle.completed(details).catch(() => {}); }, registrationRequests);
  browser.alarms.create("vp-refresh", {periodInMinutes: 1});
  browser.alarms.onAlarm.addListener(async alarm => {
    if (alarm.name !== "vp-refresh") return;
    await qojLifecycle.resume().catch(() => {});
    let sessions;
    try { sessions = (await native("settlement_sessions")).sessions || []; } catch (_) { sessions=[]; }
    for (const session of sessions) {
      try {
        if (session.refreshRequired) await providerRead("qoj_submissions", {sessionId:session.sessionId, refresh:true});
        // Local Board reads this ledger independently of optional export.
      }
      catch (_) { /* The UI and durable queue expose failures on the next interaction. */ }
    }
    await continueExports();
  });
})();
