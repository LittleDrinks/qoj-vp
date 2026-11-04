"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const projectionSource = fs.readFileSync(path.join(__dirname, "../extension/rankland-projection.js"), "utf8");
const protocolSource = fs.readFileSync(path.join(__dirname, "../extension/rankland-protocol.js"), "utf8");
const transferSource = fs.readFileSync(path.join(__dirname, "../extension/rankland-transfer.js"), "utf8");
const sessionId = "11111111-2222-4333-8444-555555555555";
const url = `https://vp.xcpc.link/?contest=fixture&run=${sessionId}&rule=ICPC&from=0`;
const row = (problemIndex, timeMs, result) => ({problemIndex, timeMs, result});
const submission = (id, elapsedMs, verdict = "CORRECT", revision = 1, problemLabel = "A") =>
  ({sourceId: `qoj:tester:${id}`, submissionId: String(id), revision, elapsedMs, verdict, rawVerdict: verdict, problemLabel});
const freshArchive = extra => ({version: 2, elapsed: 5100000, savedAt: 1800000000000,
  running: true, speed: 1, ownName: "Existing team name", ownOrganization: "Existing organization", manual: [], ...extra});
const clone = value => structuredClone(value);
const code = expected => error => error.code === expected;

// The browser transport is fake, but executeScript serializes and executes the
// actual production function in a separate page realm, including its exact URL
// guard, DOM checks, localStorage read/write, and compare-and-set. Vue rendering
// is intentionally represented by a minimal DOM, not claimed as a browser test.
function environment(extra = {}) {
  const replayUrl = extra.url || url;
  const session = {sessionId, ranklandUrl: replayUrl};
  const state = {tab: {id: 7, url:replayUrl}, otherTabs: [], bundle: "/assets/index-ad07c00e.js",
    labels: ["A", "B", "C", "D"], ownRow: true, gateHasBoard: false, navigations: [],
    writes: [], executions: [], extension: {}, sourceCalls: [], queryCount: 0, ...extra};
  const pageStorage = new Map();
  let api;
  const pageContext = vm.createContext({URL, location: {href: state.tab.url},
    localStorage: {
      getItem: key => pageStorage.get(key) ?? null,
      setItem: (key, value) => { state.writes.push({key, value}); pageStorage.set(key, String(value)); },
    },
    document: {
      get scripts() { return [{src: new URL(state.bundle, replayUrl).href}]; },
      querySelector(selector) {
        assert.equal(selector, '[data-id="vp-ranklist-content"]');
        if (!new URL(state.tab.url).searchParams.has("contest") && !state.gateHasBoard) return null;
        return {querySelectorAll(selector) {
          if (selector === ".srk-main > table thead .srk-problem-header") return state.labels.map(label =>
            ({querySelector: () => ({textContent: label})}));
          assert.equal(selector, ".srk-user-name-text");
          return state.ownRow ? [{textContent: ((extra.modern || Array.isArray(JSON.parse(pageStorage.get(api.archiveKey(replayUrl)) ?? "null"))) ? new URL(state.tab.url).searchParams.get("team") : JSON.parse(pageStorage.get(api.archiveKey(replayUrl)) ?? "null")?.ownName),
            closest: () => ({getClientRects: () => [{}]})}] : [];
        }};
      },
    },
  });
  const context = vm.createContext({URL, Date, Map, Set, Promise,
    setTimeout: callback => { queueMicrotask(callback); return 1; },
    VpScoreboardSources: {describeReplay: async raw => {
      state.sourceCalls.push(raw);
      return {durationMs: 18000000, problems: state.labels.map((label, index) => ({label, index}))};
    }},
    browser: {
      tabs: {
        query: async () => { state.queryCount++; await state.onQuery?.(state); return clone([state.tab, ...state.otherTabs]); },
        get: async id => { assert.equal(id, state.tab.id); return clone(state.tab); },
        update: async (id, options) => {
          assert.equal(id, state.tab.id);
          state.navigations.push(options.url);
          await state.onNavigate?.(options.url, state);
          state.tab.url = state.redirectNavigation || options.url;
          pageContext.location.href = state.tab.url;
          return clone(state.tab);
        },
      },
      storage: {local: {
        get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys])
          .filter(key => Object.hasOwn(state.extension, key)).map(key => [key, clone(state.extension[key])])),
        set: async values => { await state.onExtensionSet?.(values, state); Object.assign(state.extension, clone(values)); },
        remove: async key => { delete state.extension[key]; },
      }},
      scripting: {executeScript: async ({target, func, args, files}) => {
        if (files) { vm.runInContext(protocolSource,pageContext); return [{result:null}]; }
        assert.equal(target.tabId, state.tab.id);
        const arg = args[0];
        state.executions.push(clone(arg));
        if (arg.write) await state.beforeWrite?.(state, pageStorage, arg);
        pageContext.args = clone(args);
        const result = vm.runInContext(`(${func.toString()})(...args)`, pageContext);
        if (arg.write && state.loseWriteReplyOnce) {
          state.loseWriteReplyOnce = false;
          throw new Error("Simulated extension disconnect after page write");
        }
        return [{result: clone(result)}];
      }},
    },
  });
  vm.runInContext(protocolSource, pageContext);
  vm.runInContext(protocolSource, context);
  vm.runInContext(projectionSource, context);
  vm.runInContext(transferSource, context);
  api = context.VpRanklandTransfer;
  const targetKey = api.archiveKey(replayUrl);
  if (!extra.empty) pageStorage.set(targetKey, JSON.stringify(extra.modern ? (extra.manual || []) : freshArchive(extra.archive)));
  const sync = items => api.sync({session, tabId: state.tab.id, plan: {items, allItems: items}});
  return {state, api, session, pageStorage, targetKey, sync,
    read: () => JSON.parse(pageStorage.get(targetKey)),
    replace: archive => pageStorage.set(targetKey, JSON.stringify(archive)),
    setUrl: raw => { state.tab.url = raw; pageContext.location.href = raw; },
    metadataKey: prefix => Object.keys(state.extension).find(key => key.startsWith(prefix)),
  };
}

test("sync imports a five-minute-delayed verdict at its exact original timestamp", async () => {
  const env = environment();
  const result = await env.sync([submission(101, 4800123)]);
  assert.equal(result.synced, 1);
  assert.deepEqual(env.read().manual, [row(0, 4800123, "AC")]);
  assert.deepEqual(env.state.navigations, [env.api.gateUrl(env.session), url]);
  assert.equal(env.state.writes.length, 1);
  assert.equal(env.metadataKey("rankland-transfer-v1:"), undefined, "Only a verified commit clears the transaction journal");
});

test("finished and paused replays retain their clock, speed, team, and unowned attempts", async () => {
  for (const extra of [{elapsed: 18000000, running: false}, {elapsed: 8000000, running: false, speed: 5}]) {
    const manual = [row(2, 40000, "WA")];
    const env = environment({archive: {...extra, manual}}), before = env.read();
    await env.sync([submission(101, 17999000)]);
    assert.deepEqual(env.read(), {...before, manual: [...manual, row(0, 17999000, "AC")]});
  }
});

test("two real same-second WA submissions both survive the transfer and retry", async () => {
  const env = environment();
  const items = [submission(101, 1200123, "WRONG-ANSWER"), submission(102, 1200123, "WRONG-ANSWER"),
    submission(103, 1300000)];
  await env.sync(items);
  assert.deepEqual(env.read().manual, [row(0, 1200123, "WA"), row(0, 1200123, "WA"), row(0, 1300000, "AC")]);
  const before = {writes: env.state.writes.length, navigations: env.state.navigations.length};
  const again = await env.sync(items);
  assert.equal(again.synced, 0);
  assert.equal(env.state.writes.length, before.writes);
  assert.equal(env.state.navigations.length, before.navigations);
});

test("rejudging replaces AC, and pending withdrawal removes only that source", async () => {
  const env = environment({archive: {manual: [row(3, 1000, "AC")]}});
  await env.sync([submission(101, 2000123), submission(102, 2100000, "CORRECT", 1, "B")]);
  await env.sync([submission(101, 2000123, "TIMELIMIT", 3), submission(102, 2100000, "CORRECT", 1, "B")]);
  assert.deepEqual(env.read().manual, [row(3, 1000, "AC"), row(0, 2000123, "TLE"), row(1, 2100000, "AC")]);
  await env.sync([submission(102, 2100000, "CORRECT", 1, "B")]);
  assert.deepEqual(env.read().manual, [row(3, 1000, "AC"), row(1, 2100000, "AC")]);
});

test("a lost reply after the page writes recovers ownership from its journal without another import", async () => {
  const env = environment({loseWriteReplyOnce: true});
  const items = [submission(101, 4800123)];
  await assert.rejects(env.sync(items), /Simulated extension disconnect/);
  assert.deepEqual(env.read().manual, [row(0, 4800123, "AC")]);
  assert.equal(env.metadataKey("rankland-owned-v1:"), undefined);
  assert.ok(env.metadataKey("rankland-transfer-v1:"));
  assert.equal(env.state.tab.url, url, "Failure returns to the original replay");
  const before = {writes: env.state.writes.length, navigations: env.state.navigations.length};
  await env.sync(items);
  assert.equal(env.read().manual.length, 1);
  assert.ok(env.metadataKey("rankland-owned-v1:"));
  assert.equal(env.metadataKey("rankland-transfer-v1:"), undefined);
  assert.equal(env.state.writes.length, before.writes);
  assert.equal(env.state.navigations.length, before.navigations);
});

test("ownership persistence failure after readback remains recoverable", async () => {
  const env = environment();
  env.state.onExtensionSet = async values => {
    if (Object.keys(values).some(key => key.startsWith("rankland-owned-v1:"))) {
      env.state.onExtensionSet = null;
      throw new Error("Simulated ownership commit failure");
    }
  };
  const items = [submission(101, 4800123)];
  await assert.rejects(env.sync(items), /ownership commit failure/);
  assert.equal(env.state.writes.length, 1);
  await env.sync(items);
  assert.equal(env.state.writes.length, 1);
  assert.equal(env.read().manual.length, 1);
});

test("changed owned records stop synchronization without overwriting user state", async () => {
  const env = environment(), items = [submission(101, 4800123)];
  await env.sync(items);
  env.replace({...env.read(), manual: [row(0, 4800123, "WA")]});
  const before = {writes: env.state.writes.length, navigations: env.state.navigations.length};
  await assert.rejects(env.sync(items), code("RANKLAND_OWNERSHIP_CONFLICT"));
  assert.deepEqual(env.read().manual, [row(0, 4800123, "WA")]);
  assert.equal(env.state.writes.length, before.writes);
  assert.equal(env.state.navigations.length, before.navigations);
});

test("a concurrent storage edit defeats the page compare-and-set", async () => {
  const env = environment();
  env.state.beforeWrite = async () => env.replace({...env.read(), manual: [row(3, 20000, "WA")]});
  await assert.rejects(env.sync([submission(101, 4800123)]), code("RANKLAND_STORAGE_CHANGED"));
  assert.deepEqual(env.read().manual, [row(3, 20000, "WA")]);
  assert.equal(env.state.writes.length, 0);
  assert.ok(env.metadataKey("rankland-transfer-v1:"));
  assert.equal(env.state.tab.url, url);
});

test("pagehide clock updates and last manual edits are rebased before writing", async () => {
  const env = environment();
  env.state.onNavigate = async target => {
    if (target === env.api.gateUrl(env.session)) {
      env.replace({...env.read(), elapsed: 5400123, savedAt: 1800000300000,
        manual: [row(3, 5300000, "WA")]});
    }
  };
  await env.sync([submission(101, 4800123)]);
  assert.equal(env.read().elapsed, 5400123);
  assert.equal(env.read().savedAt, 1800000300000);
  assert.deepEqual(env.read().manual, [row(3, 5300000, "WA"), row(0, 4800123, "AC")]);
});

test("another replay writer or navigation away refuses delivery", async () => {
  const env = environment({otherTabs: [{id: 8, url}]});
  await assert.rejects(env.sync([submission(101, 4800123)]), code("RANKLAND_MULTIPLE_WRITERS"));
  assert.equal(env.state.navigations.length, 0);
  assert.equal(env.state.writes.length, 0);
  const navigated = environment();
  navigated.state.tab.url = "https://vp.xcpc.link/?contest=other";
  await assert.rejects(navigated.sync([submission(101, 4800123)]), code("RANKLAND_SESSION_MISMATCH"));
  assert.equal(navigated.state.navigations.length, 0);
});

test("a writer appearing after staging is caught before the archive is written", async () => {
  const env = environment();
  env.state.onQuery = state => { if (state.queryCount === 3) state.otherTabs.push({id: 8, url}); };
  await assert.rejects(env.sync([submission(101, 4800123)]), code("RANKLAND_MULTIPLE_WRITERS"));
  assert.equal(env.state.writes.length, 0);
  assert.deepEqual(env.read().manual, []);
});

test("navigation away during staging never writes or forcibly returns the user's tab", async () => {
  const destination = "https://vp.xcpc.link/?contest=user-chosen";
  const env = environment({redirectNavigation: destination});
  await assert.rejects(env.sync([submission(101, 4800123)]), code("RANKLAND_LOAD_TIMEOUT"));
  assert.equal(env.state.writes.length, 0);
  assert.equal(env.state.tab.url, destination);
  assert.deepEqual(env.state.navigations, [env.api.gateUrl(env.session)]);
});

test("the gate must have fully left the live replay before any write", async () => {
  const env = environment({gateHasBoard: true});
  await assert.rejects(env.sync([submission(101, 4800123)]), code("REPLAY_STILL_RUNNING"));
  assert.equal(env.state.writes.length, 0);
  assert.equal(env.state.tab.url, url);
});

test("unsupported archive format fails before navigation", async () => {
  const env = environment({archive: {version: 3}});
  await assert.rejects(env.sync([submission(101, 4800123)]), code("RANKLAND_SCHEMA_CHANGED"));
  assert.equal(env.state.writes.length, 0);
  assert.equal(env.state.navigations.length, 0);
});

test("resuming a staged import does not require a particular build fingerprint", async () => {
  const env = environment({bundle: "/assets/index-new-upstream.js"});
  env.setUrl(env.api.gateUrl(env.session));
  assert.equal((await env.sync([submission(101, 4800123)])).synced, 1);
});

test("an incompatible storage change during staging still prevents mutation", async () => {
  const env = environment();
  env.state.onNavigate = async target => {
    if (target === env.api.gateUrl(env.session)) env.replace({version:3,manual:[]});
  };
  await assert.rejects(env.sync([submission(101, 4800123)]), code("RANKLAND_SCHEMA_CHANGED"));
  assert.equal(env.state.writes.length, 0);
});

// A deployment fingerprint is not a storage protocol version.
test("a cosmetic upstream bundle rebuild does not block the verified storage contract", async () => {
  const env = environment({bundle: "/assets/index-cosmetic-rebuild.js"});
  const result = await env.sync([submission(101, 4800123)]);
  assert.equal(result.synced, 1);
  assert.deepEqual(env.read().manual, [row(0, 4800123, "AC")]);
});

const modernUrl = "https://vp.xcpc.link/?contest=fixture&at=2026-11-04T00%3A00%3A00.000Z&from=0&play=1&speed=1&team=TestTeam";
test("current manual-array storage imports delayed exact timestamps and survives a new deployment", async () => {
  const env=environment({url:modernUrl,modern:true,bundle:"/assets/index-whatever.js"});
  const items=[submission(101,4800123)];
  await env.sync(items);
  assert.deepEqual(env.read(),[row(0,4800123,"AC")]);
  assert.equal((await env.sync(items)).synced,0);
  assert.equal(env.state.writes.length,1);
  assert.equal(env.state.tab.url,modernUrl);
});
test("first current import can create an absent submissions array", async () => {
  const env=environment({url:modernUrl,modern:true,empty:true});
  await env.sync([submission(101,4800123)]);
  assert.deepEqual(env.read(),[row(0,4800123,"AC")]);
});
test("current rejudge and withdrawal preserve unowned attempts and replay settings", async () => {
  const actual=modernUrl.replace('from=0&play=1&speed=1','from=40&play=0&speed=5')+'&anchor=2026-11-04T01%3A00%3A00Z';
  const env=environment({url:actual,modern:true,manual:[row(3,20000,"WA")]});
  env.session.ranklandUrl=modernUrl;
  await env.sync([submission(101,4800123)]);
  await env.sync([submission(101,4800123,"TIMELIMIT",2)]);
  assert.deepEqual(env.read(),[row(3,20000,"WA"),row(0,4800123,"TLE")]);
  assert.equal(env.state.tab.url,actual);
  await env.sync([]);
  assert.deepEqual(env.read(),[row(3,20000,"WA")]);
});
test("current array write reply loss is recovered without duplicating records", async () => {
  const env=environment({url:modernUrl,modern:true,loseWriteReplyOnce:true});
  const items=[submission(101,4800123)];
  await assert.rejects(env.sync(items),/Simulated extension disconnect/);
  await env.sync(items);
  assert.deepEqual(env.read(),[row(0,4800123,"AC")]);
  assert.equal(env.state.writes.length,1);
});
test("unknown current records and another clock's writer cannot be overwritten", async () => {
  const env=environment({url:modernUrl,modern:true,manual:[{...row(0,123,"AC"),newMeaning:true}]});
  await assert.rejects(env.sync([submission(101,4800123)]),code("RANKLAND_SCHEMA_CHANGED"));
  assert.equal(env.state.writes.length,0);
  const multiple=environment({url:modernUrl,modern:true,otherTabs:[{id:9,url:modernUrl.replace('play=1','play=0')}]});
  await assert.rejects(multiple.sync([submission(101,4800123)]),code("RANKLAND_MULTIPLE_WRITERS"));
  assert.equal(multiple.state.writes.length,0);
});
