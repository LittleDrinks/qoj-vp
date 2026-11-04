"use strict";
globalThis.VpScoreboardSources = (() => {
  const API = "https://rl.algoux.cn/api/v2/public/contests";
  const MAX_BODY_CHARS = 2 * 1024 * 1024;
  const MAX_SRK_BYTES = 16 * 1024 * 1024;
  const stopWords = new Set("the of and a an cup universal grand prix stage extra contest contests regional region programming collegiate international university universities china chinese asia asian site final finals semifinal semifinals round division div warm up practice acm icpc ccpc national year".split(" "));
  const id = value => /^(?:0|[1-9]\d{0,19})$/.test(String(value));
  const key = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value);
  const clean = value => typeof value === "string" && value.length <= 2048 && !/[\x00-\x1f]/.test(value) ? value.trim() : "";
  const fold = value => value.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[’'`]/g, "");
  const compact = value => fold(value).replace(/[^\p{L}\p{N}]/gu, "");
  const labels = value => clean(value).normalize("NFKC").toUpperCase();
  const years = values => new Set(values.join(" ").match(/(?:19|20)\d{2}/g) || []);
  const failure = code => Object.assign(new Error(code), {code});

  function duration(value) {
    if (!Array.isArray(value) || value.length !== 2 || typeof value[0] !== "number" || !Number.isFinite(value[0])) return null;
    const multiplier = {ms: 1, s: 1000, min: 60000, h: 3600000, d: 86400000}[value[1]];
    const result = value[0] * multiplier;
    return Number.isSafeInteger(result) && result > 0 && result <= 14 * 86400000 ? result : null;
  }
  function names(record) {
    const values = [record.name, record.title];
    if (record.title && typeof record.title === "object" && !Array.isArray(record.title)) values.push(...Object.values(record.title));
    if (Array.isArray(record.titles)) values.push(...record.titles.slice(0, 20));
    return [...new Set(values.map(clean).filter(Boolean))];
  }
  function input(contest, durationMs) {
    if (!contest || !id(contest.id) || !Number.isSafeInteger(durationMs) || durationMs <= 0 || durationMs > 14 * 86400000 ||
        !Array.isArray(contest.problems) || !contest.problems.length || contest.problems.length > 200) throw failure("INVALID_CONTEST");
    const problems = contest.problems.map(problem => ({id: String(problem?.id), label: labels(problem?.label)}));
    if (problems.some(problem => !id(problem.id) || !problem.label || problem.label.length > 32) ||
        new Set(problems.map(problem => problem.id)).size !== problems.length ||
        new Set(problems.map(problem => problem.label)).size !== problems.length) throw failure("INVALID_CONTEST");
    const titles = names(contest);
    if (!titles.length) throw failure("INVALID_CONTEST");
    return {id: String(contest.id), titles, problems, durationMs};
  }
  function anchors(titles) {
    const output = new Set();
    for (const title of titles) {
      for (const token of fold(title).match(/[a-z]{3,}/g) || []) if (!stopWords.has(token)) output.add(token);
      const chinese = title.replace(/第[\d零〇一二三四五六七八九十百]+届/g, "")
        .replace(/国际|中国|大学生|程序设计|竞赛|区域赛|正式赛|热身赛|邀请赛|赛区|全国|站|年|杯/g, " ");
      for (const token of chinese.match(/[\p{Script=Han}]{2,}/gu) || []) output.add(token);
    }
    return [...output];
  }
  function titleScore(contest, candidate) {
    const target = contest.titles, source = names(candidate);
    const sourceYears = years(source.concat(candidate.uk));
    // Older local-contest titles sometimes omit their year entirely. Their
    // actual catalogue date can still exclude a same-city, different-year event.
    if (!sourceYears.size && typeof candidate.startAt === "string" && /^\d{4}-\d{2}-\d{2}T/.test(candidate.startAt)) sourceYears.add(candidate.startAt.slice(0, 4));
    const targetYears = years(target);
    if (targetYears.size && sourceYears.size && ![...targetYears].some(year => sourceYears.has(year))) return 0;
    const forms = source.map(compact), targets = target.map(compact);
    if (targets.some(title => forms.includes(title))) return 100;
    const haystack = forms.concat(compact(candidate.uk));
    const hits = anchors(target).filter(token => haystack.some(text => text.includes(compact(token))));
    return hits.length ? Math.min(90, 10 + hits.length * 10) : 0;
  }
  function catalog(data) {
    if (!Array.isArray(data?.contests) || data.contests.length > 10000) throw failure("MALFORMED_CATALOG");
    const seen = new Set(), result = [];
    for (const item of data.contests) {
      if (!item || !key(item.uk) || seen.has(item.uk) || !names(item).length) throw failure("MALFORMED_CATALOG");
      seen.add(item.uk);
      if (!item.srkFileID) continue;
      if (!id(item.srkFileID)) throw failure("MALFORMED_CATALOG");
      result.push(item);
    }
    return result;
  }
  function problemId(raw) {
    try {
      const url = new URL(raw);
      if (url.origin !== "https://qoj.ac" || url.username || url.password) return null;
      const match = url.pathname.match(/^\/(?:contest\/\d+\/)?problem\/(\d+)\/?$/);
      return match && id(match[1]) ? match[1] : null;
    } catch (_) { return null; }
  }
  function qojTarget(contest, cid) {
    for (const raw of [contest.scoreboardUrl, contest.url]) {
      try {
        const url = new URL(raw);
        if (url.origin !== "https://qoj.ac" || url.username || url.password) continue;
        if (new RegExp("^/(?:contest/" + cid + "(?:/standings)?|results/QOJ" + cid + ")/?$").test(url.pathname)) return url.href;
      } catch (_) { /* Only a discovered same-contest QOJ URL is accepted. */ }
    }
    return "https://qoj.ac/contest/" + cid;
  }
  function verify(contest, candidate, detail) {
    if (!detail || detail.uk !== candidate.uk || !id(detail.srkFileID) ||
        !Array.isArray(detail.problems) || detail.problems.length > 200 || duration(detail.duration) === null) {
      return {state: "unverified", reason: "MALFORMED_DETAIL"};
    }
    if (detail.redirectUK) return {state: "unverified", reason: "REDIRECT_TARGET"};
    if (detail.sorter?.algorithm !== "ICPC") return {state: "mismatch", reason: "UNSUPPORTED_RULES"};
    if (duration(detail.duration) !== contest.durationMs) return {state: "mismatch", reason: "DURATION_MISMATCH"};
    if (detail.problems.length !== contest.problems.length) return {state: "mismatch", reason: "PROBLEM_COUNT_MISMATCH"};
    const remote = detail.problems.map(problem => ({id: problemId(problem?.link), label: labels(problem?.alias)}));
    if (remote.some(problem => !problem.id || !problem.label)) return {state: "unverified", reason: "PROBLEM_LINKS_MISSING"};
    if (!remote.every((problem, index) => problem.id === contest.problems[index].id && problem.label === contest.problems[index].label)) {
      return {state: "mismatch", reason: "PROBLEM_ORDER_MISMATCH"};
    }
    return {state: "matched", reason: "VERIFIED_PROBLEM_SET"};
  }

  function archiveFile(detail, file) {
    // Older RankLand contests keep their metadata in the original SRK file.
    // Resolve its public file record instead of constructing an assumed CDN URL.
    if (!id(detail._id) || !id(detail.srkFileID) || !file || String(file.id) !== String(detail.srkFileID) ||
        String(file.contestId) !== String(detail._id) || file.category !== "RankMain" ||
        typeof file.name !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}\.srk\.json$/.test(file.name) ||
        file.path !== detail.srkFileID + "/" + file.name || file.hashType !== "sha256" ||
        typeof file.hashValue !== "string" || !/^[a-f0-9]{64}$/i.test(file.hashValue) ||
        !Number.isSafeInteger(file.size) || file.size <= 0 || file.size > MAX_SRK_BYTES) throw failure("MALFORMED_FILE");
    let url;
    try { url = new URL(file.url); } catch (_) { throw failure("MALFORMED_FILE"); }
    if (url.origin !== "https://cdn.algoux.cn" || url.username || url.password || url.search || url.hash ||
        url.pathname !== "/rankland/file/" + file.path) throw failure("MALFORMED_FILE");
    return {url: url.href, size: file.size, hash: file.hashValue.toLowerCase()};
  }
  function archiveMetadata(value) {
    if (!value || value.type !== "general" || typeof value.version !== "string" || !/^0\.3\.\d+$/.test(value.version) ||
        !duration(value.contest?.duration) || !Array.isArray(value.problems) || !value.problems.length || value.problems.length > 200 ||
        typeof value.sorter?.algorithm !== "string") throw failure("MALFORMED_SRK");
    const problems = value.problems.map(problem => ({alias: labels(problem?.alias), link: clean(problem?.link)}));
    if (problems.some(problem => !problem.alias || problem.alias.length > 32) ||
        new Set(problems.map(problem => problem.alias)).size !== problems.length) throw failure("MALFORMED_SRK");
    // Participant rows can be much larger than these fields. The resolver only
    // retains metadata; the original RankLand page owns the actual replay.
    return {duration: value.contest.duration, problems, sorter: {algorithm: value.sorter.algorithm}};
  }

  function create(options = {}) {
    const fetchImpl = options.fetchImpl || ((...args) => globalThis.fetch(...args));
    const clock = options.clock || Date.now;
    const timeoutMs = options.timeoutMs ?? 5000, cacheTtlMs = options.cacheTtlMs ?? 300000;
    const maxCandidates = options.maxCandidates ?? 6;
    if (typeof fetchImpl !== "function" || typeof clock !== "function" || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000 ||
        !Number.isSafeInteger(cacheTtlMs) || cacheTtlMs < 0 || cacheTtlMs > 86400000 ||
        !Number.isSafeInteger(maxCandidates) || maxCandidates < 1 || maxCandidates > 8) throw failure("INVALID_OPTIONS");
    const cache = new Map(), pending = new Map();
    async function request(url, archive = null) {
      const cacheKey = archive ? url + "#sha256=" + archive.hash : url;
      const saved = cache.get(cacheKey);
      if (saved && saved.expiresAt > clock()) return saved.data;
      if (pending.has(cacheKey)) return pending.get(cacheKey);
      const task = (async () => {
        const controller = new AbortController();
        let timer;
        try {
          const data = await Promise.race([(async () => {
            const response = await fetchImpl(url, {method: "GET", credentials: "omit", redirect: "error", signal: controller.signal});
            if (!response?.ok) throw failure("HTTP_ERROR");
            let text;
            if (archive) {
              if (!/^application\/json(?:\s*;|$)/i.test(response.headers?.get("Content-Type") || "")) throw failure("MALFORMED_SRK");
              const contentLength = Number(response.headers?.get("Content-Length"));
              if (contentLength > MAX_SRK_BYTES) throw failure("RESPONSE_TOO_LARGE");
              const bytes = await response.arrayBuffer();
              if (bytes.byteLength > MAX_SRK_BYTES) throw failure("RESPONSE_TOO_LARGE");
              if (bytes.byteLength !== archive.size) throw failure("SRK_INTEGRITY_MISMATCH");
              const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
              const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
              if (hash !== archive.hash) throw failure("SRK_INTEGRITY_MISMATCH");
              text = new TextDecoder("utf-8", {fatal: true}).decode(bytes);
            } else {
              text = await response.text();
              if (text.length > MAX_BODY_CHARS) throw failure("RESPONSE_TOO_LARGE");
            }
            let value;
            try { value = JSON.parse(text); } catch (_) { throw failure("INVALID_JSON"); }
            if (archive) { archiveMetadata(value); return value; }
            if (value?.success !== true || value?.code !== 0 || !value.data || typeof value.data !== "object" || Array.isArray(value.data)) throw failure("MALFORMED_RESPONSE");
            return value.data;
          })(), new Promise((_, reject) => {
            timer = setTimeout(() => { reject(failure("TIMEOUT")); controller.abort(); }, timeoutMs);
          })]);
          cache.set(cacheKey, {data, expiresAt: clock() + cacheTtlMs});
          // A long-lived event page should not retain every previously inspected detail.
          while (cache.size > 128) cache.delete(cache.keys().next().value);
          return data;
        } catch (error) {
          throw failure(["HTTP_ERROR", "RESPONSE_TOO_LARGE", "INVALID_JSON", "MALFORMED_RESPONSE", "MALFORMED_SRK", "SRK_INTEGRITY_MISMATCH", "TIMEOUT"].includes(error?.code) ? error.code : "NETWORK_ERROR");
        } finally { clearTimeout(timer); }
      })().finally(() => pending.delete(cacheKey));
      pending.set(cacheKey, task);
      return task;
    }
    async function contestDetail(api, uk) {
      const detail = await request(api + "/" + encodeURIComponent(uk));
      if (!detail || detail.uk !== uk || detail.redirectUK || !duration(detail.duration)) throw failure("MALFORMED_DETAIL");
      if (detail.problems != null && detail.sorter != null) return detail;
      if (!id(detail._id) || !id(detail.srkFileID)) throw failure("MALFORMED_DETAIL");
      const file = archiveFile(detail, await request(api.replace(/\/contests$/, "/files/") + detail.srkFileID));
      const metadata = archiveMetadata(await request(file.url, file));
      if (duration(metadata.duration) !== duration(detail.duration) ||
          (detail.sorter != null && detail.sorter.algorithm !== metadata.sorter.algorithm) ||
          (detail.problems != null && (!Array.isArray(detail.problems) || detail.problems.length !== metadata.problems.length ||
            detail.problems.some((problem, index) => labels(problem?.alias) !== metadata.problems[index].alias ||
              (clean(problem?.link) && clean(problem.link) !== metadata.problems[index].link))))) throw failure("MALFORMED_DETAIL");
      return {...detail, problems: metadata.problems, sorter: metadata.sorter};
    }
    async function resolve(raw, durationMs) {
      const contest = input(raw, durationMs), qojUrl = qojTarget(raw, contest.id);
      const fallback = (state, reason, extra = {}) => ({source: "qoj", state, reason, url: qojUrl,
        qojUrl, ranklandUrl: null, candidates: [], candidateCount: 0, checkedCandidates: 0, checkedAt: clock(), ...extra});
      let all;
      try { all = catalog(await request(API)); }
      catch (error) { return fallback("unavailable", error.code || "CATALOG_UNAVAILABLE"); }
      const candidates = all.map(item => ({item, score: titleScore(contest, item)})).filter(item => item.score > 0)
        .sort((a, b) => b.score - a.score || a.item.uk.localeCompare(b.item.uk));
      const summary = candidate => ({uk: candidate.uk, name: names(candidate)[0]});
      const info = {candidateCount: candidates.length, candidates: candidates.slice(0, maxCandidates).map(value => summary(value.item))};
      if (!candidates.length) return fallback("unmatched", "NO_TITLE_CANDIDATE");
      if (candidates.length > maxCandidates) return fallback("unverified", "CANDIDATE_LIMIT", info);
      const checked = await Promise.all(candidates.map(async ({item}) => {
        try { return {...summary(item), ...verify(contest, item, await contestDetail(API, item.uk))}; }
        catch (error) { return {...summary(item), state: "unverified", reason: error.code || "DETAIL_UNAVAILABLE"}; }
      }));
      const results = {candidateCount: candidates.length, candidates: checked, checkedCandidates: checked.length};
      const matched = checked.filter(item => item.state === "matched");
      if (matched.length > 1) return fallback("ambiguous", "MULTIPLE_MATCHES", results);
      if (checked.some(item => item.state === "unverified")) return fallback("unverified", "INCOMPLETE_VERIFICATION", results);
      if (!matched.length) return fallback("unmatched", "NO_VERIFIED_MATCH", results);
      const ranklandUrl = "https://vp.xcpc.link/?contest=" + encodeURIComponent(matched[0].uk);
      return {...fallback("matched", "VERIFIED_PROBLEM_SET", results), source: "rankland", url: ranklandUrl,
        ranklandUrl, contestKey: matched[0].uk};
    }
    async function describeReplay(raw) {
      const url = new URL(raw), uk = url.searchParams.get("contest");
      const loopback = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
      if ((!loopback && url.origin !== "https://vp.xcpc.link") || url.pathname !== "/" || !key(uk)) throw failure("INVALID_REPLAY");
      const detail = await contestDetail(loopback ? url.origin + "/api/v2/public/contests" : API, uk);
      const durationMs = duration(detail.duration);
      if (detail.uk !== uk || detail.redirectUK || !durationMs || detail.sorter?.algorithm !== "ICPC" ||
          !Array.isArray(detail.problems) || !detail.problems.length || detail.problems.length > 200) throw failure("MALFORMED_DETAIL");
      const problems = detail.problems.map((problem, index) => ({index, label: labels(problem?.alias)}));
      if (problems.some(problem => !problem.label) || new Set(problems.map(problem => problem.label)).size !== problems.length) throw failure("MALFORMED_DETAIL");
      return {contestKey: uk, durationMs, problems};
    }
    async function loadArchive(raw) {
      const url = new URL(raw), uk = url.searchParams.get("contest");
      const loopback = url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
      if ((!loopback && url.origin !== "https://vp.xcpc.link") || url.pathname !== "/" || !key(uk)) throw failure("INVALID_REPLAY");
      const api = loopback ? url.origin + "/api/v2/public/contests" : API;
      const detail = await request(api + "/" + encodeURIComponent(uk));
      if (detail.uk !== uk || detail.redirectUK) throw failure("MALFORMED_DETAIL");
      const file = archiveFile(detail, await request(api.replace(/\/contests$/, "/files/") + detail.srkFileID));
      return {archive:await request(file.url, file), hash:file.hash, contestKey:uk, fetchedAt:clock()};
    }
    return {resolve, describeReplay, loadArchive};
  }
  const defaults = create();
  return {create, resolve: defaults.resolve, describeReplay: defaults.describeReplay, loadArchive: defaults.loadArchive};
})();
