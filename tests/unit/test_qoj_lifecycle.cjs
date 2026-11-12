"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../src/firefox/qoj-lifecycle.js"), "utf8");
const cid = "2644", account = "LittleDrinks", sid = "11111111-2222-4333-8444-555555555555";
const register = "https://qoj.ac/contest/2644/virtual/register", dashboard = "https://qoj.ac/contest/2644";
const now = 1800000000000, serverStart = now - 301234, intentKey = "qoj-native-start:7", rulesKey = "qoj-native-registration:7";
const registrationPage = {url:register, html:'<ul class="nav nav-pills float-right"><li><a href="/user/profile/LittleDrinks">LittleDrinks</a></li></ul><ul><li>The contest is 300 minutes long.</li><li>Each wrong submission adds 20 minutes of penalty.</li></ul><form id="form-register_vp" method="post" action="/contest/2644/virtual/register"><button id="button-submit-register_vp" type="submit" name="submit-register_vp"></button></form>'};
const sender = (tabId = 7, url = register) => ({id:"extension-test", frameId:0, url, tab:{id:tabId}});
const copy = value => value === undefined ? undefined : structuredClone(value);
const deferred = () => { let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve}; };
const turn = () => new Promise(setImmediate);
function bound({started = false, username = account} = {}) {
  return {sessionId:sid, contestId:cid, account:username, state:started ? "running" : "prepared", startAt:started ? serverStart : null,
    qojVirtual:{mode:"qoj-native", origin:"https://qoj.ac", contestId:cid, account:username, startAt:started ? serverStart : null}};
}
const reply = started => ({session:bound({started}), virtual:{state:started ? "running" : "unknown"}});
const pending = () => ({cid, tabId:7, observedAt:now, sessionId:sid, account});
const completed = (tabId = 7) => ({url:register, method:"POST", type:"main_frame", statusCode:302, tabId});
function environment({initial = {}, openedTabs = [{id:7, url:register}], onNative = null, clock = () => now} = {}) {
  const data = copy(initial), calls = [], opened = [], tabMap = new Map(openedTabs.map(tab => [tab.id, copy(tab)]));
  const storage = {
    get:async key => key === null ? copy(data) : {[key]:copy(data[key])},
    set:async values => {Object.assign(data, copy(values));},
    remove:async key => {delete data[key];}
  };
  const tabs = {
    get:async id => {if (!tabMap.has(id)) throw Error("Tab closed: " + id); return copy(tabMap.get(id));},
    query:async () => [...tabMap.values()].filter(tab => tab.url.startsWith("https://qoj.ac/contest/")).map(copy)
  };
  const context = {URL, browser:{runtime:{id:"extension-test"}}};
  vm.createContext(context); vm.runInContext(source, context);
  let handler = onNative;
  const native = async (method, args) => {
    calls.push({method, args:copy(args)});
    if (handler) {const answer = await handler(method, args); if (answer !== undefined) return copy(answer);}
    if (method === "qoj_bind_virtual") return {session:bound()};
    if (method === "qoj_confirm_virtual_start") return reply(false);
    if (method === "list_sessions") return {sessions:[bound()]};
    throw Error("Unexpected native action " + method);
  };
  const options = {native, storage, tabs, clock, openSession:async (session, settings) => opened.push({session:copy(session), settings:copy(settings)})};
  return {flow:context.VpQojLifecycle.create(options), restart:() => context.VpQojLifecycle.create(options),
    data, calls, opened, tabMap, setHandler(value) {handler = value;}};
}

test("register preparation shares a binding and opens that exact prepared session without starting", async () => {
  const env = environment();
  const results = await Promise.all([env.flow.prepare({cid}, sender()), env.flow.prepare({cid}, sender())]);
  assert.deepEqual(results.map(result => result.sessionId), [sid, sid]);
  assert.equal(env.calls.filter(call => call.method === "qoj_bind_virtual").length, 1);
  assert.equal(env.calls.filter(call => call.method === "list_sessions").length, 1);
  assert.equal(env.calls.some(call => call.method === "qoj_confirm_virtual_start"), false);
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].session.sessionId, sid);
  assert.deepEqual(env.opened[0].settings, {prepare:true, active:true});
  assert.equal(env.opened[0].session.startAt, null); assert.equal(env.data[intentKey], undefined);
  await env.flow.prepare({cid}, sender());
  assert.equal(env.opened[1].session.sessionId, sid);
});

test("readiness binds the QOJ account without opening a tab or starting its clock", async () => {
  const env = environment();
  const result = await env.flow.bind({cid, registrationPage}, sender());
  assert.equal(result.sessionId, sid);
  assert.equal(env.opened.length, 0);
  assert.equal(env.calls.some(call => call.method === "qoj_confirm_virtual_start"), false);
  assert.equal(env.data[intentKey], undefined);
  await assert.rejects(env.flow.bind({cid}, sender(7, dashboard)));
});

test("invalid account, contest or native binding never opens a prepared session", async () => {
  for (const session of [null, {...bound(), contestId:"999"}, {...bound(), account:"someone-else"},
    {...bound(), qojVirtual:{...bound().qojVirtual, mode:"local"}},
    {...bound(), qojVirtual:{...bound().qojVirtual, origin:"https://other.example"}}]) {
    const env = environment({onNative:async method => method === "qoj_bind_virtual" ? {session} : undefined});
    await assert.rejects(env.flow.prepare({cid}, sender()));
    assert.equal(env.opened.length, 0); assert.equal(env.calls.length, 1);
  }
});

test("preparation finishing after a verified native Start does not reopen or reload the resource page", async () => {
  const entered = deferred(), release = deferred(); let lists = 0;
  const env = environment({onNative:async method => {
    if (method === "list_sessions" && ++lists === 1) {entered.resolve(); await release.promise; return {sessions:[bound()]};}
    if (method === "qoj_confirm_virtual_start") return reply(true);
  }});
  const preparing = env.flow.prepare({cid}, sender()); await entered.promise;
  const started = await env.flow.startIntent({cid}, sender());
  assert.equal(started.state, "started"); assert.equal(env.opened.length, 1);
  release.resolve(); const prepared = await preparing;
  assert.equal(prepared.sessionId, sid);
  assert.equal(env.opened.length, 1, "a late prepare must not reload the workbench after Start");
  assert.equal(env.opened[0].settings.prepare, false); assert.equal(env.opened[0].session.startAt, serverStart);
});

test("the verified Start protects its session while its own list refresh is still pending", async () => {
  const entered = deferred(), release = deferred(); let lists = 0;
  const env = environment({initial:{[intentKey]:pending()}, onNative:async method => {
    if (method === "qoj_confirm_virtual_start") return reply(true);
    if (method === "list_sessions" && ++lists === 1) {entered.resolve(); await release.promise; return {sessions:[bound({started:true})]};}
  }});
  const starting = env.flow.check({cid}, sender()); await entered.promise;
  await env.flow.prepare({cid}, sender());
  assert.equal(env.opened.length, 0, "preparation cannot reopen while confirmed Start is completing");
  release.resolve(); assert.equal((await starting).state, "started");
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].settings.prepare, false);
});

test("an unconfirmed Start does not suppress subsequent resource preparation", async () => {
  const env = environment(); assert.equal((await env.flow.startIntent({cid}, sender())).state, "waiting");
  await env.flow.prepare({cid}, sender());
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].settings.prepare, true);
});

test("an observed native POST completes the workflow even when QOJ bypasses DOM submit events", async () => {
  const env = environment({onNative:async method => method === "qoj_confirm_virtual_start" ? reply(true) : undefined});
  // No startIntent message: the browser observes the original request itself.
  const recording = env.flow.submitted(completed());
  env.tabMap.set(7, {id:7, url:dashboard});
  const checking = env.flow.completed(completed());
  await recording; assert.equal((await checking).state, "started");
  assert.equal(env.calls.filter(call => call.method === "qoj_bind_virtual").length, 1);
  assert.equal(env.calls.filter(call => call.method === "qoj_confirm_virtual_start").length, 1);
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].session.startAt, serverStart);
  assert.equal(env.data[intentKey], undefined);
});

test("direct native Start uses the saved registration rules without preparation or a DOM submit event", async () => {
  const env = environment({onNative:async (method, args) => {
    if (method === "qoj_bind_virtual") {assert.deepEqual(copy(args.registrationPage), registrationPage); return {session:bound()};}
    if (method === "qoj_confirm_virtual_start") return reply(true);
  }});
  assert.equal((await env.flow.registration({cid, registrationPage}, sender())).ready, true);
  assert.equal(env.calls.length, 0); assert.equal(env.opened.length, 0);
  assert.deepEqual(env.data[rulesKey], {cid, observedAt:now, registrationPage});
  await env.flow.submitted(completed());
  assert.deepEqual(env.data[intentKey].registrationPage, registrationPage);
  env.tabMap.set(7, {id:7, url:dashboard});
  assert.equal((await env.flow.completed(completed())).state, "started");
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].settings.prepare, false);
  assert.equal(env.opened[0].session.startAt, serverStart);
  assert.equal(env.data[intentKey], undefined); assert.equal(env.data[rulesKey], undefined);
  assert.deepEqual(env.calls.map(call => call.method), ["qoj_bind_virtual", "qoj_confirm_virtual_start", "list_sessions"]);
});

test("registration rules arriving after the native POST still bind the direct Start", async () => {
  let started = false;
  const env = environment({onNative:async (method, args) => {
    if (method === "qoj_bind_virtual") {assert.deepEqual(copy(args.registrationPage), registrationPage); return {session:bound()};}
    if (method === "qoj_confirm_virtual_start") return reply(started);
  }});
  await env.flow.submitted(completed());
  assert.equal(env.data[intentKey].registrationPage, undefined);
  await env.flow.registration({cid, registrationPage}, sender());
  started = true;
  env.tabMap.set(7, {id:7, url:dashboard});
  assert.equal((await env.flow.completed(completed())).state, "started");
  assert.equal(env.opened.length, 1); assert.equal(env.data[intentKey], undefined);
});

test("late registration rules queue a fresh bind after an in-flight bind without rules fails", async () => {
  const entered = deferred(), release = deferred(); let bindings = 0;
  const env = environment({onNative:async (method, args) => {
    if (method === "qoj_bind_virtual") {
      if (++bindings === 1) {assert.equal(args.registrationPage, undefined); entered.resolve(); await release.promise; throw Error("register redirected after native Start");}
      assert.deepEqual(copy(args.registrationPage), registrationPage); return {session:bound()};
    }
    if (method === "qoj_confirm_virtual_start") return reply(true);
  }});
  await env.flow.submitted(completed());
  const completing = env.flow.completed(completed()); await entered.promise;
  const registration = env.flow.registration({cid, registrationPage}, sender());
  await turn(); release.resolve();
  await Promise.all([completing, registration]);
  assert.equal(bindings, 2); assert.equal(env.opened.length, 1);
  assert.equal(env.opened[0].session.startAt, serverStart);
  assert.equal(env.data[intentKey], undefined); assert.equal(env.data[rulesKey], undefined);
});

test("a delayed registration message after completion never creates a new start intent", async () => {
  const env = environment({onNative:async method => method === "qoj_confirm_virtual_start" ? reply(true) : undefined});
  await env.flow.registration({cid, registrationPage}, sender());
  await env.flow.submitted(completed()); await env.flow.completed(completed());
  const nativeCount = env.calls.length;
  assert.equal((await env.flow.registration({cid, registrationPage}, sender())).ready, true);
  assert.equal(env.data[intentKey], undefined); assert.equal(env.calls.length, nativeCount);
  assert.equal(env.opened.length, 1);
});

test("preparation and DOM Start pass the same bounded registration snapshot to the helper", async () => {
  for (const action of ["prepare", "startIntent"]) {
    const env = environment(); await env.flow[action]({cid, registrationPage}, sender());
    assert.deepEqual(env.calls.find(call => call.method === "qoj_bind_virtual").args.registrationPage, registrationPage);
  }
});

test("an existing POST observation merges the snapshot supplied by a later DOM Start event", async () => {
  const env = environment();
  await Promise.all([env.flow.submitted(completed()), env.flow.startIntent({cid, registrationPage}, sender())]);
  assert.deepEqual(env.data[intentKey].registrationPage, registrationPage);
  assert.deepEqual(env.calls.find(call => call.method === "qoj_bind_virtual").args.registrationPage, registrationPage);
  assert.equal(env.calls.filter(call => call.method === "qoj_bind_virtual").length, 1);
});

test("registration evidence is rejected for a different origin, contest, page, type or excessive size", async () => {
  for (const evidence of [{...registrationPage, url:"https://elsewhere.invalid/contest/2644/virtual/register"},
    {...registrationPage, url:"https://qoj.ac/contest/999/virtual/register"}, {...registrationPage, url:dashboard},
    {...registrationPage, html:null}, {...registrationPage, html:"x".repeat(65537)}]) {
    for (const action of ["registration", "prepare", "startIntent"]) {
      const env = environment(); await assert.rejects(env.flow[action]({cid, registrationPage:evidence}, sender()));
      assert.deepEqual(env.data, {}); assert.equal(env.calls.length, 0); assert.equal(env.opened.length, 0);
    }
  }
  const env = environment(); assert.equal((await env.flow.registration({cid}, sender())).ready, false);
  assert.deepEqual(env.data, {});
});

test("rules from another contest, future observations or more than one day ago are not reused", async () => {
  for (const rules of [{cid:"999", observedAt:now, registrationPage},
    {cid, observedAt:now+1, registrationPage}, {cid, observedAt:now-24*60*60*1000-1, registrationPage}]) {
    const env = environment({initial:{[rulesKey]:rules}}); await env.flow.submitted(completed());
    assert.equal(env.data[intentKey].registrationPage, undefined);
  }
});

test("a saved direct-Start snapshot survives a background restart and tab change within one day", async () => {
  let observed = now;
  const env = environment({clock:() => observed, onNative:async (method, args) => {
    if (method === "qoj_bind_virtual") {assert.deepEqual(copy(args.registrationPage), registrationPage); assert.equal(args.httpTabId, 77); return {session:bound()};}
    if (method === "qoj_confirm_virtual_start") return reply(true);
  }});
  await env.flow.registration({cid, registrationPage}, sender()); await env.flow.submitted(completed());
  observed += 2*60*60*1000; env.tabMap.delete(7); env.tabMap.set(77, {id:77, url:dashboard});
  await env.restart().resume();
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].session.startAt, serverStart);
  assert.equal(env.data[intentKey], undefined); assert.equal(env.data[rulesKey], undefined);
});

test("observing a native POST only persists intent, and unrelated requests create no intent", async () => {
  const observed = environment(); await observed.flow.submitted(completed());
  assert.equal(observed.calls.length, 0); assert.equal(observed.opened.length, 0);
  assert.equal(observed.data[intentKey].cid, cid);
  for (const details of [{...completed(), method:"GET"}, {...completed(), type:"sub_frame"},
    {...completed(), url:dashboard}, {...completed(), url:dashboard+"/problem/123"},
    {...completed(), url:"https://other.example/contest/2644/virtual/register"}, {...completed(), tabId:-1}]) {
    const env = environment(); await env.flow.submitted(details);
    assert.deepEqual(env.data, {}); assert.equal(env.calls.length, 0); assert.equal(env.opened.length, 0);
  }
});

test("observing Start preserves pending intent; an unknown reply or failed POST cannot start a timer", async () => {
  const env = environment(), result = await env.flow.startIntent({cid}, sender());
  assert.equal(result.state, "waiting"); assert.equal(env.opened.length, 0);
  assert.equal(env.data[intentKey].sessionId, sid); assert.equal(env.data[intentKey].account, account);
  assert.equal(env.data[intentKey].observedAt, now);
  const before = env.calls.length;
  await env.flow.completed({...completed(), statusCode:500});
  await env.flow.completed({...completed(), method:"GET"});
  await env.flow.completed({...completed(), type:"sub_frame"});
  assert.equal(env.calls.length, before); assert.equal(env.opened.length, 0);
  assert.equal(env.data[intentKey].sessionId, sid);
});

test("only a verified server start opens Home, keeping QOJ time despite the later local observation", async () => {
  const env = environment(); await env.flow.startIntent({cid}, sender());
  env.setHandler(async method => method === "qoj_confirm_virtual_start" ? reply(true) : undefined);
  env.tabMap.set(7, {id:7, url:dashboard});
  const result = await env.flow.completed(completed());
  assert.equal(result.state, "started"); assert.equal(result.startAt, serverStart);
  assert.notEqual(result.startAt, now); assert.equal(env.data[intentKey], undefined);
  assert.equal(env.opened.length, 1); assert.equal(env.opened[0].session.startAt, serverStart);
  assert.deepEqual(env.opened[0].settings, {prepare:false, active:true});
  assert.equal(env.calls.filter(call => call.method === "qoj_bind_virtual").length, 1);
  assert.equal(env.calls.some(call => /^(start_session|update_session|submit)/.test(call.method)), false);
});

test("a running label without matching server start evidence remains pending", async () => {
  for (const result of [reply(false), {...reply(true), session:{...bound({started:true}), startAt:null}},
    {...reply(true), session:{...bound({started:true}), qojVirtual:{...bound({started:true}).qojVirtual, startAt:serverStart + 1}}}]) {
    const env = environment({initial:{[intentKey]:pending()}, onNative:async method => method === "qoj_confirm_virtual_start" ? result : undefined});
    const checked = await env.flow.check({cid}, sender());
    assert.equal(checked.state, "waiting"); assert.equal(env.opened.length, 0); assert.ok(env.data[intentKey]);
  }
});

test("a restarted background resumes the saved native intent after Firefox changes tab IDs", async () => {
  const env = environment(); await env.flow.startIntent({cid}, sender());
  env.tabMap.delete(7); env.tabMap.set(77, {id:77, url:dashboard});
  env.setHandler(async method => method === "qoj_confirm_virtual_start" ? reply(true) : undefined);
  await env.restart().resume();
  const confirmations = env.calls.filter(call => call.method === "qoj_confirm_virtual_start");
  assert.equal(confirmations.at(-1).args.httpTabId, 77);
  assert.equal(env.calls.filter(call => call.method === "qoj_bind_virtual").length, 1);
  assert.equal(env.opened.length, 1); assert.equal(env.data[intentKey], undefined);
});

test("duplicate submit, POST completion and dashboard events share work and recheck after the in-flight unknown response", async () => {
  const entered = deferred(), release = deferred(); let confirmations = 0;
  const env = environment({onNative:async method => {
    if (method !== "qoj_confirm_virtual_start") return;
    confirmations++;
    if (confirmations === 1) {entered.resolve(); await release.promise; return reply(false);}
    return reply(true);
  }});
  const first = env.flow.startIntent({cid}, sender()); await entered.promise;
  env.tabMap.set(7, {id:7, url:dashboard});
  const duplicates = [env.flow.startIntent({cid}, sender()), env.flow.completed(completed()), env.flow.check({cid}, sender(7, dashboard))];
  await turn(); release.resolve();
  const results = await Promise.all([first, ...duplicates]);
  assert.ok(results.every(result => result.state === "started"));
  assert.equal(confirmations, 2); assert.equal(env.calls.filter(call => call.method === "qoj_bind_virtual").length, 1);
  assert.equal(env.opened.length, 1); assert.equal(env.data[intentKey], undefined);
});

test("a later native event is not lost when an earlier confirmation read fails", async () => {
  const entered = deferred(), release = deferred(); let confirmations = 0;
  const env = environment({initial:{[intentKey]:pending()}, onNative:async method => {
    if (method !== "qoj_confirm_virtual_start") return;
    confirmations++;
    if (confirmations === 1) {entered.resolve(); await release.promise; throw Error("temporary read failure before POST completed");}
    return reply(true);
  }});
  const first = env.flow.check({cid}, sender()); await entered.promise;
  const later = env.flow.completed(completed());
  const outcomes = Promise.allSettled([first, later]); await turn(); release.resolve(); await outcomes;
  assert.equal(confirmations, 2, "POST completion must receive a fresh read after the older read failed");
  assert.equal(env.opened.length, 1); assert.equal(env.data[intentKey], undefined);
});

test("a queued recovery event uses the newly opened tab when the previous QOJ tab was closed", async () => {
  const entered = deferred(), release = deferred(); let confirmations = 0;
  const env = environment({initial:{[intentKey]:pending()}, onNative:async method => {
    if (method !== "qoj_confirm_virtual_start") return;
    confirmations++;
    if (confirmations === 1) {entered.resolve(); await release.promise; return reply(false);}
    return reply(true);
  }});
  const first = env.flow.check({cid}, sender()); await entered.promise;
  env.tabMap.delete(7); env.tabMap.set(77, {id:77, url:dashboard});
  const later = env.flow.check({cid}, sender(77, dashboard));
  const outcomes = Promise.allSettled([first, later]); await turn(); release.resolve(); await outcomes;
  assert.equal(confirmations, 2); assert.equal(env.opened.length, 1);
  assert.equal(env.calls.filter(call => call.method === "qoj_confirm_virtual_start").at(-1).args.httpTabId, 77);
});

test("events arriving during both confirmation reads still receive one final fresh read", async () => {
  const entered = [deferred(), deferred()], release = [deferred(), deferred()]; let confirmations = 0;
  const env = environment({initial:{[intentKey]:pending()}, onNative:async method => {
    if (method !== "qoj_confirm_virtual_start") return;
    const index = confirmations++;
    if (index < 2) {entered[index].resolve(); await release[index].promise; return reply(false);}
    return reply(true);
  }});
  const first = env.flow.check({cid}, sender()); await entered[0].promise;
  const second = env.flow.completed(completed()); await turn(); release[0].resolve(); await entered[1].promise;
  const third = env.flow.check({cid}, sender(7, dashboard));
  await turn(); release[1].resolve(); await Promise.allSettled([first, second, third]);
  assert.equal(confirmations, 3, "the dashboard event must not be silently discarded at the retry-pass limit");
  assert.equal(env.opened.length, 1); assert.equal(env.data[intentKey], undefined);
});

test("a same-contest account switch rejected by native retains the original pending binding", async () => {
  const env = environment({initial:{[intentKey]:pending()}, onNative:async method => {
    if (method === "qoj_confirm_virtual_start") throw Object.assign(Error("QOJ account changed"), {code:"QOJ_VIRTUAL_ACCOUNT_MISMATCH"});
  }});
  await assert.rejects(env.flow.check({cid}, sender()), /account changed/);
  assert.equal(env.opened.length, 0); assert.equal(env.data[intentKey].sessionId, sid);
  assert.equal(env.data[intentKey].account, account); assert.match(env.data[intentKey].error, /account changed/);
  assert.equal(env.calls.some(call => call.method === "qoj_bind_virtual"), false);
});

test("visiting an old contest without a native Start intent never calls the helper", async () => {
  const env = environment({initial:{sessions:[bound({started:true})]}});
  assert.equal((await env.flow.check({cid}, sender(7, dashboard))).state, "idle");
  await env.flow.completed(completed()); await env.flow.resume();
  assert.equal(env.calls.length, 0); assert.equal(env.opened.length, 0);
});

test("messages from another origin, contest, frame or extension are rejected before native or storage mutations", async () => {
  const badSenders = [{...sender(), url:"https://example.com/contest/2644/virtual/register"},
    {...sender(), url:"https://qoj.ac.evil.example/contest/2644/virtual/register"},
    {...sender(), url:"https://qoj.ac/contest/999/virtual/register"},
    {...sender(), url:"https://qoj.ac/contest/2644/problem/14872"},
    {...sender(), frameId:1}, {...sender(), id:"another-extension"}, {...sender(), tab:null}];
  for (const action of ["registration", "prepare", "startIntent", "check"]) for (const bad of badSenders) {
    const env = environment();
    await assert.rejects(env.flow[action]({cid, registrationPage}, bad), error => error.code === "QOJ_VIRTUAL_SENDER_MISMATCH");
    assert.equal(env.calls.length, 0); assert.deepEqual(env.data, {});
  }
  for (const action of ["registration", "prepare", "startIntent"]) {
    const env = environment(); await assert.rejects(env.flow[action]({cid}, sender(7, dashboard)));
    assert.equal(env.calls.length, 0);
  }
});

test("navigating away before an intent is processed cannot bind or confirm the wrong page", async () => {
  for (const url of ["https://example.com/", "https://qoj.ac/contest/999", "https://qoj.ac/contest/2644/problem/14872"]) {
    const env = environment({openedTabs:[{id:7, url}]});
    assert.equal((await env.flow.startIntent({cid}, sender())).state, "page_changed");
    assert.equal(env.calls.length, 0); assert.equal(env.opened.length, 0);
  }
});

test("navigating away while the binding request is pending does not confirm or open afterward", async () => {
  const entered = deferred(), release = deferred();
  const env = environment({onNative:async method => {
    if (method === "qoj_bind_virtual") {entered.resolve(); await release.promise; return {session:bound()};}
    if (method === "qoj_confirm_virtual_start") return reply(true);
  }});
  const action = env.flow.startIntent({cid}, sender()); await entered.promise;
  env.tabMap.set(7, {id:7, url:"https://qoj.ac/contest/999"}); release.resolve();
  await Promise.allSettled([action]);
  assert.equal(env.calls.some(call => call.method === "qoj_confirm_virtual_start"), false);
  assert.equal(env.opened.length, 0); assert.ok(env.data[intentKey]);
});
