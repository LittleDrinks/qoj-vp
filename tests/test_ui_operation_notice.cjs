/* Exercise notice ownership at the actual submit -> refresh/applyHistory seam. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm"), test = require("node:test");
const source = fs.readFileSync(require("node:path").join(__dirname, "../extension/ui.js"), "utf8");
const operationId = "00000000-0000-4000-8000-000000000001";
function environment(initialState = "unknown") {
  const elements = new Map(), calls = [];
  const $ = id => {
    if (!elements.has(id)) {
      const element = {id, dataset: {}, attributes: {}, textContent: "", className: "",
        setAttribute(key,value) {this.attributes[key]=value;}, removeAttribute(key) {delete this.attributes[key];}};
      element.classList = {add:name=>{if(!element.className.split(/\s+/).includes(name))element.className+=" "+name;},
        remove:name=>{element.className=element.className.split(/\s+/).filter(value=>value!==name).join(" ");},
        contains:name=>element.className.split(/\s+/).includes(name)};
      elements.set(id, element);
    }
    return elements.get(id);
  };
  const state = {session:{sessionId:"session",account:"fixture"},submitting:false,intents:[],submissions:[],
    confirmPayload:{sessionId:"session",operationId,problemId:"100",language:"C++20",filename:"A.cpp",fingerprint:"hash"}};
  const context = {state,$,Date,isProblemsRoute:()=>false,canSubmit:()=>true,
    call:async(method,args)=>{calls.push({method,args});return {state:"unknown",submission:{}};},
    persistIntents:async()=>{},renderNavigation:()=>{},renderSubmissions:()=>{},renderBoard:()=>{},renderHistoryCoverage:()=>{},
    resetConfirmation:()=>{state.confirmPayload=null;},modals:{submit:{hide:()=>{}}},
    DEFINITIVE_REJECTION_CODES:new Set(),message:error=>error.message,fail:error=>{throw error;},
  };
  vm.createContext(context);
  for (const [begin,end] of [["  function showMessage(","  function message("],
    ["  async function changeIntent(","  function epoch("],
    ["  function applyHistory(","  async function selectSession("],
    ["  async function submit(","  function interactiveResource("]])
    vm.runInContext(source.slice(source.indexOf(begin),source.indexOf(end,source.indexOf(begin))),context);
  const record = status => ({operationId,state:status,id:status==="confirmed"?"123":null});
  context.refresh = async()=>context.applyHistory({account:"fixture",submissions:[record(initialState)]});
  return {context,state,$,calls,record,submit:()=>context.submit({preventDefault(){}}),
    apply:rows=>context.applyHistory({account:"fixture",submissions:rows})};
}

for (const finalState of ["confirmed","rejected"]) test("only the matching "+finalState+" receipt clears its unresolved-submission notice",async()=>{
  const view=environment();await view.submit();
  assert.equal(view.calls.length,1);assert.equal(view.calls[0].method,"qoj_submit");
  assert.match(view.$("notice").textContent,/提交结果未确认/);
  view.apply([view.record("unknown")]);assert.equal(view.$("notice").classList.contains("d-none"),false);
  view.apply([view.record(finalState)]);
  assert.equal(view.$("notice").classList.contains("d-none"),true,"a verified receipt must remove its old unresolved warning");
  assert.equal(view.$("notice").textContent,"");assert.equal(view.state.intents[0].state,finalState);
});

test("an unrelated receipt cannot clear an unresolved-submission notice",async()=>{
  const view=environment();await view.submit();
  view.apply([{...view.record("confirmed"),operationId:"other-operation"},view.record("unknown")]);
  assert.match(view.$("notice").textContent,/提交结果未确认/);assert.equal(view.$("notice").classList.contains("d-none"),false);
});

test("a later unrelated warning remains after the old submission is confirmed",async()=>{
  const view=environment();await view.submit();
  view.context.showMessage(view.$("notice"),"榜单打开失败：当前离线","warning");
  view.apply([view.record("confirmed")]);
  assert.equal(view.$("notice").textContent,"榜单打开失败：当前离线");assert.equal(view.$("notice").classList.contains("d-none"),false);
});

test("an immediately reconciled submit does not leave its transient warning after automatic refresh",async()=>{
  const view=environment("confirmed");await view.submit();
  assert.equal(view.state.intents[0].state,"confirmed");
  assert.equal(view.$("notice").classList.contains("d-none"),true);
});
