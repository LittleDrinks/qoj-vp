"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../src/firefox/ui.js"), "utf8");
const sessionId = "ffe1f51d-bcc8-44ee-8bff-c97de7fd8bd8";
const ranklandUrl = `https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC&run=${sessionId}&from=0&at=2026-10-31T17%3A03%3A02.045Z`;

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
const byClass = (target, name) => walk(target).filter(element => element.className.split(/\s+/).includes(name));

function environment() {
  const target = new Element("div"), calls = [];
  const state = {session: {sessionId, contestId: "1051", account: "LittleDrinks", ranklandUrl, durationMs: 18000000, startAt:0, elapsedMs:18000000},
    contest: {account: "LittleDrinks", problems: [{id: "5115", label: "C", name: "Clone Ranran"}]},
    submissions: [{id: "3331061", problemId: "5115", state: "confirmed", elapsedMs: 4674955, pending: false, verdict: "CORRECT", inSession:true, timeSource:"provider-absolute"}],
    generation: 1};
  let handler = async () => {throw new Error('Unexpected background call');};
  const context = {URL, Date, state, location:{hash:"#home"},VpBoardView:{render(){}}, document: {createElement: tag => new Element(tag)}, $: () => target,
    current: (expected, generation) => state.session?.sessionId === expected && state.generation === generation,
    formatDate: value => new Date(value).toISOString(), renderScoreboardSource(){},
    call: async (method, args) => { calls.push({method, args}); return handler(method, args); }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("src/firefox/scoreboard-sources.js","utf8"),context);
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
test("Home uses the same historical rank as Scoreboard while retaining the local score",()=>{
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
test('Home desktop and mobile show a question mark during freeze and the actual rank after unfreeze',()=>{
 const e=environment(),input=e.context.boardInput(),engine=e.context.VpBoardEngine;
 const archive={version:'0.3.14',type:'general',contest:{title:'Frozen contest',startAt:new Date(0).toISOString(),duration:[5,'h'],frozenDuration:[1,'h']},
  problems:[{alias:'C'}],rows:[],series:[{title:'Rank',rule:{preset:'Normal'}}],sorter:{algorithm:'ICPC',config:{penalty:[20,'min']}}};
 e.state.session.state='finished';
 for(const [minute,rank] of [[239,'1'],[240,'?'],[299,'?'],[300,'1'],[250,'?']]) {
  e.state.board={...engine.project(input,archive,minute*60000),inputKey:engine.inputKey(input)};
  e.context.renderSummary();assert.deepEqual(byClass(e.target,'rank').map(x=>x.textContent),[rank,rank]);
  assert.deepEqual(byClass(e.target,'scorenc').map(x=>x.textContent),['1','1']);
  assert.deepEqual(byClass(e.target,'scorett').map(x=>x.textContent),['77','77']);
 }
});
test("board reads coalesce, and replies for another session cannot change display",async()=>{
 const e=environment();let release;e.setHandler(()=>new Promise(resolve=>release=resolve));
 const a=e.context.refreshBoard(),b=e.context.refreshBoard();assert.equal(e.calls.length,1);
 assert.equal(e.calls[0].method,"board.snapshot");e.state.generation++;
 release({sessionId,inputKey:"wrong"});await Promise.all([a,b]);assert.equal(e.state.board,undefined);
});
test("Home polling preserves the historical load requested by manual source settings",async()=>{
 const e=environment();let release;e.setHandler(()=>new Promise(resolve=>release=resolve));
 const manual=e.context.refreshBoard(true,true),poll=e.context.refreshBoard();
 assert.equal(e.calls.length,1);assert.equal(e.calls[0].args.includeHistory,true);
 const input=e.context.boardInput(),engine=e.context.VpBoardEngine;
 const result={...engine.project(input),inputKey:engine.inputKey(input),scope:"historical"};
 release(result);await Promise.all([manual,poll]);
 assert.equal(e.state.boardSource.ready,true);assert.equal(e.state.boardSource.url,ranklandUrl);
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
test('external links open the final standings at the exact end, including saved full-duration offsets',()=>{
 const e=environment();e.state.session.state='running';
 e.state.session.ranklandUrl='https://vp.xcpc.link/?contest=ccpc2025jinan&from=300&play=0&rule=CCPC26';
 const before=JSON.stringify(e.state.session);
 assert.equal(new URL(e.context.ranklandBoardUrl(null,17999999)).searchParams.get('play'),'1');
 assert.equal(e.context.ranklandBoardUrl(null,18000000),'https://rl.algoux.cn/ranklist/ccpc2025jinan');
 assert.equal(e.context.ranklandBoardUrl({elapsedMs:18000000},18000000),'https://rl.algoux.cn/ranklist/ccpc2025jinan');
 assert.equal(JSON.stringify(e.state.session),before);
});
test('early finish opens final standings by default and keeps an explicit replay below the duration',()=>{
 const e=environment();Object.assign(e.state.session,{state:'finished',finishedAt:1200000});
 assert.equal(new URL(e.context.ranklandBoardUrl(null,1200000)).pathname,'/ranklist/icpc2022xi_an');
 const replay=new URL(e.context.ranklandBoardUrl({elapsedMs:17999999},1200000));
 assert.equal(replay.origin,'https://vp.xcpc.link');
 assert.ok(Number(replay.searchParams.get('from'))<300);
 assert.equal(replay.searchParams.get('play'),'0');
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

test("Home requests historical opponents for a configured source",async()=>{
 const e=environment();e.setHandler(async()=>null);
 await e.context.refreshBoard();assert.equal(e.calls[0].args.includeHistory,true);
 e.state.session.ranklandUrl=null;await e.context.refreshBoard();assert.equal(e.calls.at(-1).args.includeHistory,false);
});

test("a changed judgement keeps the full table while its replacement snapshot is loading",async()=>{
 const e=environment(),engine=e.context.VpBoardEngine; e.context.location.hash="#scoreboard";
 let displayed;
 e.context.VpBoardView.render=(_target,snapshot)=>{displayed=snapshot;};
 e.setHandler(async()=>{const input=e.context.boardInput();return {...engine.project(input),inputKey:engine.inputKey(input),scope:"historical"};});
 await e.context.refreshBoard();const previous=displayed;
 e.state.submissions[0].verdict="WRONG-ANSWER";e.context.renderBoard();
 assert.equal(displayed,previous,"Do not collapse the table to a single row between history and board reads");
 await e.context.refreshBoard();assert.notEqual(displayed,previous);assert.equal(displayed.own.score,0);
 e.state.session.ranklandUrl="https://vp.xcpc.link/?contest=another";e.context.renderBoard();
 assert.equal(displayed.scope,"self","A new source must not display the previous opponents");
});
