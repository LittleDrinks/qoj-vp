"use strict";
(() => {
  const HOST = "org.littledrinks.qoj_vp";
  const methods = new Set(["hello", "create_session", "start_session", "list_sessions", "inspect_session", "archive_session", "update_session",
    "qoj_contest", "qoj_problem_form", "qoj_samples", "qoj_submit", "qoj_submissions", "qoj_reconcile", "rankland_queue", "rankland_ack", "prepare_rankland",
    "resource_manifest", "prepare_resource", "resource_chunk"]);
  function ranklandIdentity(raw) {
    const url = new URL(raw), q = url.searchParams;
    return JSON.stringify([url.origin, q.get("contest"), q.get("run"), q.get("rule") || "auto",
      Number(q.get("count") ?? 50), Number(q.get("ratio") ?? 20), q.get("at") || "null", Number(q.get("from") || 0)]);
  }
  const openingRankland = new Map();
  const ranklandGuardEvents = [];
  async function matchingRanklandTabs(expectedUrl) {
    const identity = ranklandIdentity(expectedUrl);
    return (await browser.tabs.query({})).filter(item => {
      try { return ranklandIdentity(item.url) === identity; } catch (_) { return false; }
    });
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
        const matches = await matchingRanklandTabs(session.ranklandUrl);
        if (matches.length > 1) throw new Error("同一场 VP 打开了多个榜单页，请保留一个后再继续，以免原站存档互相覆盖。");
        if (matches[0]) return matches[0];
        const created = await browser.tabs.create({url: session.ranklandUrl, active: false});
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
  async function sync(sessionId, open = false) {
    const session = await native(open ? "prepare_rankland" : "inspect_session", {sessionId});
    if (!session.ranklandUrl) return {state: "not_configured", synced: 0, message: "请先配置这场 VP 的 RankLand 比赛链接。"};
    let tab;
    const matches = await matchingRanklandTabs(session.ranklandUrl);
    if (matches.length > 1) return {state: "attention", synced: 0, message: "同一场 VP 打开了多个榜单页。请保留一个，避免原站的多个页面互相覆盖进度。"};
    if (open) tab = await ranklandTab(session, false);
    else {
      tab = matches[0];
    }
    if (!tab) return {state: "waiting_for_scoreboard", synced: 0, message: "判定已保留，打开这场 VP 的榜单后继续同步。"};
    let ready, teamPrepared = false;
    for (let n = 0; n < 80; n++) {
      try {
        ready = await browser.tabs.sendMessage(tab.id, {type: "vp.rankland.ready", sessionId, expectedUrl: session.ranklandUrl});
        if (ready?.reason === 'TEAM_REQUIRED' && !teamPrepared) {
          teamPrepared = true;
          ready = await browser.tabs.sendMessage(tab.id, {type: "vp.rankland.prepare", sessionId,
            expectedUrl: session.ranklandUrl, teamName: session.account});
        }
        if (ready?.ready || (ready?.reason && !['CONTEST_LOADING', 'STORAGE_NOT_READY', 'TEAM_REQUIRED'].includes(ready.reason))) break;
      } catch (_) { /* Navigating. */ }
      if (n === 15) {
        const frames = await browser.scripting.executeScript({target: {tabId: tab.id}, files: ["rankland-content.js"]});
        if (frames.some(frame => frame.error)) throw new Error("RANKLAND_BRIDGE_LOAD_FAILED");
      }
      await VpTransport.pause(150);
    }
    if (!ready?.ready) {
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
    const queue = await native("rankland_queue", {sessionId});
    const results = [];
    let attention = "";
    for (const item of queue.items || []) {
      const receiptKey = `rankland-receipt:${sessionId}:${item.submissionId}:${ranklandIdentity(session.ranklandUrl)}`;
      const old = (await browser.storage.local.get(receiptKey))[receiptKey];
      const delivered = await browser.tabs.sendMessage(tab.id, {type: "vp.rankland.deliver", sessionId, expectedUrl: session.ranklandUrl, receiptKey, item, previous: old || null});
      if (delivered?.receipt) await browser.storage.local.set({[receiptKey]: {...delivered.receipt, revision: item.revision}});
      const state = delivered?.state || "failed";
      await native("rankland_ack", {sessionId, queueId: item.queueId, revision: item.revision, state,
        receipt: delivered?.receipt || null, error: delivered?.message || null});
      results.push({submissionId: item.submissionId, state, ...(delivered?.reason ? {reason: delivered.reason} : {})});
      if (state !== "synced") { attention = delivered?.message || "原站未确认同步，请核对榜单。"; break; }
    }
    const count = results.filter(item => item.state === "synced").length;
    return {state: attention ? "attention" : "ready", synced: count, results,
      message: attention || (count ? `已将 ${count} 条判定同步至原站。` : "已确认的判定均已同步。")};
  }
  const synchronizing = new Map();
  let htmlPdfBusy = false;
  function exclusiveSync(id, open = false) {
    if (!synchronizing.has(id)) synchronizing.set(id, sync(id, open).finally(() => synchronizing.delete(id)));
    return synchronizing.get(id);
  }
  async function dispatch(method, args) {
    if (method === "rankland.open") {
      const session = await native("prepare_rankland", args);
      const tab = await ranklandTab(session, true);
      exclusiveSync(args.sessionId).catch(() => {});
      return {tabId: tab.id, url: session.ranklandUrl};
    }
    if (method === "rankland.sync") return exclusiveSync(args.sessionId, true);
    if (method === "problem.pdf") {
      const form = await native("qoj_problem_form", args);
      const candidate = form.pdfCandidates?.[0];
      const url = typeof candidate === "string" ? candidate : candidate?.url;
      if (url) { await browser.tabs.create({url}); return {method: "original-pdf", url}; }
      if (htmlPdfBusy) throw new Error("请先完成当前题面的 PDF 保存。");
      htmlPdfBusy = true;
      const requestId = crypto.randomUUID();
      let tab, prepared = false, stylesInserted = false, cssRemoved = false, cleanup = null, result = null;
      try {
        tab = await browser.tabs.create({url: form.statementUrl, active: true});
        for (let n = 0; n < 100 && (await browser.tabs.get(tab.id)).status !== "complete"; n++) await VpTransport.pause(100);
        const assertPrintTab = async () => {
          const loaded = await browser.tabs.get(tab.id);
          const active = (await browser.tabs.query({active: true, currentWindow: true}))[0];
          if (loaded.status !== "complete" || new URL(loaded.url).origin !== new URL(form.statementUrl).origin ||
              !new URL(loaded.url).pathname.startsWith(new URL(form.statementUrl).pathname)) throw new Error("题面尚未加载完成，未导出 PDF。");
          if (active?.id !== tab.id) throw new Error("请保持新打开的题面页处于当前标签，再重新导出 PDF。");
        };
        await assertPrintTab();
        if (typeof browser.tabs.saveAsPDF !== "function") throw new Error("当前 Firefox 不支持题面 PDF 导出。");
        const frames = await browser.scripting.executeScript({target: {tabId: tab.id}, files: ["pdf-content.js"]});
        if (frames.some(frame => frame.error)) throw new Error("题面打印准备未能加载，未导出 PDF。");
        await browser.scripting.insertCSS({target: {tabId: tab.id}, files: ["pdf-print.css"], origin: "USER"});
        stylesInserted = true;
        const isolation = await browser.tabs.sendMessage(tab.id, {type: "vp.pdf.prepare", requestId,
          expectedUrl: form.statementUrl, problemLabel: form.problemLabel, problemName: form.problemName, stylesheetReady: true});
        if (!isolation?.ok) throw new Error("无法唯一识别题面正文，未导出 PDF。");
        prepared = true;
        await assertPrintTab();
        const status = await browser.tabs.saveAsPDF({headerLeft: "", headerCenter: "", headerRight: "",
          footerLeft: "", footerCenter: "", footerRight: ""});
        result = {method: "firefox-save-as-pdf", status, isolation};
        return result;
      } finally {
        try {
          if (tab) cleanup = await browser.tabs.sendMessage(tab.id, {type: "vp.pdf.restore", requestId});
        } catch (_) { /* A closed or navigated dedicated tab has discarded the prepared document. */ }
        if (stylesInserted) {
          try {
            await browser.scripting.removeCSS({target: {tabId: tab.id}, files: ["pdf-print.css"], origin: "USER"});
            cssRemoved = true;
          } catch (_) { /* Closed/navigated documents have no retained print CSS. */ }
        }
        htmlPdfBusy = false;
        if (prepared && (!cleanup?.ok || !cssRemoved)) {
          let remains = false;
          try {
            const current = await browser.tabs.get(tab.id);
            remains = new URL(current.url).origin === new URL(form.statementUrl).origin &&
              new URL(current.url).pathname.startsWith(new URL(form.statementUrl).pathname);
          } catch (_) { /* The dedicated tab has closed. */ }
          if (remains) throw new Error("题面打印清理未获确认，请关闭新开的题面页。");
        }
        if (result && cleanup) result.cleanup = {...cleanup, printStylesheetRemoved: cssRemoved};
      }
    }
    if (!methods.has(method)) throw new Error("UNKNOWN_METHOD");
    const result = await native(method, args);
    if (["create_session", "start_session", "archive_session", "update_session"].includes(method)) {
      await browser.storage.local.set({sessions: (await native("list_sessions")).sessions});
    }
    if (method === "qoj_submissions" || method === "qoj_submit") exclusiveSync(args.sessionId).catch(() => {});
    return result;
  }
  browser.runtime.onMessage.addListener((message, sender) => {
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
        return matchingRanklandTabs(message.expectedUrl).then(matches => {
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
  browser.alarms.create("vp-refresh", {periodInMinutes: 1});
  browser.alarms.onAlarm.addListener(async alarm => {
    if (alarm.name !== "vp-refresh") return;
    const sessions = (await browser.storage.local.get("sessions")).sessions || [];
    for (const session of sessions.filter(item => item.state === "running" && Date.now() < item.startAt + item.durationMs)) {
      try { await native("qoj_submissions", {sessionId: session.sessionId, refresh: true}); await exclusiveSync(session.sessionId); }
      catch (_) { /* The UI and durable queue expose failures on the next interaction. */ }
    }
  });
})();
