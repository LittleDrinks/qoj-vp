"use strict";
globalThis.VpQojLifecycle = (() => {
  const PREFIX = "qoj-native-start:";
  const MAX_AGE = 24 * 60 * 60 * 1000;
  const RULES_PREFIX = "qoj-native-registration:";
  function page(raw) {
    try {
      const url = new URL(raw), match = url.pathname.match(/^\/contest\/(\d{1,20})(\/virtual\/register)?\/?$/);
      return url.origin === "https://qoj.ac" && match ? {cid:match[1], register:Boolean(match[2])} : null;
    } catch (_) { return null; }
  }
  function create({native, openSession, onStarted = async () => {}, storage = browser.storage.local, tabs = browser.tabs, clock = Date.now}) {
    const preparing = new Map(), checking = new Map(), confirmedStarts = new Set();
    function source(message, sender, register = false) {
      const found = page(sender?.url);
      if (sender?.id !== browser.runtime.id || sender.frameId !== 0 || !Number.isInteger(sender.tab?.id) ||
          !found || found.cid !== String(message?.cid) || register && !found.register) {
        throw Object.assign(new Error("请从 QOJ 的 VP 确认页进入。"), {code:"QOJ_VIRTUAL_SENDER_MISMATCH"});
      }
      return found;
    }
    async function refreshSessions() { await storage.set({sessions:(await native("list_sessions")).sessions}); }
    function checkedBinding(result, cid) {
      const session = result?.session, binding = session?.qojVirtual;
      if (!session?.sessionId || String(session.contestId) !== cid || !session.account ||
          binding?.mode !== "qoj-native" || binding.origin !== "https://qoj.ac" || String(binding.contestId) !== cid ||
          binding.account?.toLowerCase() !== session.account.toLowerCase()) throw new Error("QOJ 账号或比赛绑定未确认。");
      return session;
    }
    async function prepare(message, sender) {
      const {cid} = source(message, sender, true), key = sender.tab.id + ":" + cid;
      if (!preparing.has(key)) preparing.set(key, (async () => {
        const registrationPage = await registrationEvidence(message, sender);
        const result = await native("qoj_bind_virtual", {contestId:cid, httpTabId:sender.tab.id, ...(registrationPage ? {registrationPage} : {})});
        const session = checkedBinding(result, cid);
        await refreshSessions();
        // A preparation read can finish after native Start has been verified.
        // Reopening its old preparation URL would reload an active workbench
        // and interrupt the resource job already running there.
        if (!confirmedStarts.has(session.sessionId)) await openSession(session, {prepare:true, active:true});
        return {sessionId:session.sessionId, cid};
      })().finally(() => preparing.delete(key)));
      return preparing.get(key);
    }
    async function attempt(key, tabId) {
      let intent = (await storage.get(key))[key];
      if (!intent || clock() - intent.observedAt > MAX_AGE || clock() < intent.observedAt) return {state:"expired"};
      const current = page((await tabs.get(tabId)).url);
      if (!current || current.cid !== intent.cid) return {state:"page_changed"};
      if (!intent.sessionId) {
        if (!intent.registrationPage) {
          const rules = (await storage.get(RULES_PREFIX + tabId))[RULES_PREFIX + tabId];
          if (rules?.cid === intent.cid && clock() >= rules.observedAt && clock() - rules.observedAt <= MAX_AGE) {
            intent = {...intent, registrationPage:rules.registrationPage};
            await storage.set({[key]:intent});
          }
        }
        const binding = await native("qoj_bind_virtual", {contestId:intent.cid, httpTabId:tabId,
          ...(intent.registrationPage ? {registrationPage:intent.registrationPage} : {})});
        const session = checkedBinding(binding, intent.cid);
        intent = {...intent, sessionId:session.sessionId, account:session.account};
        await storage.set({[key]:intent});
      }
      const boundPage = page((await tabs.get(tabId)).url);
      if (!boundPage || boundPage.cid !== intent.cid) return {state:"page_changed"};
      const result = await native("qoj_confirm_virtual_start", {sessionId:intent.sessionId, httpTabId:tabId});
      const session = checkedBinding(result, intent.cid);
      if (session.sessionId !== intent.sessionId || session.account.toLowerCase() !== intent.account.toLowerCase()) throw new Error("QOJ 开始回执与准备的比赛不一致。");
      if (!["running", "finished"].includes(result.virtual?.state) || !Number.isSafeInteger(session.startAt) ||
          session.qojVirtual.startAt !== session.startAt) return {state:"waiting", sessionId:session.sessionId};
      confirmedStarts.add(session.sessionId);
      await refreshSessions();
      await onStarted(session);
      await openSession(session, {prepare:false, active:true});
      await storage.remove(key);
      await storage.remove(RULES_PREFIX + intent.tabId);
      return {state:"started", sessionId:session.sessionId, startAt:session.startAt};
    }
    async function confirm(key, tabId) {
      if (checking.has(key)) { const job = checking.get(key); job.again = true; job.tabId = tabId; return job.promise; }
      const job = {again:false, tabId};
      checking.set(key, job);
      job.promise = (async () => {
        let result, failure;
        do {
          job.again = false;
          failure = null;
          try { result = await attempt(key, job.tabId); }
          catch (error) {
            const saved = (await storage.get(key))[key];
            if (saved) await storage.set({[key]:{...saved, error:String(error.message || error).slice(0, 500)}});
            failure = error;
          }
        } while (job.again && result?.state !== "started");
        if (failure) throw failure;
        return result;
      })().finally(() => checking.delete(key));
      return job.promise;
    }
    const recording = new Map();
    async function registrationEvidence(message, sender) {
      const {cid} = source(message, sender, true), evidence = message.registrationPage;
      if (!evidence) return null;
      const found = page(evidence.url);
      if (!found?.register || found.cid !== cid || typeof evidence.html !== 'string' || evidence.html.length > 65536) {
        throw new Error('QOJ 确认页信息不完整。');
      }
      return {url:evidence.url, html:evidence.html};
    }
    async function registration(message, sender) {
      const evidence = await registrationEvidence(message, sender);
      if (evidence) {
        await storage.set({[RULES_PREFIX + sender.tab.id]:{cid:String(message.cid), observedAt:clock(), registrationPage:evidence}});
        const key = PREFIX + sender.tab.id, pending = (await storage.get(key))[key];
        if (pending?.cid === String(message.cid)) await confirm(key, sender.tab.id);
      }
      return {ready:Boolean(evidence)};
    }
    async function rememberIntent(cid, tabId, registrationPage) {
      const key = PREFIX + tabId;
      if (recording.has(key)) {
        await recording.get(key);
        return rememberIntent(cid, tabId, registrationPage);
      }
      if (!recording.has(key)) recording.set(key, (async () => {
        const saved = (await storage.get(key))[key];
        // Observation time only limits retries. QOJ supplies the contest start.
        if (!saved || saved.cid !== cid || clock() - saved.observedAt > MAX_AGE || clock() < saved.observedAt) {
          const rules = (await storage.get(RULES_PREFIX + tabId))[RULES_PREFIX + tabId];
          const evidence = registrationPage || (rules?.cid === cid && clock() >= rules.observedAt &&
            clock() - rules.observedAt <= MAX_AGE ? rules.registrationPage : null);
          await storage.set({[key]:{cid, tabId, observedAt:clock(), ...(evidence ? {registrationPage:evidence} : {})}});
        } else if (registrationPage && !saved.registrationPage) {
          await storage.set({[key]:{...saved, registrationPage}});
        }
      })().finally(() => recording.delete(key)));
      await recording.get(key);
      return key;
    }
    async function startIntent(message, sender) {
      const {cid} = source(message, sender, true);
      const key = await rememberIntent(cid, sender.tab.id, await registrationEvidence(message, sender));
      return confirm(key, sender.tab.id);
    }
    async function submitted(details) {
      const current = page(details.url);
      if (details.method !== "POST" || details.type !== "main_frame" || !current?.register || details.tabId < 0) return;
      // QOJ may submit its form through JavaScript, bypassing DOM submit events.
      // Observe that request without altering, replaying or waiting on its POST.
      await rememberIntent(current.cid, details.tabId);
    }
    async function checkTab(tabId, raw) {
      const current = page(raw);
      if (!current) return {state:"irrelevant"};
      await recording.get(PREFIX + tabId);
      const all = await storage.get(null);
      const matches = Object.entries(all).filter(([key, value]) => key.startsWith(PREFIX) && value?.cid === current.cid &&
        clock() >= value.observedAt && clock() - value.observedAt <= MAX_AGE);
      const exact = matches.find(([, value]) => value.tabId === tabId);
      const found = exact || (matches.length === 1 ? matches[0] : null);
      return found ? confirm(found[0], tabId) : {state:"idle"};
    }
    async function check(message, sender) { source(message, sender); return checkTab(sender.tab.id, sender.url); }
    async function completed(details) {
      const current = page(details.url);
      if (details.method !== "POST" || details.type !== "main_frame" || details.statusCode >= 400 || !current?.register || details.tabId < 0) return;
      return checkTab(details.tabId, details.url);
    }
    async function resume() {
      const all = await storage.get(null);
      if (!Object.keys(all).some(key => key.startsWith(PREFIX))) return;
      const opened = await tabs.query({url:"https://qoj.ac/contest/*"});
      for (const tab of opened) await checkTab(tab.id, tab.url).catch(() => {});
    }
    return {registration, prepare, startIntent, submitted, check, completed, resume};
  }
  return {create};
})();
