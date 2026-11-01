"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../extension/ui.js"), "utf8");
const sessionId = "ffe1f51d-bcc8-44ee-8bff-c97de7fd8bd8";
const ranklandUrl = `https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC&run=${sessionId}&from=0&at=2026-10-31T17%3A03%3A02.045Z`;
const identity = raw => {
  const url = new URL(raw), query = url.searchParams;
  return JSON.stringify([url.origin, query.get("contest"), query.get("run"), query.get("rule") || "auto",
    Number(query.get("count") ?? 50), Number(query.get("ratio") ?? 20), query.get("at") || "null", Number(query.get("from") || 0)]);
};
const snapshot = overrides => ({version: 1, sessionId, url: ranklandUrl, identity: identity(ranklandUrl),
  targetKey: "RanklandVP2:exact-current-run", ownName: "LittleDrinks", rank: 465,
  ranks: [{label: "#", value: 465}, {label: "R#", value: 510}], score: 1, penaltyMinutes: 77,
  elapsedMs: 18000000, running: false, observedAt: 1793493600000, ...overrides});

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.dataset = {};
    this.attributes = {}; this.listeners = {}; this.className = ""; this.textContent = "";
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  get firstChild() { return this.children[0]; }
}
const walk = element => typeof element === "string" ? [] : [element, ...element.children.flatMap(walk)];
const text = element => typeof element === "string" ? element : element.textContent + element.children.map(text).join("");
const byClass = (target, name) => walk(target).filter(element => element.className.split(/\s+/).includes(name));

function environment() {
  const target = new Element("div"), calls = [];
  const state = {session: {sessionId, contestId: "1051", account: "LittleDrinks", ranklandUrl, durationMs: 18000000},
    contest: {account: "LittleDrinks", problems: [{id: "5115", label: "C", name: "Clone Ranran"}]},
    submissions: [{id: "3331061", problemId: "5115", state: "confirmed", elapsedMs: 4674955, pending: false, verdict: "CORRECT"}],
    generation: 1, ranklandSnapshot: null, ranklandSnapshotState: "unavailable", ranklandSnapshotMessage: "",
    ranklandRequestSequence: 0, ranklandRequest: null};
  let handler = async () => ({state: "live", url: ranklandUrl, snapshot: snapshot()});
  const context = {URL, Date, state, document: {createElement: tag => new Element(tag)}, $: () => target,
    current: (expected, generation) => state.session?.sessionId === expected && state.generation === generation,
    formatDate: value => new Date(value).toISOString(),
    call: async (method, args) => { calls.push({method, args}); return handler(method, args); }};
  vm.createContext(context);
  for (const [begin, end] of [["  function node(", "  function showMessage("],
    ["  function epoch(", "  function formatDate("],
    ["  function safeQojUrl(", "  function contestName("],
    ["  function ranklandViewIdentity(", "  function renderSummary("],
    ["  function renderSummary(", "  function renderSubmissions("]]) {
    const offset = source.indexOf(begin);
    if (offset >= 0) vm.runInContext(source.slice(offset, source.indexOf(end, offset)), context);
  }
  return {context, state, target, calls, setHandler(value) { handler = value; }};
}

test("desktop and mobile show original RankLand rank and penalty rather than dashes", () => {
  const view = environment(); view.state.ranklandSnapshot = snapshot(); view.state.ranklandSnapshotState = "live";
  view.context.renderSummary();
  assert.deepEqual(byClass(view.target, "rank").map(element => element.textContent), ["465", "465"]);
  assert.deepEqual(byClass(view.target, "scorett").map(element => element.textContent), ["77", "77"]);
  assert.ok(byClass(view.target, "rank").every(element => element.title.includes("RankLand")));
  assert.equal(walk(view.target).filter(element => element.dataset.ranklandStatus).length, 0);
});

test("zero values stay zero and the score follows the same original-site snapshot", () => {
  const view = environment(); view.state.ranklandSnapshot = snapshot({rank: null, score: 0, penaltyMinutes: 0});
  view.state.ranklandSnapshotState = "live"; view.context.renderSummary();
  assert.deepEqual(byClass(view.target, "rank").map(element => element.textContent), ["—", "—"]);
  assert.deepEqual(byClass(view.target, "scorett").map(element => element.textContent), ["0", "0"]);
  assert.deepEqual(byClass(view.target, "scorenc").map(element => element.textContent), ["0", "0"]);
  assert.equal(byClass(view.target, "score_correct").length, 1, "local confirmed problem progress remains visible");
});

test("cached ranks retain their timestamp and are visibly marked as the previous sync", () => {
  const view = environment(); view.state.ranklandSnapshot = snapshot(); view.state.ranklandSnapshotState = "cached";
  view.context.renderSummary();
  assert.ok(byClass(view.target, "rank").every(element => /上次同步/.test(element.title)));
  const notes = walk(view.target).filter(element => element.dataset.ranklandStatus);
  assert.equal(notes.length, 1); assert.match(text(notes[0]), /上次同步/);
  assert.match(text(notes[0]), /2026-11-01/);
});

test("different session, changed URL or malformed metrics never render a borrowed rank", () => {
  for (const invalid of [snapshot({sessionId: "other"}), snapshot({identity: "other"}),
    snapshot({url: ranklandUrl.replace("icpc2022xi_an", "other")}), snapshot({rank: "465"}), snapshot({penaltyMinutes: -1})]) {
    const view = environment(); view.state.ranklandSnapshot = invalid; view.state.ranklandSnapshotState = "live";
    view.context.renderSummary();
    assert.deepEqual(byClass(view.target, "rank").map(element => element.textContent), ["—", "—"]);
    assert.deepEqual(byClass(view.target, "scorett").map(element => element.textContent), ["—", "—"]);
  }
});

test("rank refresh uses only the new read-only snapshot API", async () => {
  const view = environment();
  assert.equal(typeof view.context.refreshRanklandSnapshot, "function");
  await view.context.refreshRanklandSnapshot();
  assert.deepEqual(view.calls.map(call => call.method), ["rankland.snapshot"]);
  assert.equal(view.state.ranklandSnapshot.rank, 465); assert.equal(view.state.ranklandSnapshotState, "live");
});

test("late replies cannot overwrite a newly selected session", async () => {
  const view = environment(); let complete;
  view.setHandler(() => new Promise(resolve => { complete = resolve; }));
  assert.equal(typeof view.context.refreshRanklandSnapshot, "function");
  const pending = view.context.refreshRanklandSnapshot();
  view.state.generation++; view.state.session = {...view.state.session, sessionId: "new-session"};
  complete({state: "live", url: ranklandUrl, snapshot: snapshot()}); await pending;
  assert.equal(view.state.ranklandSnapshot, null);
});

test("URL edits and a newer forced request discard older snapshot responses", async () => {
  const view = environment(), completions = [];
  view.setHandler(() => new Promise(resolve => completions.push(resolve)));
  assert.equal(typeof view.context.refreshRanklandSnapshot, "function");
  const first = view.context.refreshRanklandSnapshot();
  const second = view.context.refreshRanklandSnapshot(true);
  completions[1]({state: "live", url: ranklandUrl, snapshot: snapshot({rank: 400})}); await second;
  completions[0]({state: "live", url: ranklandUrl, snapshot: snapshot({rank: 465})}); await first;
  assert.equal(view.state.ranklandSnapshot.rank, 400);
  const edited = view.context.refreshRanklandSnapshot(true);
  view.state.session.ranklandUrl = ranklandUrl.replace("icpc2022xi_an", "edited");
  completions[2]({state: "live", url: ranklandUrl, snapshot: snapshot({rank: 300})}); await edited;
  view.context.renderSummary();
  assert.deepEqual(byClass(view.target, "rank").map(element => element.textContent), ["—", "—"]);
});

test("the backend frozen replay URL replaces the initial bare link before applying its snapshot", async () => {
  const view = environment();
  view.state.session.ranklandUrl = "https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC";
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.state.session.ranklandUrl, ranklandUrl);
  assert.equal(view.state.ranklandSnapshot.rank, 465);
  assert.deepEqual(byClass(view.target, "scorett").map(element => element.textContent), ["77", "77"]);
});

test("an in-flight poll is shared and API failure keeps only a clearly stale same-run snapshot", async () => {
  const view = environment(); let complete;
  view.setHandler(() => new Promise(resolve => { complete = resolve; }));
  const first = view.context.refreshRanklandSnapshot(), second = view.context.refreshRanklandSnapshot();
  assert.equal(first, second); assert.equal(view.calls.length, 1);
  complete({state: "live", url: ranklandUrl, snapshot: snapshot()}); await first;
  view.setHandler(async () => { throw new Error("synthetic unavailable"); });
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.state.ranklandSnapshot.rank, 465); assert.equal(view.state.ranklandSnapshotState, "cached");
  assert.match(byClass(view.target, "rank")[0].title, /上次同步/);
});

test("closed-board cached results keep original observedAt and a missing result invents no metrics", async () => {
  const view = environment(), observed = snapshot();
  view.setHandler(async () => ({state: "cached", url: ranklandUrl, snapshot: observed}));
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.state.ranklandSnapshot.observedAt, observed.observedAt);
  assert.equal(view.state.ranklandSnapshotState, "cached");
  view.setHandler(async () => ({state: "unavailable", url: ranklandUrl, snapshot: null}));
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.state.ranklandSnapshot, null);
  assert.deepEqual(byClass(view.target, "rank").map(element => element.textContent), ["—", "—"]);
});

test("unconfigured contests do not poll and clearing a session invalidates pending results", async () => {
  const view = environment(); view.state.session.ranklandUrl = null;
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.calls.length, 0); assert.equal(view.state.ranklandSnapshotState, "not_configured");
  view.state.session.ranklandUrl = ranklandUrl;
  let complete; view.setHandler(() => new Promise(resolve => { complete = resolve; }));
  const pending = view.context.refreshRanklandSnapshot();
  view.context.resetRanklandSnapshot();
  complete({state: "live", url: ranklandUrl, snapshot: snapshot()}); await pending;
  assert.equal(view.state.ranklandSnapshot, null);
});

test("adopting another replay anchor clears the old visible row immediately", () => {
  const view = environment(); view.state.ranklandSnapshot = snapshot(); view.state.ranklandSnapshotState = "live";
  view.context.renderSummary();
  view.context.adoptRanklandUrl(ranklandUrl.replace("from=0", "from=1"));
  assert.equal(view.state.ranklandSnapshot, null);
  assert.deepEqual(byClass(view.target, "rank").map(element => element.textContent), ["—", "—"]);
});

test("an old background coalesced reply cannot roll back freshly edited contest settings", async () => {
  const view = environment();
  const edited = ranklandUrl.replace("icpc2022xi_an", "new-contest");
  view.state.session.ranklandUrl = edited;
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.state.session.ranklandUrl, edited);
  assert.equal(view.state.ranklandSnapshot, null);
});

test("a frozen replay never adopts another offset from an old background task", async () => {
  const view = environment();
  view.state.session.ranklandPrepared = true;
  const edited = ranklandUrl.replace("from=0", "from=12");
  view.state.session.ranklandUrl = edited;
  await view.context.refreshRanklandSnapshot();
  assert.equal(view.state.session.ranklandUrl, edited);
  assert.equal(view.state.ranklandSnapshot, null);
});

test("the actual timer wiring polls rankings every10s only while the view is visible", () => {
  const intervals = new Map(), listeners = new Map(), ranks = [], requests = [];
  const context = {state: {connected: true, session: {sessionId}, submitting: false, submissions: []},
    document: {hidden: true, addEventListener: (name, listener) => listeners.set(name, listener)},
    setInterval: (handler, milliseconds) => intervals.set(milliseconds, handler), renderClock() {},
    sessionState: () => "finished", refresh: async () => requests.push("qoj"),
    refreshRanklandSnapshot: force => ranks.push(Boolean(force))};
  vm.createContext(context);
  const start = source.indexOf("    setInterval(renderClock, 1000);");
  const end = source.indexOf("\n    try {", start);
  vm.runInContext(source.slice(start, end), context);
  assert.equal(typeof intervals.get(10000), "function");
  intervals.get(10000)(); assert.equal(ranks.length, 0);
  context.document.hidden = false; listeners.get("visibilitychange")();
  intervals.get(10000)(); assert.deepEqual(ranks, [true, false]);
  context.state.connected = false; intervals.get(10000)();
  assert.equal(ranks.length, 2); assert.equal(requests.length, 0);
});


test("early finish excludes later AC even while an old row still says inSession", () => {
  const view = environment();
  view.state.session.startAt = 1793490000000;
  view.state.session.finishedAt = view.state.session.startAt + 60000;
  view.state.session.state = "finished";
  view.state.submissions[0].inSession = true;
  view.context.renderSummary();
  assert.equal(byClass(view.target, "score_correct").length, 0);
  assert.ok(byClass(view.target, "scorenc").every(cell => cell.textContent === "0"));
  view.state.session.finishedAt = null;
  view.state.submissions[0].inSession = false;
  view.context.renderSummary();
  assert.equal(byClass(view.target, "score_correct").length, 0);
});
