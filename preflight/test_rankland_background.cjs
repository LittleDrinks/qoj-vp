"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../extension/background.js"), "utf8");
const sessionId = "11111111-2222-4333-8444-555555555555";
const url = `https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC&run=${sessionId}&from=0&at=2026-11-01T00%3A00%3A00Z`;
const identity = raw => {
  const parsed = new URL(raw), params = parsed.searchParams;
  return JSON.stringify([parsed.origin, params.get("contest"), params.get("run"), params.get("rule") || "auto", Number(params.get("count") ?? 50), Number(params.get("ratio") ?? 20), params.get("at") || "null", Number(params.get("from") || 0)]);
};
function environment(cache = {}) {
  const session = {sessionId, ranklandUrl: url}, requests = [], nativeCalls = [];
  const result = {ready: true, reason: "READY", snapshot: {version: 1, sessionId, url, identity: identity(url), targetKey: "RanklandVP2:owned", ownName: "LittleDrinks", rank: 465, ranks: [{label: "#", value: 465}], score: 1, penaltyMinutes: 77, elapsedMs: 5000000, running: true, observedAt: Date.now()}};
  const setup = {tabs: [{id: 7, url}], result, fail: false};
  const listener = {addListener() {}};
  const context = {URL, Map, Set, Promise, Date, setTimeout, clearTimeout, crypto: require("node:crypto").webcrypto,
    __native: async (method, args) => { nativeCalls.push({method, args}); assert.equal(method, "inspect_session"); return {...session}; },
    VpTransport: {pause: async () => {}},
    browser: {runtime: {id: "test-extension", getURL: name => "moz-extension://test/" + name, onMessage: listener, onInstalled: listener}, action: {onClicked: listener}, alarms: {create() {}, onAlarm: listener},
      tabs: {query: async () => setup.tabs, sendMessage: async (tabId, message) => { requests.push({tabId, message}); if (setup.fail) throw Error("closed"); return setup.handler ? setup.handler(tabId, message) : setup.result; }},
      scripting: {executeScript: async () => [{result: null}]},
      storage: {local: {get: async key => ({[key]: cache[key]}), set: async values => Object.assign(cache, values)}}}};
  vm.createContext(context);
  vm.runInContext(source.replace(/\}\)\(\);\s*$/, "native = globalThis.__native; globalThis.dispatch = dispatch; })();"), context);
  return {session, setup, requests, nativeCalls, cache, read: () => context.dispatch("rankland.snapshot", {sessionId})};
}
test("empty submission queue still reads and persists original RankLand rank and penalty", async () => {
  const env = environment(), result = await env.read();
  assert.equal(result.state, "live"); assert.equal(result.snapshot.rank, 465); assert.equal(result.snapshot.penaltyMinutes, 77);
  assert.equal(result.url, url); assert.equal(env.requests[0].message.type, "vp.rankland.snapshot");
  assert.equal(Object.values(env.cache)[0].rank, 465); assert.equal(env.nativeCalls.length, 1);
});
test("closing the scoreboard retains explicitly cached values without opening a tab", async () => {
  const env = environment(); await env.read(); env.setup.tabs = [];
  const result = await env.read(); assert.equal(result.state, "cached"); assert.equal(result.snapshot.penaltyMinutes, 77);
  assert.equal(env.requests.length, 1); assert.equal(result.reason, "TAB_CLOSED");
});
test("changed replay identity never reuses the previous scoreboard snapshot", async () => {
  const env = environment(); await env.read(); env.session.ranklandUrl += "&ratio=30"; env.setup.tabs = [];
  const result = await env.read(); assert.equal(result.snapshot, null); assert.equal(result.state, "unavailable");
});
test("ambiguous pages and another run's response cannot become live scores", async () => {
  const env = environment(); env.setup.tabs.push({id: 8, url});
  assert.equal((await env.read()).state, "attention"); assert.equal(env.requests.length, 0);
  env.setup.tabs.pop(); env.setup.result.snapshot.sessionId = "other-run";
  assert.equal((await env.read()).snapshot, null); assert.equal(Object.keys(env.cache).length, 0);
});
test("zero score and penalty survive; missing rank remains unknown", async () => {
  const env = environment(); Object.assign(env.setup.result.snapshot, {rank: null, score: 0, penaltyMinutes: 0, ranks: [{label: "#", value: null}]});
  const result = await env.read(); assert.equal(result.state, "live"); assert.equal(result.snapshot.rank, null); assert.equal(result.snapshot.penaltyMinutes, 0);
});
test("unavailable content bridge preserves only marked cached evidence", async () => {
  const env = environment(); await env.read(); env.setup.fail = true;
  const result = await env.read(); assert.equal(result.state, "cached"); assert.equal(result.reason, "BRIDGE_UNAVAILABLE");
});
test("changing replay settings during an old read creates an independent task and preserves both caches", async () => {
  const env = environment(), pending = new Map();
  env.setup.handler = (_tabId, message) => new Promise(resolve => pending.set(message.expectedUrl, resolve));
  const first = env.read();
  await new Promise(setImmediate);
  const changedUrl = url + "&ratio=30";
  env.session.ranklandUrl = changedUrl; env.setup.tabs.push({id: 8, url: changedUrl});
  const second = env.read();
  await new Promise(setImmediate);
  assert.equal(env.requests.length, 2, "new replay settings must not share the old identity's in-flight promise");
  pending.get(changedUrl)({ready: true, snapshot: {...env.setup.result.snapshot, url: changedUrl, identity: identity(changedUrl),
    rank: 400, ranks: [{label: "#", value: 400}], penaltyMinutes: 90}});
  const newer = await second;
  assert.equal(newer.url, changedUrl); assert.equal(newer.snapshot.rank, 400);
  pending.get(url)(env.setup.result);
  const older = await first;
  assert.equal(older.url, url); assert.equal(older.snapshot.rank, 465);
  assert.equal(Object.keys(env.cache).length, 2);
  const restarted = environment(env.cache);
  restarted.session.ranklandUrl = changedUrl; restarted.setup.tabs = [];
  const cached = await restarted.read();
  assert.equal(cached.state, "cached"); assert.equal(cached.url, changedUrl);
  assert.equal(cached.snapshot.rank, 400); assert.equal(cached.snapshot.penaltyMinutes, 90);
});
