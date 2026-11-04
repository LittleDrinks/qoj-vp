"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const {webcrypto, createHash} = require("node:crypto");
const source = fs.readFileSync(path.join(__dirname, "../extension/scoreboard-sources.js"), "utf8");
const API = "https://rl.algoux.cn/api/v2/public/contests";
const HOURS = 18000000;
const title = "The 2022 ICPC Asia Xi'an Regional Contest";
const qoj = {id: "1051", name: title, problems: [{id: "5113", label: "A"}, {id: "5114", label: "B"}]};
const entry = (uk = "icpc2022xi_an", extra = {}) => ({uk, name: title, title: {en: title}, duration: [18000, "s"], srkFileID: "1234", ...extra});
const detail = (uk = "icpc2022xi_an", extra = {}) => ({...entry(uk), sorter: {algorithm: "ICPC"}, redirectUK: null,
  problems: [{alias: "A", link: "https://qoj.ac/problem/5113"}, {alias: "B", link: "https://qoj.ac/problem/5114"}], ...extra});
const envelope = data => new Response(JSON.stringify({success: true, code: 0, data}));
function setup({entries = [entry()], details = {}, handler = null, ...options} = {}) {
  const requests = [], context = {URL, AbortController, setTimeout, clearTimeout, Date, Map, Set, crypto: webcrypto, TextDecoder};
  vm.createContext(context); vm.runInContext(source, context);
  const resolver = context.VpScoreboardSources.create({...options, fetchImpl: async (url, opts) => {
    requests.push({url, opts});
    if (handler) return handler(url, opts);
    if (url === API) return envelope({contests: entries});
    const uk = decodeURIComponent(url.slice(API.length + 1));
    return envelope(details[uk] || detail(uk));
  }});
  return {requests, describeReplay: resolver.describeReplay, resolve: (contest = qoj, duration = HOURS) => resolver.resolve(contest, duration)};
}
test("replay metadata provides original problem indices and duration using cached public GET only", async () => {
  const env = setup(), url = "https://vp.xcpc.link/?contest=icpc2022xi_an&run=practice";
  const first = await env.describeReplay(url), again = await env.describeReplay(url);
  assert.equal(first.durationMs, HOURS); assert.equal(first.problems[1].index, 1); assert.equal(first.problems[1].label, "B");
  assert.equal(JSON.stringify(first), JSON.stringify(again)); assert.equal(env.requests.length, 1);
  assert.equal(env.requests[0].opts.method, "GET"); assert.equal(env.requests[0].opts.credentials, "omit");
});
test("replay import rejects mismatched keys, duplicate aliases, redirects and unsupported scoring metadata", async () => {
  for (const patch of [{uk:"other"}, {redirectUK:"other"}, {sorter:{algorithm:"OI"}}, {duration:[0,"s"]},
      {problems:[{alias:"A"},{alias:"A"}]}]) {
    const env = setup({handler:async()=>envelope(detail("icpc2022xi_an",patch))});
    await assert.rejects(env.describeReplay("https://vp.xcpc.link/?contest=icpc2022xi_an"), error=>error.code==="MALFORMED_DETAIL");
  }
  await assert.rejects(setup().describeReplay("https://example.com/?contest=icpc2022xi_an"), error=>error.code==="INVALID_REPLAY");
});
test("exact QOJ problem identities and order select the original RankLand URL without starting a replay", async () => {
  const env = setup(), result = await env.resolve();
  assert.equal(result.source, "rankland"); assert.equal(result.state, "matched");
  assert.equal(result.ranklandUrl, "https://vp.xcpc.link/?contest=icpc2022xi_an");
  assert.equal(result.url, result.ranklandUrl); assert.equal(result.contestKey, "icpc2022xi_an");
  assert.equal(result.checkedCandidates, 1); assert.equal(result.qojUrl, "https://qoj.ac/contest/1051");
  assert.equal(env.requests.length, 2);
  for (const {url, opts} of env.requests) {
    assert.ok(url.startsWith(API)); assert.equal(opts.method, "GET"); assert.equal(opts.credentials, "omit");
    assert.equal(opts.redirect, "error"); assert.equal(opts.headers, undefined); assert.equal(opts.body, undefined);
    assert.ok(opts.signal instanceof AbortSignal);
  }
});
test("Chinese aliases and contest-scoped QOJ problem links match Changchun with supported CCPC26 metadata", async () => {
  const uk = "ccpc2026changchun", remote = entry(uk, {name: "2026 年第十二届中国大学生程序设计竞赛 长春站 正式赛", title: {fallback: "2026 年第十二届中国大学生程序设计竞赛 长春站 正式赛"}});
  const env = setup({entries: [remote], details: {[uk]: {...remote, sorter: {algorithm: "ICPC", config: {extendedAlgorithms: [{algorithm: "CCPC26"}]}},
    problems: [{alias: "A", link: "https://qoj.ac/contest/4582/problem/22910"}, {alias: "B", link: "https://qoj.ac/contest/4582/problem/22911"}]}}});
  const result = await env.resolve({id: "4582", title: "第十二届中国大学生程序设计竞赛 长春站（CCPC 2026 Changchun Site）",
    problems: [{id: "22910", label: "A"}, {id: "22911", label: "B"}]});
  assert.equal(result.source, "rankland"); assert.equal(result.contestKey, uk);
});
test("Ucup without a title candidate falls back to QOJ and never requests unrelated detail", async () => {
  const env = setup({entries: [entry(), entry("ucup3rdfinals", {name: "The 3rd Universal Cup Finals", title: {fallback: "The 3rd Universal Cup Finals"}})]});
  const result = await env.resolve({...qoj, id: "4569", name: "The 5th Universal Cup. Extra Stage 1: Dolgoprudny"});
  assert.equal(result.source, "qoj"); assert.equal(result.state, "unmatched"); assert.equal(result.reason, "NO_TITLE_CANDIDATE");
  assert.equal(result.qojUrl, "https://qoj.ac/contest/4569"); assert.equal(env.requests.length, 1);
});
test("an available Ucup contest is eligible and alternate titles can discover its matching regional contest", async () => {
  const uk = "ucup3rdfinals", name = "The 3rd Universal Cup Finals";
  let env = setup({entries: [entry(uk, {name, title: name})]});
  assert.equal((await env.resolve({...qoj, name})).source, "rankland");
  env = setup();
  assert.equal((await env.resolve({...qoj, name: "The Universal Cup. Stage 4", titles: [title]})).source, "rankland");
});
test("a same-city contest in a different year is not fetched or selected", async () => {
  const env = setup({entries: [entry("icpc2026xi_an", {name: title.replace("2022", "2026"), title: {fallback: title.replace("2022", "2026")}})]});
  assert.equal((await env.resolve()).state, "unmatched"); assert.equal(env.requests.length, 1);
});
test("a yearless title from an older dated event cannot block a verified same-city match", async () => {
  const env = setup({entries: [entry(), entry("local1st", {name: "Xi'an local contest", title: {fallback: "Xi'an local contest"}, startAt: "2021-05-01T09:00:00+08:00"})]});
  assert.equal((await env.resolve()).source, "rankland"); assert.equal(env.requests.length, 2);
});
test("QOJ fallback follows the observed native scoreboard link, never guesses standings or accepts another contest", async () => {
  const env = setup({entries: []});
  const source = {...qoj, scoreboardUrl: "https://qoj.ac/results/QOJ1051?mode=pc2"};
  assert.equal((await env.resolve(source)).qojUrl, source.scoreboardUrl);
  for (const scoreboardUrl of ["https://qoj.ac/results/QOJ999?mode=pc2", "https://evil.example/results/QOJ1051", "https://qoj.ac/contest/1051/register", "https://user@qoj.ac/contest/1051/standings"]) {
    assert.equal((await env.resolve({...qoj, scoreboardUrl})).qojUrl, "https://qoj.ac/contest/1051");
  }
});
test("same title or partial problem overlap never outweighs problem order, labels, count or duration", async () => {
  for (const change of [
    {problems: [{alias: "A", link: "https://qoj.ac/problem/5114"}, {alias: "B", link: "https://qoj.ac/problem/5113"}]},
    {problems: [{alias: "B", link: "https://qoj.ac/problem/5113"}, {alias: "A", link: "https://qoj.ac/problem/5114"}]},
    {problems: [{alias: "A", link: "https://qoj.ac/problem/5113"}]},
    {duration: [4, "h"]}, {sorter: {algorithm: "IOI"}}
  ]) {
    const result = await setup({details: {icpc2022xi_an: detail(undefined, change)}}).resolve();
    assert.equal(result.source, "qoj"); assert.equal(result.state, "unmatched"); assert.equal(result.ranklandUrl, null);
  }
});
test("two complete matches remain ambiguous instead of choosing by title order", async () => {
  const result = await setup({entries: [entry("original"), entry("duplicate")]}).resolve();
  assert.equal(result.source, "qoj"); assert.equal(result.state, "ambiguous"); assert.equal(result.reason, "MULTIPLE_MATCHES");
  assert.equal(result.checkedCandidates, 2);
});
test("more candidates than the configured limit stays unverified without an unbounded detail crawl", async () => {
  const env = setup({entries: Array.from({length: 9}, (_, index) => entry("copy" + index))});
  const result = await env.resolve();
  assert.equal(result.state, "unverified"); assert.equal(result.reason, "CANDIDATE_LIMIT");
  assert.equal(result.candidateCount, 9); assert.equal(result.candidates.length, 6); assert.equal(result.checkedCandidates, 0);
  assert.equal(env.requests.length, 1);
});
test("a verified candidate plus a failed competing lookup cannot claim uniqueness", async () => {
  const env = setup({handler: async url => {
    if (url === API) return envelope({contests: [entry("good"), entry("broken")]});
    if (url.endsWith("/broken")) throw Error("offline");
    return envelope(detail("good"));
  }});
  const result = await env.resolve();
  assert.equal(result.state, "unverified"); assert.equal(result.reason, "INCOMPLETE_VERIFICATION");
  assert.equal(result.ranklandUrl, null); assert.equal(result.candidates.find(row => row.uk === "broken").reason, "NETWORK_ERROR");
});
test("missing links, redirects and malformed details remain unverified instead of guessed matches", async () => {
  for (const change of [
    {uk: "another-contest"}, {problems: null}, {duration: "5 hours"}, {redirectUK: "canonical"},
    {problems: [{alias: "A", link: "https://evil.example/problem/5113"}, {alias: "B", link: "https://qoj.ac/problem/5114"}]},
    {problems: [{alias: "A", link: "https://qoj.ac.evil.example/problem/5113"}, {alias: "B", link: "https://qoj.ac/problem/5114"}]},
    {problems: [{alias: "A", link: "https://user@qoj.ac/problem/5113"}, {alias: "B", link: "https://qoj.ac/problem/5114"}]},
    {problems: [{alias: "A"}, {alias: "B"}]}
  ]) {
    const result = await setup({details: {icpc2022xi_an: detail(undefined, change)}}).resolve();
    assert.equal(result.source, "qoj"); assert.equal(result.state, "unverified");
  }
});
test("invalid public envelopes and catalog structures are availability failures, never a no-match conclusion", async () => {
  for (const response of [
    new Response("broken"), new Response("{}"), new Response("{}", {status: 503}),
    envelope({contests: "changed"}), envelope({contests: [entry("bad?redirect=elsewhere")]}),
    envelope({contests: [entry("copy"), entry("copy")]})
  ]) {
    const env = setup({handler: async () => response});
    const result = await env.resolve();
    assert.equal(result.state, "unavailable"); assert.equal(result.source, "qoj"); assert.equal(env.requests.length, 1);
  }
});
test("catalog timeout terminates even when a fetch implementation ignores AbortSignal", async () => {
  const env = setup({timeoutMs: 5, handler: async () => new Promise(() => {})});
  const result = await env.resolve();
  assert.equal(result.state, "unavailable"); assert.equal(result.reason, "TIMEOUT");
  assert.equal(env.requests[0].opts.signal.aborted, true);
});
test("a detail timeout preserves QOJ fallback and explains incomplete verification", async () => {
  const env = setup({timeoutMs: 5, handler: async url => url === API ? envelope({contests: [entry()]}) : new Promise(() => {})});
  const result = await env.resolve();
  assert.equal(result.state, "unverified"); assert.equal(result.candidates[0].reason, "TIMEOUT");
});
test("concurrent resolutions share catalog and detail requests, but validate each contest separately", async () => {
  const env = setup();
  const [first, other] = await Promise.all([env.resolve(), env.resolve({...qoj, problems: [{id: "999", label: "A"}]})]);
  assert.equal(first.source, "rankland"); assert.equal(other.source, "qoj");
  assert.equal(env.requests.length, 2);
  assert.equal((await env.resolve()).source, "rankland"); assert.equal(env.requests.length, 2);
});
test("cache expiry fetches current metadata and a network failure never erases a verified result into a fabricated match", async () => {
  let now = 100, offline = false;
  const env = setup({clock: () => now, cacheTtlMs: 10, handler: async url => {
    if (offline) throw Error("offline");
    return envelope(url === API ? {contests: [entry()]} : detail());
  }});
  assert.equal((await env.resolve()).source, "rankland");
  now = 105; offline = true;
  assert.equal((await env.resolve()).source, "rankland"); assert.equal(env.requests.length, 2);
  now = 111;
  const result = await env.resolve();
  assert.equal(result.state, "unavailable"); assert.equal(result.reason, "NETWORK_ERROR"); assert.equal(env.requests.length, 3);
});
test("invalid input fails before any public network request", async () => {
  for (const change of [{id: "../123"}, {problems: []}, {problems: [{id: "1", label: "A"}, {id: "1", label: "B"}]},
    {problems: [{id: "1", label: "A"}, {id: "2", label: "A"}]}, {name: ""}]) {
    const env = setup();
    await assert.rejects(env.resolve({...qoj, ...change}), {message: "INVALID_CONTEST"});
    assert.equal(env.requests.length, 0);
  }
  await assert.rejects(setup().resolve(qoj, 0), {message: "INVALID_CONTEST"});
});

// The real sdutpc14 public contest has null problems/sorter. The original
// RankLand client reads these from getPublicFile(...).url instead. These
// fixtures retain that observed shape without carrying real participant rows.
function archivedBoard({patchContest = {}, patchFile = {}, patchSrk = {}, corruptBody = false} = {}) {
  const uk = "sdutpc14", fid = "70792767114055680", contestId = "70792767067918336";
  const contest = {_id:contestId, uk, name:"山东理工大学第十四届ACM程序设计竞赛", title:{fallback:"山东理工大学第十四届ACM程序设计竞赛"},
    startAt:"2022-05-29T13:10:00+08:00", duration:[14400,"s"], srkFileID:fid, problems:null, sorter:null, redirectUK:null, ...patchContest};
  const srk = {type:"general", version:"0.3.9", contest:{title:contest.name, startAt:contest.startAt, duration:[4,"h"]},
    problems:Array.from({length:10},(_,i)=>({alias:String.fromCharCode(65+i)})), sorter:{algorithm:"ICPC",config:{penalty:[20,"min"]}}, rows:[], ...patchSrk};
  const body = JSON.stringify(srk), fileUrl = "https://cdn.algoux.cn/rankland/file/" + fid + "/sdutpc14.srk.json";
  const file = {id:fid, contestId, category:"RankMain", name:"sdutpc14.srk.json", path:fid+"/sdutpc14.srk.json", url:fileUrl,
    size:Buffer.byteLength(body), hashType:"sha256", hashValue:createHash("sha256").update(body).digest("hex"), ...patchFile};
  const env = setup({handler:async url => {
    if(url===API)return envelope({contests:[contest]});
    if(url===API+"/"+uk)return envelope(contest);
    if(url==="https://rl.algoux.cn/api/v2/public/files/"+fid)return envelope(file);
    if(url===fileUrl)return new Response(corruptBody?body+" ":body,{headers:{"Content-Type":"application/json"}});
    throw Error("Unexpected URL "+url);
  }});
  return {...env, contest, srk, file, url:"https://vp.xcpc.link/?contest="+uk};
}

test("archived SDUT metadata comes from the original public file and verified SRK bytes", async()=>{
  const env=archivedBoard(), result=await env.describeReplay(env.url);
  assert.equal(result.durationMs,14400000); assert.equal(result.problems.length,10);
  assert.equal(result.problems[9].label,"J"); assert.equal(result.problems[9].index,9);
  assert.equal(env.requests.length,3);
  assert.deepEqual(env.requests.map(r=>r.url),[API+"/sdutpc14","https://rl.algoux.cn/api/v2/public/files/70792767114055680",env.file.url]);
  for(const {opts} of env.requests){assert.equal(opts.credentials,"omit");assert.equal(opts.method,"GET");assert.equal(opts.redirect,"error");}
  await env.describeReplay(env.url); assert.equal(env.requests.length,3);
});

test("archived aliases alone never invent a QOJ mapping",async()=>{
  const env=archivedBoard(), result=await env.resolve({id:"123",name:env.contest.name,
    problems:env.srk.problems.map((p,i)=>({id:String(i+1),label:p.alias}))},14400000);
  assert.equal(result.source,"qoj");assert.equal(result.state,"unverified");
  assert.equal(result.candidates[0].reason,"PROBLEM_LINKS_MISSING");
});

test("an archived board still needs exact QOJ links and order for automatic matching",async()=>{
  for(const reversed of [false,true]){
    const problems=[{alias:"A",link:"https://qoj.ac/problem/5113"},{alias:"B",link:"https://qoj.ac/problem/5114"}];
    const env=archivedBoard({patchSrk:{problems:reversed?[...problems].reverse():problems}});
    const result=await env.resolve({...qoj,name:env.contest.name},14400000);
    assert.equal(result.source,reversed?"qoj":"rankland");
  }
});

test("foreign files, external URLs, unsupported hash metadata and oversized archives are rejected before CDN fetch",async()=>{
  for(const patchFile of [{id:"99"},{contestId:"99"},{category:"UserFile"},
    {url:"https://evil.example/sdutpc14.srk.json"},{url:"https://cdn.algoux.cn/rankland/file/99/sdutpc14.srk.json"},
    {url:"https://user@cdn.algoux.cn/rankland/file/70792767114055680/sdutpc14.srk.json"},
    {url:"https://cdn.algoux.cn/rankland/file/70792767114055680/sdutpc14.srk.json?token=bad"},
    {hashType:"md5"},{hashValue:"invalid"},{size:1024*1024*1024}]){
    const env=archivedBoard({patchFile});await assert.rejects(env.describeReplay(env.url));
    assert.ok(env.requests.every(r=>r.url.startsWith("https://rl.algoux.cn/api/")));
  }
});

test("changed SRK bytes are rejected and are not cached as valid metadata",async()=>{
  const env=archivedBoard({corruptBody:true});
  for(let i=0;i<2;i++)await assert.rejects(env.describeReplay(env.url),error=>error.code==="SRK_INTEGRITY_MISMATCH");
  assert.equal(env.requests.filter(r=>r.url===env.file.url).length,2);
});

test("SRK duration conflicts, unsupported schema and duplicate problem aliases fail closed",async()=>{
  for(const patchSrk of [{contest:{duration:[5,"h"]}},{version:"999"},{type:"other"},
    {problems:[{alias:"A"},{alias:"A"}]},{sorter:{algorithm:"IOI"}}]){
    const env=archivedBoard({patchSrk});await assert.rejects(env.describeReplay(env.url));
  }
  const env=archivedBoard({patchContest:{problems:[{alias:"WRONG"}]}});
  await assert.rejects(env.describeReplay(env.url));
});
