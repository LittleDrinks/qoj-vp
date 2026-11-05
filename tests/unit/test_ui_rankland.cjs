"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../src/firefox/ui.js"), "utf8");
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
  const state = {session: {sessionId, contestId: "1051", account: "LittleDrinks", ranklandUrl, durationMs: 18000000, startAt:0, elapsedMs:18000000},
    contest: {account: "LittleDrinks", problems: [{id: "5115", label: "C", name: "Clone Ranran"}]},
    submissions: [{id: "3331061", problemId: "5115", state: "confirmed", elapsedMs: 4674955, pending: false, verdict: "CORRECT", inSession:true, timeSource:"provider-absolute"}],
    generation: 1, ranklandSnapshot: null, ranklandSnapshotState: "unavailable", ranklandSnapshotMessage: "",
    ranklandRequestSequence: 0, ranklandRequest: null};
  let handler = async () => ({state: "live", url: ranklandUrl, snapshot: snapshot()});
  const context = {URL, Date, state, location:{hash:"#home"},VpBoardView:{render(){}}, document: {createElement: tag => new Element(tag)}, $: () => target,
    current: (expected, generation) => state.session?.sessionId === expected && state.generation === generation,
    formatDate: value => new Date(value).toISOString(),
    call: async (method, args) => { calls.push({method, args}); return handler(method, args); }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("src/firefox/board/generated/engine.js","utf8"),context);
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


test("desktop and mobile use local score and penalty without an external page",()=>{
 const e=environment();e.context.renderSummary();
 assert.deepEqual(byClass(e.target,"scorett").map(x=>x.textContent),["77","77"]);
 assert.deepEqual(byClass(e.target,"rank").map(x=>x.textContent),["—","—"]);
 assert.equal(byClass(e.target,"score_correct").length,1);
});
test("a matching board snapshot supplies rank and score from one calculation",()=>{
 const e=environment(),input=e.context.boardInput(),engine=e.context.VpBoardEngine;
 e.state.board={...engine.project(input),inputKey:engine.inputKey(input),scope:"historical"};e.state.board.own.rank=465;
 e.context.renderSummary();assert.deepEqual(byClass(e.target,"rank").map(x=>x.textContent),["465","465"]);
 assert.deepEqual(byClass(e.target,"scorenc").map(x=>x.textContent),["1","1"]);
});
test("changed verdicts immediately discard stale ranks and recompute self score",()=>{
 const e=environment(),input=e.context.boardInput(),engine=e.context.VpBoardEngine;
 e.state.board={...engine.project(input),inputKey:engine.inputKey(input),scope:"historical"};e.state.board.own.rank=465;
 e.state.submissions[0].verdict="WRONG-ANSWER";e.context.renderSummary();
 assert.deepEqual(byClass(e.target,"rank").map(x=>x.textContent),["—","—"]);
 assert.deepEqual(byClass(e.target,"scorenc").map(x=>x.textContent),["0","0"]);
 assert.equal(byClass(e.target,"score_correct").length,0);
});
test("board reads coalesce, and replies for another session cannot change display",async()=>{
 const e=environment();let release;e.setHandler(()=>new Promise(resolve=>release=resolve));
 const a=e.context.refreshBoard(),b=e.context.refreshBoard();assert.equal(e.calls.length,1);
 assert.equal(e.calls[0].method,"board.snapshot");e.state.generation++;
 release({sessionId,inputKey:"wrong"});await Promise.all([a,b]);assert.equal(e.state.board,undefined);
});
test("early finish excludes later AC without changing the immutable submission time",()=>{
 const e=environment();e.state.session.finishedAt=60000;e.context.renderSummary();
 assert.equal(byClass(e.target,"score_correct").length,0);assert.equal(e.state.submissions[0].elapsedMs,4674955);
});
test("the running RankLand link follows the confirmed start instead of opening paused at zero",()=>{
 const e=environment(),started=1793493600045;
 e.state.session.startAt=started;e.state.session.ranklandUrl=ranklandUrl+"&anchor=2026-11-01T00%3A00%3A00Z&from=90&play=1&speed=60";
 e.state.session.state='running';e.state.session.elapsedMs=1200000;
 const before=JSON.stringify(e.state.session),url=new URL(e.context.ranklandBoardUrl(null,started+1200000));
 assert.equal(Date.parse(url.searchParams.get("at")),started);assert.equal(url.searchParams.get("play"),"1");
 assert.equal(url.searchParams.get("from"),"0");assert.equal(url.searchParams.get("speed"),"1");
 assert.equal(url.searchParams.get("anchor"),null);assert.equal(url.searchParams.get("rule"),"ICPC");
 assert.equal(JSON.stringify(e.state.session),before);
});
test('finished RankLand links and shares preserve the displayed replay instant without restarting the contest',()=>{
 const e=environment();e.state.session.state='finished';e.state.session.finishedAt=1200000;
 const before=JSON.stringify(e.state.session);
 const url=new URL(e.context.ranklandBoardUrl({elapsedMs:7500000,speed:5,playing:true},2000000));
 assert.equal(url.searchParams.get('from'),'125');assert.equal(url.searchParams.get('play'),'0');
 assert.equal(url.searchParams.get('speed'),'1');assert.equal(Date.parse(url.searchParams.get('at')),0);
 assert.equal(JSON.stringify(e.state.session),before);
});
test('prepared external links pause at zero and have no invented start',()=>{
 const e=environment();Object.assign(e.state.session,{startAt:null,state:'prepared',elapsedMs:0});
 const url=new URL(e.context.ranklandBoardUrl());
 assert.equal(url.searchParams.get('at'),null);assert.equal(url.searchParams.get('from'),'0');assert.equal(url.searchParams.get('play'),'0');
});
test("display projection reads the requested time without replacing the real Home snapshot",async()=>{
 const e=environment(),real={own:{score:99}};e.state.connected=true;e.state.board=real;
 e.setHandler(async(method,args)=>{
  assert.equal(method,"board.snapshot");const input=e.context.boardInput(),result=e.context.VpBoardEngine.project(input,null,args.elapsedMs);
  return {...result,inputKey:e.context.VpBoardEngine.inputKey(input)};
 });
 const replay=await e.context.projectBoard(0);assert.equal(replay.elapsedMs,0);assert.equal(replay.own.score,0);
 assert.equal(e.state.board,real);assert.equal(e.state.submissions[0].elapsedMs,4674955);
});
