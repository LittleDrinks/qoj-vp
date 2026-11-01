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
  function scoreSnapshot(sessionId, expectedUrl) {
    let currentUrl;
    try {
      currentUrl = new URL(location.href);
      if (currentUrl.origin !== "https://vp.xcpc.link" || currentUrl.pathname !== "/" ||
          !sessionId || currentUrl.searchParams.get("run") !== sessionId ||
          !expectedUrl || identity(location.href) !== identity(expectedUrl)) {
        return {ready: false, reason: "SESSION_MISMATCH"};
      }
    } catch (_) { return {ready: false, reason: "SESSION_MISMATCH"}; }
    const board = document.querySelector('[data-id="vp-ranklist-content"]');
    if (!board) return {ready: false, reason: "CONTEST_LOADING"};
    const archive = saved();
    if (!archive) return {ready: false, reason: "STORAGE_NOT_READY"};
    const ownName = archive.value.ownName;
    if (typeof ownName !== "string" || !ownName.trim()) return {ready: false, reason: "TEAM_REQUIRED"};
    if (ownName.length > 80 || /[\x00-\x1f\x7f]/.test(ownName) ||
        !Number.isFinite(archive.value.elapsed) || archive.value.elapsed < 0 ||
        typeof archive.value.running !== "boolean") return {ready: false, reason: "STORAGE_FORMAT_CHANGED"};
    const candidates = [];
    for (const table of board.querySelectorAll("table.srk-main")) {
      for (const name of table.querySelectorAll(".srk-user-name-text")) {
        if (name.textContent.trim() !== ownName) continue;
        const row = name.closest("tr"), cell = name.closest("td");
        if (row && cell && row.closest("table") === table && row.getClientRects().length) candidates.push({table, row, cell});
      }
    }
    if (candidates.length !== 1) return {ready: false, reason: candidates.length ? "OWN_ROW_AMBIGUOUS" : "OWN_ROW_NOT_VISIBLE"};
    const {table, row, cell} = candidates[0], headers = [...(table.tHead?.rows[0]?.cells || [])], cells = [...row.cells];
    const nameIndex = cells.indexOf(cell), scoreIndex = nameIndex + 1, timeIndex = nameIndex + 2;
    const scoreLabel = headers[scoreIndex]?.textContent.trim() || "", timeLabel = headers[timeIndex]?.textContent.trim() || "";
    if (nameIndex < 1 || headers.length !== cells.length ||
        !/^(score|得分|分数|解题数|题数)$/i.test(scoreLabel) || !/^(time|时间|用时|罚时)$/i.test(timeLabel)) {
      return {ready: false, reason: "SCORE_COLUMNS_CHANGED"};
    }
    const integer = (text, minimum = 0) => {
      if (!/^\d+$/.test(text)) return null;
      const value = Number(text);
      return Number.isSafeInteger(value) && value >= minimum ? value : null;
    };
    const ranks = headers.flatMap((header, index) => header.classList.contains("srk-series-header") && index < nameIndex ?
      [{label: header.textContent.trim().slice(0, 80), value: integer(cells[index]?.textContent.trim() || "", 1)}] : []);
    const score = integer(cells[scoreIndex]?.textContent.trim() || "");
    const penaltyText = cells[timeIndex]?.textContent.trim() || "", penaltyMinutes = integer(penaltyText);
    if (!ranks.length || score === null || (penaltyMinutes === null && !/^(?:-|—)$/.test(penaltyText))) {
      return {ready: false, reason: "SCORE_VALUES_CHANGED"};
    }
    return {ready: true, reason: "READY", snapshot: {version: 1, sessionId, url: currentUrl.href,
      identity: identity(currentUrl.href), targetKey: archive.key, ownName, rank: ranks[0].value,
      ranks, score, penaltyMinutes, elapsedMs: archive.value.elapsed, running: archive.value.running, observedAt: Date.now()}};
  }
  function setValue(element, value, event) {
    if (!element || !visible(element)) throw new Error("RankLand 提交表单发生变化，请在原站核对。");
    element.value = String(value);
    element.dispatchEvent(new Event(event, {bubbles: true}));
  }
  function readiness(expectedUrl, sessionId) {
    try {
      if (!expectedUrl || identity(location.href) !== identity(expectedUrl) ||
          (sessionId && new URL(location.href).searchParams.get('run') !== sessionId)) {
        return {ready: false, reason: 'SESSION_MISMATCH'};
      }
    } catch (_) { return {ready: false, reason: 'SESSION_MISMATCH'}; }
    const board = document.querySelector('[data-id="vp-ranklist-content"]');
    if (!board) {
      const error = [...document.querySelectorAll('section.mt-16.text-center > p[role="alert"]')].find(visible);
      return {ready: false, reason: !error ? 'CONTEST_LOADING' :
        error.textContent.trim() === '起始时间必须小于比赛时长。' ? 'START_OFFSET_OUT_OF_RANGE' : 'SOURCE_LOAD_ERROR'};
    }
    const state = saved();
    if (!state) return {ready: false, reason: 'STORAGE_NOT_READY'};
    if (typeof state.value.ownName !== 'string') return {ready: false, reason: 'STORAGE_FORMAT_CHANGED'};
    if (!state.value.ownName.trim()) return {ready: false, reason: 'TEAM_REQUIRED', run: state.run};
    if (board.querySelectorAll('select[aria-label="题目"]').length !== 1 ||
        board.querySelectorAll('select[aria-label="结果"]').length !== 1) {
      return {ready: false, reason: 'RECORD_FORM_CHANGED', run: state.run};
    }
    return {ready: true, reason: 'READY', run: state.run};
  }
  async function prepareTeam(sessionId, expectedUrl, teamName) {
    let status = readiness(expectedUrl, sessionId);
    // Existing original-site team names are authoritative, including custom
    // names restored from a previous tab. Never overwrite them from QOJ.
    if (status.reason !== 'TEAM_REQUIRED') return status;
    if (typeof teamName !== 'string' || !teamName.trim() || teamName.trim().length > 80 || /[\x00-\x1f\x7f]/.test(teamName)) {
      return {ready: false, reason: 'TEAM_NAME_REQUIRED'};
    }
    teamName = teamName.trim();
    await intro();
    status = readiness(expectedUrl, sessionId);
    if (status.reason !== 'TEAM_REQUIRED') return status;
    const before = saved();
    const manualBefore = JSON.stringify(before.value.manual);
    const guard = () => browser.runtime.sendMessage({type: 'vp.rankland.guard', expectedUrl});
    if (!(await guard())?.allowed) return {ready: false, reason: 'TEAM_GUARD_BLOCKED'};
    // Do not take over a team dialog the user already has open.
    if ([...document.querySelectorAll('input[aria-label="队伍名称"]')].some(visible)) {
      return {ready: false, reason: 'TEAM_FORM_ALREADY_OPEN'};
    }
    const board = document.querySelector('[data-id="vp-ranklist-content"]');
    const joins = [...board.querySelectorAll('button')].filter(button => visible(button) && button.textContent.trim() === '加入我的队伍');
    if (joins.length !== 1) return {ready: false, reason: 'TEAM_FORM_CHANGED'};
    joins[0].click();
    let field, form;
    for (let n = 0; n < 40; n++) {
      await pause(100);
      const fields = [...document.querySelectorAll('input[aria-label="队伍名称"]')].filter(visible);
      if (fields.length === 1 && fields[0].closest('form')) {
        field = fields[0];
        form = field.closest('form');
        break;
      }
    }
    if (!field || !form) return {ready: false, reason: 'TEAM_FORM_CHANGED'};
    let current = saved();
    if (readiness(expectedUrl, sessionId).reason !== 'TEAM_REQUIRED' || current?.key !== before.key ||
        JSON.stringify(current.value.manual) !== manualBefore || !(await guard())?.allowed) {
      return {ready: false, reason: 'TEAM_STATE_CHANGED'};
    }
    setValue(field, teamName, 'input');
    await pause(100);
    const submit = [...form.querySelectorAll('button[type="submit"]')]
      .filter(button => visible(button) && button.textContent.trim() === '加入');
    if (submit.length !== 1) return {ready: false, reason: 'TEAM_FORM_CHANGED'};
    current = saved();
    if (readiness(expectedUrl, sessionId).reason !== 'TEAM_REQUIRED' || current?.key !== before.key ||
        JSON.stringify(current.value.manual) !== manualBefore || !(await guard())?.allowed) {
      return {ready: false, reason: 'TEAM_STATE_CHANGED'};
    }
    submit[0].click(); // Original local team form; never dispatch a verdict here.
    for (let n = 0; n < 50; n++) {
      await pause(100);
      current = saved();
      status = readiness(expectedUrl, sessionId);
      if (status.ready && current?.key === before.key && current.value.ownName === teamName &&
          JSON.stringify(current.value.manual) === manualBefore) return {...status, joined: true};
    }
    return {ready: false, reason: 'TEAM_SETUP_NOT_CONFIRMED'};
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
  let busy = false, preparing = null;
  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id) return undefined;
    if (message?.type === 'vp.rankland.snapshot') return Promise.resolve(scoreSnapshot(message.sessionId, message.expectedUrl));
    if (message?.type === 'vp.rankland.ready') return Promise.resolve(readiness(message.expectedUrl, message.sessionId));
    if (message?.type === 'vp.rankland.prepare') {
      if (busy) return Promise.resolve({ready: false, reason: 'DELIVERY_BUSY'});
      if (!preparing) preparing = prepareTeam(message.sessionId, message.expectedUrl, message.teamName)
        .catch(() => ({ready: false, reason: 'TEAM_SETUP_FAILED'})).finally(() => { preparing = null; });
      return preparing;
    }
    if (message?.type !== 'vp.rankland.deliver') return undefined;
    if (busy || preparing) return Promise.resolve({state: 'failed', message: '另一个同步任务仍在进行。'});
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
