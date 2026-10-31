"use strict";
(() => {
  const HOST = "org.littledrinks.qoj_vp";
  const methods = new Set(["hello", "create_session", "start_session", "list_sessions", "inspect_session", "archive_session", "update_session",
    "qoj_contest", "qoj_problem_form", "qoj_samples", "qoj_submit", "qoj_submissions", "qoj_reconcile", "rankland_queue", "rankland_ack", "prepare_rankland"]);
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
    let ready;
    for (let n = 0; n < 80; n++) {
      try { ready = await browser.tabs.sendMessage(tab.id, {type: "vp.rankland.ready", sessionId, expectedUrl: session.ranklandUrl}); if (ready?.ready) break; } catch (_) { /* Navigating. */ }
      if (n === 15) {
        const frames = await browser.scripting.executeScript({target: {tabId: tab.id}, files: ["rankland-content.js"]});
        if (frames.some(frame => frame.error)) throw new Error("RANKLAND_BRIDGE_LOAD_FAILED");
      }
      await VpTransport.pause(150);
    }
    if (!ready?.ready) return {state: "page_not_ready", synced: 0, message: "RankLand 页面尚未就绪，提交判定仍保留在同步队列。"};
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
      const tab = await browser.tabs.create({url: form.statementUrl, active: true});
      for (let n = 0; n < 100 && (await browser.tabs.get(tab.id)).status !== "complete"; n++) await VpTransport.pause(100);
      const loaded = await browser.tabs.get(tab.id);
      const active = (await browser.tabs.query({active: true, currentWindow: true}))[0];
      if (loaded.status !== "complete" || new URL(loaded.url).origin !== new URL(form.statementUrl).origin ||
          !new URL(loaded.url).pathname.startsWith(new URL(form.statementUrl).pathname)) throw new Error("题面尚未加载完成，请在原站题面页保存 PDF。");
      if (active?.id !== tab.id) throw new Error("题面已打开。请回到该题面页使用 Firefox 的打印 → 保存为 PDF。");
      if (typeof browser.tabs.saveAsPDF !== "function") throw new Error("请在题面页使用 Firefox 的打印 → 保存为 PDF。");
      return {method: "firefox-save-as-pdf", status: await browser.tabs.saveAsPDF({})};
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
