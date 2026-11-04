"use strict";
globalThis.VpRanklandTransfer = (() => {
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const fail = code => Object.assign(new Error(code), {code});
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const verdicts = {CORRECT:"AC", "WRONG-ANSWER":"WA", TIMELIMIT:"TLE", "RUN-ERROR":"RTE",
    "COMPILER-ERROR":"CE", "OUTPUT-LIMIT":"OLE", "NO-OUTPUT":"NOUT"};
  const protocol = VpRanklandProtocol;
  const identity = protocol.identity, archiveKey = protocol.archiveKey;
  function keys(session) {
    const suffix = session.sessionId + ":" + identity(session.ranklandUrl);
    return {ownership:"rankland-owned-v1:" + suffix, journal:"rankland-transfer-v1:" + suffix,
      backup:"rankland-before-transfer-v1:" + suffix};
  }
  function gateUrl(session) {
    const url = new URL("/", session.ranklandUrl);
    url.searchParams.set("qoj-vp-transfer", session.sessionId);
    return url.href;
  }
  // Executed in Firefox's isolated content world. Writes are possible only on
  // a separate, fully navigated setup document, never beside a live Vue writer.
  function page({expectedUrl, targetKey, gate, write, metadata}) {
    const protocol = globalThis.VpRanklandProtocol;
    if (gate ? location.href !== gate : protocol.identity(location.href) !== protocol.identity(expectedUrl)) return {error:"DOCUMENT_CHANGED"};
    const board = document.querySelector('[data-id="vp-ranklist-content"]');
    if (gate && (board || new URL(location.href).searchParams.has("contest"))) return {error:"REPLAY_STILL_RUNNING"};
    if (!gate && !board) return {error:"CONTEST_LOADING"};
    if (write) {
      const raw = localStorage.getItem(targetKey);
      if (!gate || raw !== write.before) return {error:"STORAGE_CHANGED"};
      localStorage.setItem(targetKey, write.after);
      return {raw:localStorage.getItem(targetKey)};
    }
    let state;
    try { state = protocol.read(localStorage, gate ? expectedUrl : location.href, {...metadata,allowEmpty:true}); }
    catch (_) { return {error:"RANKLAND_SCHEMA_CHANGED"}; }
    const labels = [...(board?.querySelectorAll(".srk-main > table thead .srk-problem-header") || [])]
      .map(header => header.querySelector(".srk--display-block:not(.srk-problem-stats)")?.textContent.trim() || "");
    const ownRow = [...(board?.querySelectorAll(".srk-user-name-text") || [])].some(node =>
      node.textContent.trim() === state.value.ownName && node.closest("tr")?.getClientRects().length);
    return {...state, labels, ownRow, url:gate ? expectedUrl : location.href};
  }
  async function execute(tabId, args) {
    // A newly navigated staging document may precede document_idle, and local
    // regression origins do not have the RankLand content-script match.
    await browser.scripting.executeScript({target:{tabId}, files:["rankland-protocol.js"]});
    const frames = await browser.scripting.executeScript({target:{tabId}, func:page, args:[args]});
    const value = frames[0]?.result;
    if (frames.length !== 1 || frames[0].error || !value) throw fail("RANKLAND_DOCUMENT_UNAVAILABLE");
    return value;
  }
  async function read(tabId, session, gate = null, metadata = {}) {
    for (let n = 0; n < 100; n++) {
      try {
        const result = await execute(tabId, {expectedUrl:session.ranklandUrl, targetKey:archiveKey(session.ranklandUrl), gate, metadata});
        if (!result.error) return result;
        if (!["DOCUMENT_CHANGED", "CONTEST_LOADING"].includes(result.error)) throw fail(result.error);
      } catch (error) {
        if (error.code && error.code !== "RANKLAND_DOCUMENT_UNAVAILABLE") throw error;
      }
      await pause(100);
    }
    throw fail("RANKLAND_LOAD_TIMEOUT");
  }
  async function guard(session, tabId, gate = null) {
    const all = await browser.tabs.query({});
    const matches = all.filter(tab => {
      try { return tab.url === gateUrl(session) || identity(tab.url) === identity(session.ranklandUrl); }
      catch (_) { return false; }
    });
    if (matches.length !== 1 || matches[0].id !== tabId || (gate ? matches[0].url !== gate : identity(matches[0].url) !== identity(session.ranklandUrl))) throw fail("RANKLAND_MULTIPLE_WRITERS");
  }
  async function legacyReceipts(session, plan) {
    const prefix = `rankland-receipt:${session.sessionId}:`, suffix = ":" + identity(session.ranklandUrl);
    const request = (plan.allItems || []).map(item => prefix + item.submissionId + suffix);
    const saved = await browser.storage.local.get(request);
    return (plan.allItems || []).flatMap(item => saved[prefix + item.submissionId + suffix] ?
      [{...saved[prefix + item.submissionId + suffix], sourceId:item.sourceId}] : []);
  }
  async function sync({session, plan, tabId}) {
    session = {...session};
    const original = (await browser.tabs.get(tabId)).url;
    if (original !== gateUrl(session)) {
      try { if (identity(original) !== identity(session.ranklandUrl)) throw fail("RANKLAND_SESSION_MISMATCH"); }
      catch (_) { throw fail("RANKLAND_SESSION_MISMATCH"); }
      session.ranklandUrl = original;
    }
    const metadata = await VpScoreboardSources.describeReplay(session.ranklandUrl);
    const bounds = {durationMs:metadata.durationMs,problemCount:metadata.problems.length};
    let targetKey = archiveKey(session.ranklandUrl);
    const key = keys(session), gate = gateUrl(session);
    const stored = await browser.storage.local.get([key.ownership,key.journal]);
    let ownership = stored[key.ownership] || null, journal = stored[key.journal] || null;
    let staged = (await browser.tabs.get(tabId)).url === gate;
    if (staged && journal?.expectedUrl && identity(journal.expectedUrl) === identity(session.ranklandUrl)) session.ranklandUrl = journal.expectedUrl;
    try {
      await guard(session, tabId, staged ? gate : null);
      let observation = await read(tabId, session, staged ? gate : null, bounds);
      let archive = observation.value;
      targetKey = observation.key;
      const kind = observation.kind;
      if (!archive.ownName.trim()) throw fail("RANKLAND_TEAM_REQUIRED");
      if (!staged && (observation.labels.length !== metadata.problems.length || observation.labels.some((label, index) =>
          label !== "?" && label.normalize("NFKC").toUpperCase() !== metadata.problems[index].label))) throw fail("RANKLAND_PROBLEM_MAPPING_CHANGED");
      // A lost reply is recovered from the write-ahead record, never by adding
      // the same submissions again. Any unrelated edit leaves both copies intact.
      if (journal) {
        if (journal.targetKey !== targetKey) throw fail("RANKLAND_JOURNAL_CONFLICT");
        if (same(archive.manual, journal.afterManual)) ownership = journal.afterOwnership;
        else if (!same(archive.manual, journal.beforeManual)) throw fail("RANKLAND_JOURNAL_CONFLICT");
      }
      const desired = (plan.items || []).map(item => {
        const problem = metadata.problems.find(problem => problem.label === String(item.problemLabel).normalize("NFKC").trim().toUpperCase());
        const result = /memory\s*limit|\bMLE\b/i.test(item.rawVerdict || "") ? "MLE" : verdicts[item.verdict];
        if (!problem || !result || !Number.isFinite(item.elapsedMs) || item.elapsedMs < 0 || item.elapsedMs >= metadata.durationMs) throw fail("RANKLAND_INVALID_PLAN");
        return {sourceId:item.sourceId, revision:item.revision, record:{problemIndex:problem.index,timeMs:item.elapsedMs,result}};
      });
      const legacy = ownership ? [] : await legacyReceipts(session, plan);
      let projected = VpRanklandProjection.reconcile({targetKey, archive, desired, ownership, legacy});
      const updatedCount = projected.updatedCount;
      if (projected.changed) {
        if (!staged) {
          await guard(session, tabId);
          await browser.tabs.update(tabId, {url:gate});
          staged = true;
        }
        observation = await read(tabId, session, gate, bounds);
        if (observation.key !== targetKey || observation.kind !== kind) throw fail("RANKLAND_SCHEMA_CHANGED");
        archive = observation.value;
        // pagehide saves the clock and any last manual entry before we rebase.
        projected = VpRanklandProjection.reconcile({targetKey, archive, desired, ownership, legacy});
        const after = protocol.encode(observation, projected.manual);
        journal = {version:1, targetKey, expectedUrl:session.ranklandUrl, sessionId:session.sessionId,
          beforeRaw:observation.raw, beforeManual:archive.manual, afterManual:projected.manual,
          afterOwnership:projected.ownership, startedAt:Date.now()};
        await browser.storage.local.set({[key.journal]:journal,[key.backup]:journal});
        await guard(session, tabId, gate);
        const written = await execute(tabId, {expectedUrl:session.ranklandUrl,targetKey,gate,write:{before:observation.raw,after}});
        if (written.error || written.raw !== after) throw fail("RANKLAND_STORAGE_CHANGED");
      }
      if (staged) {
        await guard(session, tabId, gate);
        await browser.tabs.update(tabId, {url:session.ranklandUrl});
        staged = false;
      }
      let verified = false;
      for (let n = 0; n < 100; n++) {
        const observed = await read(tabId, session, null, bounds);
        if (observed.key !== targetKey || observed.kind !== kind) throw fail("RANKLAND_SCHEMA_CHANGED");
        const actual = observed.value;
        if (!same(actual.manual, projected.manual)) throw fail("RANKLAND_READBACK_MISMATCH");
        if (observed.ownRow) { verified = true; break; }
        await pause(100);
      }
      if (!verified) throw fail("RANKLAND_ROW_NOT_READY");
      await guard(session, tabId);
      await browser.storage.local.set({[key.ownership]:projected.ownership});
      await browser.storage.local.remove(key.journal);
      return {synced:updatedCount, targetKey, ownership:projected.ownership};
    } finally {
      // A controlled import failure must not strand the user on the setup page.
      if (staged && (await browser.tabs.get(tabId).catch(() => null))?.url === gate) {
        await browser.tabs.update(tabId, {url:session.ranklandUrl}).catch(() => {});
      }
    }
  }
  return {sync, identity, archiveKey, gateUrl};
})();
