"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../extension/rankland-content.js"), "utf8");
const sessionId = "ffe1f51d-bcc8-44ee-8bff-c97de7fd8bd8";
const url = `https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC&run=${sessionId}&from=0.0842166666667&play=1&speed=1&at=2026-10-31T17%3A03%3A02.045Z`;
const targetKey = `RanklandVP2:icpc2022xi_an:${sessionId}:ICPC:50:20:2026-10-31T17:03:02.045Z:0.0842166666667`;

const modernUrl = "https://vp.xcpc.link/?contest=icpc2022xi_an&rule=ICPC&at=2026-10-31T17%3A03%3A02.045Z&from=77&play=0&speed=1&team=LittleDrinks";
const modernKey = "RanklandVP:submissions:icpc2022xi_an:2026-10-31T17:03:02.045Z:ICPC:50:20";
function harness(options = {}) {
  const stored = {version:2, ownName:"LittleDrinks", manual:[{problemIndex:2,timeMs:4620000,result:"AC"}],
    running:true, elapsed:7200000, savedAt:1800000000000, speed:1, ...options.stored};
  const writes = [], messages = [], intervals = [];
  let listener;
  const headers = ["#", "R#", "S#", "Name", "Score", "Time", "A", "B", "C"].map((text, index) => ({
    textContent:text, classList:{contains:name=>name === "srk-series-header" && index < 3},
    matches:selector=>selector === ".srk-series-header" && index < 3
  }));
  const makeRow = (name, values) => {
    const row = {cells:[], getClientRects:()=>[{}], closest:selector=>selector === "table" ? table : null};
    row.cells = values.map(text=>({textContent:text, classList:{contains:()=>false},
      closest:selector=>selector === "tr" ? row : selector === "table" ? table : null}));
    const nameNode = {textContent:name, closest:selector=>selector === "tr" ? row : selector === "td" ? row.cells[3] : null};
    row.cells[3].querySelector = selector=>selector === ".srk-user-name-text" ? nameNode : null;
    row.cells[3].classList.contains = name=>name === "srk-user-cell";
    row.querySelectorAll = selector=>selector === ".srk-user-name-text" ? [nameNode] : [];
    return {row, nameNode};
  };
  const table = {tagName:"TABLE",className:"srk-table-row-striped",
    tHead:{rows:[{cells:headers}]}, getClientRects:()=>[{}]};
  const own = makeRow(stored.ownName, options.cells || ["470", "515", "247", stored.ownName, "1", "77", "", "", "1/77"]);
  const rows = options.duplicate ? [own,makeRow(stored.ownName,["1","2","3",stored.ownName,"12","1000"])] : [own];
  table.querySelectorAll = selector=>selector === ".srk-user-name-text" ? rows.map(entry=>entry.nameNode) : [];
  const board = {querySelectorAll:selector=>selector === ".srk-main > table" ? [table] : []};
  const document = {querySelector:selector=>selector === '[data-id="vp-ranklist-content"]' && !options.noBoard ? board : null};
  const localStorage = {getItem:key=>key === (options.modern ? modernKey : targetKey) && !options.noStorage ? JSON.stringify(options.modern ? stored.manual : stored) : null,
    setItem(...args){ writes.push(["site", ...args]); }};
  const browser = {runtime:{id:"qoj-test",onMessage:{addListener:callback=>{listener=callback;}},
    sendMessage:async message=>{messages.push(message); return {allowed:true};}},
    storage:{local:{set:async value=>writes.push(["extension",value]),get:async()=>({})}}};
  const context = {URL, document, localStorage, browser, location:{href:options.location || (options.modern ? modernUrl : url)},
    setInterval:callback=>intervals.push(callback), setTimeout, clearTimeout, Date};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('extension/rankland-protocol.js','utf8'),context); vm.runInContext(source,context);
  return {stored,writes,messages,intervals,headers,table,own,context,
    async snapshot(expectedUrl = options.modern ? modernUrl : url, requestSessionId = sessionId) {
      return listener({type:"vp.rankland.snapshot",sessionId:requestSessionId,expectedUrl}, {id:"qoj-test"});
    }, send:listener};
}

test("actual content bridge reports original primary rank, score and penalty for the exact saved run", async()=>{
  const view = harness(), before = JSON.stringify(view.stored);
  const result = await view.snapshot();
  assert.equal(result?.ready,true,"RankLand own-row observation must be available without sending a verdict");
  assert.equal(result.snapshot.rank,470); assert.equal(result.snapshot.score,1); assert.equal(result.snapshot.penaltyMinutes,77);
  assert.equal(result.snapshot.sessionId,sessionId); assert.equal(result.snapshot.targetKey,targetKey);
  assert.equal(result.snapshot.ownName,"LittleDrinks"); assert.equal(result.snapshot.elapsedMs,7200000);
  assert.deepEqual(Array.from(result.snapshot.ranks, item=>({label:item.label,value:item.value})),
    [{label:"#",value:470},{label:"R#",value:515},{label:"S#",value:247}]);
  assert.equal(JSON.stringify(view.stored),before); assert.equal(view.writes.length,0);
});

test("read-only score observation works after playback ends without a record form",async()=>{
  const result = await harness({stored:{running:false,elapsed:18000000}}).snapshot();
  assert.equal(result?.ready,true); assert.equal(result.snapshot.running,false); assert.equal(result.snapshot.penaltyMinutes,77);
});

test("different run, contest or replay settings cannot return another session's rank",async()=>{
  for (const query of ["run=another", "contest=another", "from=2", "rule=IOI"]) {
    const changed = new URL(url), [key,value] = query.split("="); changed.searchParams.set(key,value);
    const result = await harness().snapshot(changed.href);
    assert.equal(result?.ready,false); assert.equal(result.reason,"SESSION_MISMATCH"); assert.equal(result.snapshot,undefined);
  }
  assert.equal((await harness().snapshot(url,"another"))?.ready,false);
});

test("duplicate own names and changed score headers fail closed instead of borrowing a rank",async()=>{
  const duplicate = await harness({duplicate:true}).snapshot();
  assert.equal(duplicate?.ready,false); assert.equal(duplicate.reason,"OWN_ROW_AMBIGUOUS");
  const changed = harness(); changed.headers[4].textContent = "Dirt";
  const result = await changed.snapshot();
  assert.equal(result?.ready,false); assert.equal(result.reason,"SCORE_COLUMNS_CHANGED");
});

test("zero scores/penalties and an explicitly unranked row remain distinct from missing fields",async()=>{
  const zero = await harness({cells:["-","-","-","LittleDrinks","0","0","","",""]}).snapshot();
  assert.equal(zero?.ready,true); assert.equal(zero.snapshot.rank,null); assert.equal(zero.snapshot.score,0); assert.equal(zero.snapshot.penaltyMinutes,0);
  const missing = await harness({cells:["465","510","244","LittleDrinks","1","-","","",""]}).snapshot();
  assert.equal(missing?.ready,true); assert.equal(missing.snapshot.penaltyMinutes,null);
});

test("a missing board or archive returns an explicit unavailable result",async()=>{
  assert.equal((await harness({noBoard:true}).snapshot())?.reason,"CONTEST_LOADING");
  assert.equal((await harness({noStorage:true}).snapshot())?.reason,"TEAM_REQUIRED");
});

test("original custom team names are used, and malformed metrics never become a zero score",async()=>{
  const custom = await harness({stored:{ownName:"自定义队名"}}).snapshot();
  assert.equal(custom?.ready,true); assert.equal(custom.snapshot.ownName,"自定义队名");
  for (const metrics of [["1 point","77"],["1","77 min"],["1","-1"],["9007199254740992","77"]]) {
    const invalid = await harness({cells:["465","510","244","LittleDrinks",...metrics,"","",""]}).snapshot();
    assert.equal(invalid?.ready,false); assert.equal(invalid.reason,"SCORE_VALUES_CHANGED");
  }
  assert.equal((await harness({stored:{elapsed:-1}}).snapshot()).reason,"STORAGE_FORMAT_CHANGED");
});

test("content bridge ignores messages from other extensions",async()=>{
  const view = harness();
  assert.equal(await view.send({type:"vp.rankland.snapshot",sessionId,expectedUrl:url},{id:"foreign"}),undefined);
  assert.equal(view.writes.length,0);
});

 test("current RankLand array archives and run-free canonical URLs expose score without resetting its clock", async()=>{
  const view = harness({modern:true});
  const result = await view.snapshot();
  assert.equal(result.ready,true);
  assert.equal(result.snapshot.targetKey,modernKey);
  assert.equal(result.snapshot.ownName,"LittleDrinks");
  assert.equal(result.snapshot.elapsedMs,77*60000);
  assert.equal(result.snapshot.running,false);
  assert.equal(result.snapshot.penaltyMinutes,77);
  assert.equal(view.writes.length,0);
});
test("new replay identity accepts normalized timezone and ignores obsolete run without accepting another start",async()=>{
  const view=harness({modern:true});
  const expected=new URL(modernUrl);
  expected.searchParams.set("at","2026-11-01T01:03:02.045+08:00");
  expected.searchParams.set("run",sessionId);
  expected.searchParams.set("from","0");
  assert.equal((await view.snapshot(expected.href)).ready,true);
  expected.searchParams.set("at","2026-11-01T01:03:03.045+08:00");
  assert.equal((await view.snapshot(expected.href)).reason,"SESSION_MISMATCH");
});
