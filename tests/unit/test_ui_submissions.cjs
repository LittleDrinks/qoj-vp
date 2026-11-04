/* Replay provider/operation DTOs through the actual production renderer. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../src/firefox/ui.js"), "utf8");
class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.style = {};
    this.dataset = {}; this.attributes = {}; this.listeners = {}; this.textContent = "";
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
}
const text = element => typeof element === "string" ? element : element.textContent + element.children.map(text).join("");
const start = Date.parse("2026-10-31T17:03:02.045Z");
const current = {id:"3331061", operationId:"current-confirmed", account:"LittleDrinks", problemId:"5115", problemLabel:"C",
  language:"C++20", submittedAt:1793470857000, elapsedMs:4674955, timeSource:"provider-absolute", inSession:true,
  verdict:"CORRECT", rawVerdict:"AC ✓", pending:false, state:"confirmed", url:"https://qoj.ac/submission/3331061"};
const old = {id:"1511772", account:"LittleDrinks", problemId:"5114", problemLabel:"B", language:"C++23",
  submittedAt:Date.parse("2025-10-14T21:37:53+08:00"), timeSource:"provider-absolute", inSession:false,
  verdict:"UNKNOWN", rawVerdict:"TL", pending:false, state:"confirmed", url:"https://qoj.ac/submission/1511772"};
old.elapsedMs = old.submittedAt - start;
function render(records, session={startAt:start,state:"running",durationMs:18000000}) {
  const ids = Object.fromEntries(["submissions-body", "submissions-table", "submissions-empty"].map(id => [id,new Element("div")]));
  ids["submissions-empty"].textContent = "No submissions";
  const reconciled = [], state = {session, submissions:records};
  const context = {URL, state, $:id=>ids[id], document:{createElement:tag=>new Element(tag)},
    renderSummary(){}, openReconcile:submission=>reconciled.push(submission)};
  vm.createContext(context);
  for (const [begin,end] of [["  function node(","  function showMessage("],
    ["  function epoch(","  function sessionState("], ["  function safeQojUrl(","  function problemUrl("],
    ["  function badge(","  function contestName("], ["  function renderSubmissions(","  function historyCoverageMessage("]]) {
    assert.ok(source.includes(begin) && source.includes(end));
    vm.runInContext(source.slice(source.indexOf(begin),source.indexOf(end)),context);
  }
  context.renderSubmissions();
  return {rows:ids["submissions-body"].children,table:ids["submissions-table"],empty:ids["submissions-empty"],reconciled};
}

test("current AC remains visible; backfilled old native/UNKNOWN history stays in data only",()=>{
  const records=[old,{...old,id:"1511385",submittedAt:null,elapsedMs:null,timeSource:"unverified-display"},current];
  const before=JSON.stringify(records), view=render(records);
  assert.equal(view.rows.length,1);
  assert.equal(view.rows[0].dataset.submissionId,"3331061");
  assert.match(text(view.rows[0]),/CORRECT/);
  assert.equal(view.rows[0].children[0].children[0].textContent,"1:17:54");
  assert.equal(view.rows[0].children[0].children[0].href,"https://qoj.ac/submission/3331061");
  assert.equal(view.empty.hidden,true); assert.equal(view.table.hidden,false);
  assert.equal(JSON.stringify(records),before,"rendering must not discard ledger/history facts");
});

test("unknown local operation remains visible and its actual reconcile button works",()=>{
  const operation={operationId:"unknown-local",problemId:"5115",problemLabel:"C",language:"C++20",filename:"C.cpp",
    state:"unknown",verdict:"UNKNOWN",pending:false,submittedAt:start-1000,elapsedMs:-1000,inSession:false};
  const view=render([old,operation]);
  assert.equal(view.rows.length,1); assert.equal(view.rows[0].dataset.operationId,operation.operationId);
  assert.match(text(view.rows[0]),/结果未确认/); assert.equal(view.rows[0].children[0].children[0].textContent,"—");
  const button=view.rows[0].children[4].children[0];
  assert.equal(button.tagName,"BUTTON"); button.listeners.click();
  assert.equal(view.reconciled.length,1); assert.equal(view.reconciled[0],operation);
});

test("out-of-window own confirmed operation keeps date/details without a negative elapsed",()=>{
  const operation={...old,operationId:"out-of-window-confirmed"},view=render([operation]);
  assert.equal(view.rows.length,1);
  const time=view.rows[0].children[0];
  assert.equal(time.children[0].textContent,"—");
  assert.match(time.title,/2025/); assert.match(time.title,/时间窗外/);
  assert.equal(time.children[0].href,"https://qoj.ac/submission/1511772");
  assert.doesNotMatch(text(view.rows[0]),/[−-]\d+:\d{2}:\d{2}/);
});

test("sending and rejected local operations survive missing/out-of-window time",()=>{
  const records=[{operationId:"sending-local",state:"sending",verdict:"UNKNOWN",pending:true,submittedAt:null,elapsedMs:null,inSession:false},
    {operationId:"rejected-local",state:"rejected",verdict:"UNKNOWN",pending:false,submittedAt:start+18000001,elapsedMs:18000001,inSession:false}];
  const view=render(records);
  assert.equal(view.rows.length,2);
  assert.match(text(view.rows.find(row=>row.dataset.operationId==="sending-local")),/结果未确认/);
  assert.match(text(view.rows.find(row=>row.dataset.operationId==="rejected-local")),/提交被拒绝/);
  assert.ok(view.rows.every(row=>row.children[0].children[0].textContent==="—"));
});

test("prepared session with only prior history retains the original No submissions state",()=>{
  const view=render([{...old,elapsedMs:null},{...old,id:"1",inSession:"true"}],{startAt:null,state:"prepared",durationMs:18000000});
  assert.equal(view.rows.length,0); assert.equal(view.table.hidden,true); assert.equal(view.empty.hidden,false);
  assert.equal(text(view.empty),"No submissions");
});
