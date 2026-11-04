"use strict";
// RankLand's private storage is isolated here. Build filenames are deliberately
// not a protocol: validate URL, records and observable page behavior instead.
(() => {
  const results = new Set(["AC", "WA", "TLE", "MLE", "RTE", "CE", "PE", "OLE", "IDLE", "NOUT", "RJ", "UKE"]);
  const fail = () => { throw Object.assign(new Error("Unsupported RankLand storage contract"), {code:"RANKLAND_SCHEMA_CHANGED"}); };
  function parameters(raw) {
    const url = new URL(raw), q = url.searchParams;
    if (url.pathname !== "/" || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(q.get("contest") || "")) fail();
    const rule = q.get("rule") || "auto", count = Number(q.get("count") ?? 50), ratio = Number(q.get("ratio") ?? 20);
    if (!["auto", "ICPC", "CCPC26"].includes(rule) || !Number.isInteger(count) || count < 0 || count > 100000 ||
        !Number.isFinite(ratio) || ratio < 0 || ratio > 100) fail();
    const at = q.get("at"), stamp = at ? Date.parse(at) : NaN;
    if (at && !Number.isFinite(stamp)) fail();
    return {url, q, rule, count, ratio, at:Number.isFinite(stamp) ? new Date(stamp).toISOString() : null};
  }
  function identity(raw) {
    const {url,q,rule,count,ratio,at} = parameters(raw);
    if (at) return JSON.stringify([url.origin,q.get("contest"),at,rule,count,ratio]);
    if (!q.get("run")) fail();
    return JSON.stringify([url.origin,q.get("contest"),q.get("run"),rule,count,ratio,"null",Number(q.get("from") || 0)]);
  }
  function legacyKey(raw) {
    const {q,rule,count,ratio} = parameters(raw);
    return q.get("run") ? `RanklandVP2:${q.get("contest")}:${q.get("run")}:${rule}:${count}:${ratio}:${q.get("at") || "null"}:${Number(q.get("from") || 0)}` : null;
  }
  function archiveKey(raw) {
    const {q,rule,count,ratio,at} = parameters(raw);
    return at ? `RanklandVP:submissions:${q.get("contest")}:${at}:${rule}:${count}:${ratio}` : legacyKey(raw);
  }
  function clock(raw, durationMs = Number.MAX_SAFE_INTEGER, now = Date.now()) {
    const {q,at} = parameters(raw), from = Number(q.get("from") || 0), speed = Number(q.get("speed") || 1);
    const anchor = q.get("anchor") ? Date.parse(q.get("anchor")) : Date.parse(at);
    const play = q.get("play"), autoplay = play === "1" || (play === null && !!at);
    if (!at || !Number.isFinite(anchor) || anchor < Date.parse(at) || ![1,2,5,10,30,60].includes(speed) ||
        !Number.isFinite(from) || from < 0 || from > 10080 || (play !== null && !["0","1"].includes(play))) fail();
    const elapsed = Math.min(durationMs, from * 60000 + (autoplay ? Math.max(0,now-anchor) * speed : 0));
    return {elapsed,running:autoplay && now >= Date.parse(at) && elapsed < durationMs,speed};
  }
  function decode(raw, kind, url, {durationMs = Number.MAX_SAFE_INTEGER, problemCount = Number.MAX_SAFE_INTEGER, allowEmpty = false} = {}) {
    let archive;
    try { archive = raw === null && kind === "submissions" && allowEmpty ? [] : JSON.parse(raw); } catch (_) { fail(); }
    let value;
    if (kind === "submissions") {
      if (!Array.isArray(archive)) fail();
      const q = parameters(url).q;
      value = {version:2,manual:archive,ownName:q.get("team") || "",ownOrganization:q.get("organization") || "",...clock(url,durationMs)};
    } else if (kind === "v2") {
      if (!archive || Array.isArray(archive) || archive.version !== 2 ||
          !Number.isFinite(archive.elapsed) || archive.elapsed < 0 || archive.elapsed > durationMs ||
          !Number.isFinite(archive.savedAt) || archive.savedAt <= 0 || typeof archive.running !== "boolean" ||
          ![1,2,5,10,30,60].includes(archive.speed)) fail();
      value = archive;
    } else fail();
    if (typeof value.ownName !== "string" || value.ownName.length > 80 || /[\x00-\x1f\x7f]/.test(value.ownName) ||
        (value.ownOrganization != null && (typeof value.ownOrganization !== "string" || value.ownOrganization.length > 120)) ||
        !Array.isArray(value.manual) || value.manual.length > 10000 || value.manual.some(item =>
          !item || Object.keys(item).length !== 3 || !Number.isInteger(item.problemIndex) || item.problemIndex < 0 || item.problemIndex >= problemCount ||
          !Number.isFinite(item.timeMs) || item.timeMs < 0 || item.timeMs > durationMs || !results.has(item.result))) fail();
    return value;
  }
  function read(storage, url, options = {}) {
    const modern = archiveKey(url), legacy = legacyKey(url);
    let key = modern, kind = modern?.startsWith("RanklandVP:submissions:") ? "submissions" : "v2";
    if (!key) fail();
    let raw = storage.getItem(key);
    // Old pages with their original run URL and an existing v2 archive remain
    // readable. Never rewrite that archive into a newer format in place.
    if (raw === null && legacy && storage.getItem(legacy) !== null) { key = legacy; kind = "v2"; raw = storage.getItem(key); }
    return {key,kind,raw,value:decode(raw,kind,url,options)};
  }
  function encode(state, manual) {
    return JSON.stringify(state.kind === "submissions" ? manual : {...state.value,manual});
  }
  const api = Object.freeze({identity,legacyKey,archiveKey,clock,decode,read,encode});
  globalThis.VpRanklandProtocol = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
