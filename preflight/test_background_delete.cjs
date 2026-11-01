"use strict";
// Exercise the unchanged production script through its runtime listener and
// native messaging ports. Deferred browser/native replies control ordering;
// dispatch, sync and exclusiveSync are never exported or substituted.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../extension/background.js"), "utf8");
const sid = "11111111-2222-4333-8444-555555555555";
const otherSid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const extensionId = "delete-test@littledrinks.local", origin = "moz-extension://delete-test/";
const tick = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function nativeError(code) { return Object.assign(new Error(code), {code}); }
function harness() {
  const nativeCalls = [], messages = [], events = [], hooks = {};
  const sessions = new Map([sid, otherSid].map(id => [id, {
    sessionId: id, state: "finished", startAt: 1000, durationMs: 5000, account: "Example",
    ranklandUrl: `https://vp.xcpc.link/?contest=example&run=${id}&at=2026-11-01T00%3A00%3A00Z`
  }]));
  const tabs = Array.from(sessions.values(), (session, index) => ({id: index + 7, url: session.ranklandUrl}));
  const cache = {sessions: Array.from(sessions.values())};
  let onMessage, onAlarm;
  const listener = {addListener() {}};
  function defaultNative(method, args) {
    if (method === "list_sessions") return {sessions: Array.from(sessions.values())};
    const session = sessions.get(args.sessionId);
    if (!session) throw nativeError("NOT_FOUND");
    if (method === "prepare_rankland" || method === "inspect_session") return {...session};
    if (method === "qoj_submissions") return {submissions: [], account: session.account};
    if (method === "rankland_queue") return {items: [{queueId: 1, submissionId: "1001", revision: 1, verdict: "AC"}]};
    if (method === "rankland_ack") return {acked: true};
    if (method === "delete_session") {
      assert.equal(args.confirmed, true);
      sessions.delete(args.sessionId);
      return {deleted: true, sessionId: args.sessionId};
    }
    throw Error("Unexpected native method: " + method);
  }
  const browser = {
    runtime: {
      id: extensionId, getURL: name => origin + name,
      onMessage: {addListener: fn => { onMessage = fn; }}, onInstalled: listener,
      connectNative: host => {
        assert.equal(host, "org.littledrinks.qoj_vp");
        const received = [], disconnected = [];
        let closed = false;
        return {
          onMessage: {addListener: fn => received.push(fn)},
          onDisconnect: {addListener: fn => disconnected.push(fn)},
          disconnect() { closed = true; for (const fn of disconnected) fn(); },
          postMessage(task) {
            assert.equal(task.type, "task");
            const {method, args} = task;
            nativeCalls.push({method, args}); events.push(`native:${method}:${args.sessionId || ""}`);
            Promise.resolve().then(() => hooks.native ? hooks.native(method, args, defaultNative) : defaultNative(method, args)).then(
              result => ({type: "result", id: task.id, ok: true, result, pid: 7}),
              error => ({type: "result", id: task.id, ok: false, error: {code: error.code || "TEST_NATIVE_ERROR", message: error.message}})
            ).then(reply => {
              assert.equal(closed, false, "the native result must arrive before port closure");
              events.push(`reply:${method}:${args.sessionId || ""}`);
              for (const fn of received) fn(reply);
            });
          }
        };
      }
    },
    tabs: {
      query: async () => tabs,
      update: async id => tabs.find(tab => tab.id === id),
      sendMessage: async (id, message) => {
        messages.push(message); events.push(`message:${message.type}:${message.sessionId}`);
        if (hooks.message) return hooks.message(id, message, defaultMessage);
        return defaultMessage(id, message);
      },
      create: async () => { throw Error("Unexpected tab creation"); }
    },
    scripting: {executeScript: async () => { throw Error("Unexpected bridge injection"); }},
    storage: {local: {
      get: async key => ({[key]: cache[key]}),
      set: async values => {
        if (hooks.store) await hooks.store(values);
        Object.assign(cache, values);
      }
    }},
    action: {onClicked: listener},
    alarms: {create() {}, onAlarm: {addListener: fn => { onAlarm = fn; }}}
  };
  function defaultMessage(_id, message) {
    if (message.type === "vp.rankland.ready") return {ready: true};
    if (message.type === "vp.rankland.deliver") return {state: "synced", receipt: {submissionId: message.item.submissionId}};
    throw Error("Unexpected tab message: " + message.type);
  }
  vm.runInNewContext(source, {
    browser, URL, Map, Set, Promise, Date, crypto: require("node:crypto").webcrypto,
    VpTransport: {pause: async () => {}, diagnostics: () => ({})},
    setTimeout: (...args) => setTimeout(...args).unref(), clearTimeout
  }, {filename: "extension/background.js"});
  return {
    hooks, nativeCalls, messages, events, sessions, cache,
    task: (method, args = {}) => onMessage({type: "vp.task", method, args}, {id: extensionId, url: origin + "ui.html"}),
    alarm: () => onAlarm({name: "vp-refresh"}),
    count: (method, id = sid) => nativeCalls.filter(call => call.method === method && call.args.sessionId === id).length
  };
}

test("deletion waits for production deliver and ack, blocks new sync, and keeps other sessions independent", async () => {
  const h = harness(), deliver = deferred(), ack = deferred();
  h.hooks.message = (id, message, fallback) => message.type === "vp.rankland.deliver" && message.sessionId === sid
    ? deliver.promise : fallback(id, message);
  h.hooks.native = (method, args, fallback) => method === "rankland_ack" && args.sessionId === sid ? ack.promise : fallback(method, args);
  const syncing = h.task("rankland.sync", {sessionId: sid});
  await tick();
  assert.equal(h.messages.filter(message => message.type === "vp.rankland.deliver").length, 1);
  let deleted = false;
  const deleting = h.task("delete_session", {sessionId: sid, confirmed: true}).then(value => { deleted = true; return value; });
  const duplicate = h.task("delete_session", {sessionId: sid, confirmed: true});
  const unconfirmed = await h.task("delete_session", {sessionId: sid, confirmed: false});
  assert.equal(unconfirmed.error.code, "CONFIRMATION_REQUIRED");
  const blocked = await h.task("rankland.sync", {sessionId: sid});
  assert.equal(blocked.error.code, "SESSION_DELETING");
  assert.equal(h.count("prepare_rankland"), 1, "a rejected sync must not reach the helper");
  assert.equal(h.count("delete_session"), 0);
  assert.equal(deleted, false);
  const other = await h.task("rankland.sync", {sessionId: otherSid});
  assert.equal(other.ok, true); assert.equal(other.result.synced, 1);
  assert.equal(h.count("rankland_ack", otherSid), 1);
  deliver.resolve({state: "synced", receipt: {submissionId: "1001"}});
  await tick();
  assert.equal(h.count("rankland_ack"), 1); assert.equal(h.count("delete_session"), 0);
  assert.equal(deleted, false, "delivery alone must not release deletion before ack");
  ack.resolve({acked: true});
  assert.equal((await syncing).result.synced, 1);
  const result = await deleting;
  assert.equal(result.ok, true); assert.equal(result.result.deleted, true);
  assert.equal((await duplicate).result.deleted, true);
  assert.equal(h.count("delete_session"), 1, "duplicate confirmed requests must share one deletion");
  assert.ok(h.events.indexOf(`reply:rankland_ack:${sid}`) < h.events.indexOf(`native:delete_session:${sid}`));
  const after = h.events.length;
  assert.equal((await h.task("rankland.sync", {sessionId: sid})).error.code, "SESSION_DELETED");
  assert.equal((await h.task("rankland.open", {sessionId: sid})).error.code, "SESSION_DELETED");
  await tick();
  assert.equal(h.events.length, after, "nothing can deliver or ack after successful deletion");
  assert.deepEqual(h.cache.sessions.map(session => session.sessionId), [otherSid]);
});

test("an existing failed sync settles before local deletion and does not block it", async () => {
  const h = harness(), queue = deferred();
  h.hooks.native = (method, args, fallback) => method === "rankland_queue" ? queue.promise : fallback(method, args);
  const syncing = h.task("rankland.sync", {sessionId: sid});
  await tick();
  assert.equal(h.count("rankland_queue"), 1);
  const deleting = h.task("delete_session", {sessionId: sid, confirmed: true});
  assert.equal(h.count("delete_session"), 0);
  queue.reject(nativeError("QUEUE_UNAVAILABLE"));
  assert.equal((await syncing).error.code, "QUEUE_UNAVAILABLE");
  assert.equal((await deleting).result.deleted, true);
  assert.equal(h.count("rankland_ack"), 0);
  assert.equal(h.messages.some(message => message.type === "vp.rankland.deliver"), false);
});

for (const trigger of ["task", "alarm"]) {
  test(`a late ${trigger} refresh cannot start a sync after deletion has succeeded`, async () => {
    const h = harness(), refresh = deferred();
    h.hooks.native = (method, args, fallback) => method === "qoj_submissions" ? refresh.promise : fallback(method, args);
    if (trigger === "alarm") h.cache.sessions = [{...h.sessions.get(sid), state: "running", startAt: Date.now(), durationMs: 60000}];
    const refreshing = trigger === "task" ? h.task("qoj_submissions", {sessionId: sid, refresh: true}) : h.alarm();
    await tick();
    assert.equal(h.count("qoj_submissions"), 1);
    assert.equal((await h.task("delete_session", {sessionId: sid, confirmed: true})).result.deleted, true);
    refresh.resolve({submissions: []});
    await refreshing; await tick();
    assert.equal(h.count("inspect_session"), 0, "tombstone must reject before another helper starts");
    assert.equal(h.count("prepare_rankland"), 0);
    assert.equal(h.messages.length, 0);
    assert.equal(h.count("rankland_ack"), 0);
  });
}

test("native deletion failure releases the barrier so a later sync and delete retry can run", async () => {
  const h = harness(), deletion = deferred();
  h.hooks.native = (method, args, fallback) => method === "delete_session" ? deletion.promise : fallback(method, args);
  const deleting = h.task("delete_session", {sessionId: sid, confirmed: true});
  await tick();
  assert.equal((await h.task("rankland.sync", {sessionId: sid})).error.code, "SESSION_DELETING");
  deletion.reject(nativeError("UNRESOLVED_SUBMISSION"));
  assert.equal((await deleting).error.code, "UNRESOLVED_SUBMISSION");
  assert.equal((await h.task("rankland.sync", {sessionId: sid})).result.synced, 1);
  h.hooks.native = null;
  assert.equal((await h.task("delete_session", {sessionId: sid, confirmed: true})).result.deleted, true);
  assert.equal(h.count("delete_session"), 2);
});

for (const failure of ["list_sessions", "storage"]) {
  test(`a ${failure} cache failure after native deletion preserves the successful result and tombstone`, async () => {
    const h = harness();
    if (failure === "list_sessions") h.hooks.native = (method, args, fallback) => {
      if (method === "list_sessions") throw nativeError("CACHE_REFRESH_FAILED");
      return fallback(method, args);
    };
    else h.hooks.store = values => { if (values.sessions) throw Error("storage failed"); };
    const result = await h.task("delete_session", {sessionId: sid, confirmed: true});
    assert.equal(result.ok, true); assert.equal(result.result.deleted, true);
    assert.equal(result.result.sessionsRefreshFailed, true);
    assert.equal(h.sessions.has(sid), false);
    assert.equal((await h.task("rankland.sync", {sessionId: sid})).error.code, "SESSION_DELETED");
    assert.equal(h.count("prepare_rankland"), 0); assert.equal(h.messages.length, 0);
  });
}
