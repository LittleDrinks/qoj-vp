"use strict";
(() => {
  if (globalThis.__qojVpRankland) return;
  globalThis.__qojVpRankland = true;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = element => element && element.getClientRects().length && !element.disabled;
  function identity(raw) {
    const url = new URL(raw), q = url.searchParams;
    return JSON.stringify([url.origin, q.get("contest"), q.get("run"), q.get("rule") || "auto",
      Number(q.get("count") ?? 50), Number(q.get("ratio") ?? 20), q.get("at") || "null", Number(q.get("from") || 0)]);
  }
  function saved() {
    const query = new URL(location.href).searchParams;
    const run = query.get("run");
    if (!run) return null;
    const key = `RanklandVP2:${query.get("contest")}:${run}:${query.get("rule") || "auto"}:${Number(query.get("count") ?? 50)}:${Number(query.get("ratio") ?? 20)}:${query.get("at") || "null"}:${Number(query.get("from") || 0)}`;
    try {
      const value = JSON.parse(localStorage.getItem(key));
      if (value?.version !== 2 || !Array.isArray(value.manual)) return null;
      return {key, run, value};
    } catch (_) { return null; }
  }
  const same = (a, b) => a?.problemIndex === b?.problemIndex && a?.timeMs === b?.timeMs && a?.result === b?.result;
  const verdicts = {CORRECT: "AC", "WRONG-ANSWER": "WA", TIMELIMIT: "TLE", "RUN-ERROR": "RTE", "COMPILER-ERROR": "CE", "OUTPUT-LIMIT": "OLE", "NO-OUTPUT": "NOUT"};
  async function intro() {
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      const modal = [...document.querySelectorAll('.srk-ranklist-settings-intro-wrap')].find(visible);
      if (modal) {
        const button = [...modal.querySelectorAll('button')].find(item => visible(item) && item.textContent.trim() === 'OK');
        if (button) button.click();
      } else if (localStorage.getItem('StyledRanklistSettingsIntroRead') === 'true') return;
      await pause(100);
    }
    throw new Error("请先在 RankLand 页面关闭首次使用提示。");
  }
  function ownRow(name) {
    const cell = [...document.querySelectorAll('td')].find(item => item.textContent.trim() === name || [...item.querySelectorAll('*')].some(child => child.textContent.trim() === name));
    const row = cell?.closest('tr');
    if (!row) return null;
    const cells = [...row.cells], index = cells.indexOf(cell);
    return {score: cells[index + 1]?.textContent.trim() || null, visible: Boolean(row.getClientRects().length)};
  }
  function setValue(element, value, event) {
    if (!element || !visible(element)) throw new Error("RankLand 提交表单发生变化，请在原站核对。");
    element.value = String(value);
    element.dispatchEvent(new Event(event, {bubbles: true}));
  }
  async function deliver(sessionId, item, previous, expectedUrl, receiptKey) {
    if (new URL(location.href).searchParams.get('run') !== sessionId || identity(location.href) !== identity(expectedUrl)) throw new Error("RANKLAND_SESSION_MISMATCH");
    await intro();
    const before = saved();
    if (!before) throw new Error("RankLand 存档尚未就绪。");
    if (item.rejudge || item.state === "needs-review") return {state: "ambiguous", message: "QOJ 已重判，请在原站核对旧记录后处理。"};
    const problem = document.querySelector('select[aria-label="题目"]');
    const result = document.querySelector('select[aria-label="结果"]');
    if (!problem || !result) throw new Error("RankLand 表单不可用，请打开正在进行的 VP。");
    const escaped = String(item.problemLabel).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const label = new RegExp(`^${escaped}(?:[\\s.、:：-]|$)`, 'i');
    const option = [...problem.options].find(entry => label.test(entry.textContent.trim()));
    const mapped = /memory\s*limit|\bMLE\b/i.test(item.rawVerdict || "") ? "MLE" : verdicts[item.verdict];
    const elapsed = Number(item.elapsedMs);
    if (!option || !mapped || !Number.isFinite(elapsed) || elapsed < 0) return {state: "ambiguous", message: "题号、判定或提交时间无法可靠映射。"};
    const target = {problemIndex: Number(option.value), timeMs: Math.floor(elapsed / 60000) * 60000, result: mapped};
    const key = `rankland-receipt:${sessionId}:${item.submissionId}:${identity(expectedUrl)}`;
    if (key !== receiptKey) throw new Error("RANKLAND_RECEIPT_MISMATCH");
    const durable = (await browser.storage.local.get(key))[key];
    const old = durable || previous;
    const matches = before.value.manual.map((entry, index) => same(entry, target) ? index : -1).filter(index => index >= 0);
    if (old) {
      if (old.targetKey !== before.key || old.revision !== item.revision || !same(old.record, target)) return {state: "ambiguous", message: "来源判定或目标榜单已有变更，需要核对原站记录。"};
      if (same(before.value.manual[old.index], target) && matches.length === 1) return {state: "synced", receipt: {...old, observedAt: Date.now(), targetKey: before.key}, deduplicated: true};
      if (old.phase !== "sending") return {state: "ambiguous", message: "同步回执与原站存档不一致，请核对。"};
      // A previously interrupted click with no matching target is uncertain.
      return {state: "ambiguous", message: "上次同步结果未确认；保留记录并等待核对。"};
    }
    if (matches.length) return {state: "ambiguous", message: "原站已有同题同时间同判定的记录，但缺少来源回执。"};
    if (!before.value.running) return {state: "failed", message: "RankLand 回放已暂停，恢复播放后再同步。"};
    if (target.timeMs > before.value.elapsed) return {state: "failed", message: "RankLand 进度尚未到该提交时间。"};
    if (![...result.options].some(entry => entry.value === mapped)) return {state: "ambiguous", message: "原站暂不支持此判定。"};
    setValue(problem, option.value, 'change');
    setValue(result, mapped, 'change');
    setValue(document.querySelector('input[aria-label="提交时间（时）"]'), Math.floor(target.timeMs / 3600000), 'input');
    setValue(document.querySelector('input[aria-label="提交时间（分）"]'), Math.floor(target.timeMs / 60000) % 60, 'input');
    await pause(100);
    const button = [...document.querySelectorAll('button')].find(entry => visible(entry) && entry.textContent.trim() === '记录提交');
    if (!button) return {state: "failed", message: "RankLand 尚未允许记录该提交。"};
    const receipt = {targetKey: before.key, record: target, problemIndex: target.problemIndex,
      timeMs: target.timeMs, result: target.result, originalElapsedMs: elapsed, precision: 'minute',
      revision: item.revision, index: before.value.manual.length, phase: 'sending', observedAt: Date.now()};
    const guard = await browser.runtime.sendMessage({type: 'vp.rankland.guard', expectedUrl});
    if (!guard?.allowed) return {state: 'failed', reason: guard?.code || 'GUARD_UNAVAILABLE', message: '榜单写入检查未通过，请从工作台重新打开并只保留一个榜单页。'};
    await browser.storage.local.set({[key]: receipt});
    const lastGuard = await browser.runtime.sendMessage({type: 'vp.rankland.guard', expectedUrl});
    if (!lastGuard?.allowed) {
      await browser.storage.local.remove(key);
      return {state: 'failed', reason: lastGuard?.code || 'GUARD_UNAVAILABLE', message: '榜单页面已改变，已停止同步；请重新打开并只保留一个页面。'};
    }
    button.click(); // Exactly one dispatch. Timeout never repeats this click.
    for (let n = 0; n < 100; n++) {
      await pause(100);
      const current = saved();
      if (current?.value.manual.length === receipt.index + 1 && same(current.value.manual[receipt.index], target) && ownRow(current.value.ownName)?.visible) {
        receipt.phase = 'observed';
        receipt.observedAt = Date.now();
        await browser.storage.local.set({[key]: receipt});
        return {state: "synced", receipt, ownRow: ownRow(current.value.ownName)};
      }
    }
    return {state: "ambiguous", receipt, message: "已操作原站表单，但未取得一致回执；不会自动重复。"};
  }
  let busy = false;
  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id) return undefined;
    if (message?.type === 'vp.rankland.ready') return Promise.resolve({ready: Boolean(message.expectedUrl && identity(location.href) === identity(message.expectedUrl) && saved() && document.querySelector('select[aria-label="题目"]')), run: saved()?.run});
    if (message?.type !== 'vp.rankland.deliver') return undefined;
    if (busy) return Promise.resolve({state: 'failed', message: '另一个同步任务仍在进行。'});
    busy = true;
    return deliver(message.sessionId, message.item, message.previous, message.expectedUrl, message.receiptKey).catch(error => ({state: 'failed', message: error.message})).finally(() => { busy = false; });
  });
  // Origin storage remains owned by the original application. Keep a separate
  // extension backup without writing its localStorage or private Vue state.
  setInterval(() => {
    const state = saved();
    if (state) browser.storage.local.set({[`rankland-backup:${state.key}`]: {...state, url: location.href, observedAt: Date.now()}}).catch(() => {});
  }, 5000);
})();
