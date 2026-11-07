"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../../src/firefox/ui.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../../src/firefox/ui.html"), "utf8");
const sid = "00000000-0000-4000-8000-000000000001";
const deferred = () => {let resolve, reject; const promise = new Promise((yes,no) => {resolve=yes; reject=no;}); return {promise,resolve,reject};};
const ticks = async () => {for (let i=0;i<5;i++) await new Promise(setImmediate);};
class Element {
  constructor(tag="div") {
    this.tagName=tag.toUpperCase(); this.children=[]; this.dataset={}; this.style={}; this.attributes={}; this.listeners={};
    this.textContent=""; this.className=""; this.value=""; this.hidden=false;
    this.classList={contains:n=>this.className.split(/\s+/).includes(n),add:n=>this.classList.toggle(n,true),remove:n=>this.classList.toggle(n,false),
      toggle:(n,yes)=>{this.className=this.className.split(/\s+/).filter(x=>x&&x!==n).concat(yes?[n]:[]).join(" ");}};
  }
  append(...values){this.children.push(...values);} replaceChildren(...values){this.children=values;}
  setAttribute(k,v){this.attributes[k]=String(v);} getAttribute(k){return this.attributes[k]??null;} removeAttribute(k){delete this.attributes[k];}
  addEventListener(k,v){this.listeners[k]=v;} querySelector(){return null;} querySelectorAll(){return [];}
  get firstChild(){return this.children[0];} get options(){return this.children;} reset(){}
}
function fixture() {
  const session={sessionId:sid,contestId:"4569",account:"fixture",title:"Saved Ucup",state:"running",startAt:Date.now()-100000,durationMs:18000000};
  return {session,contest:{id:"4569",account:"fixture",name:"Saved Ucup",problems:Array.from({length:14},(_,i)=>({id:String(100+i),label:String.fromCharCode(65+i),name:"Problem "+i}))},
    history:{account:"fixture",coverage:{complete:true},submissions:[{id:"3338719",problemId:"111",problemLabel:"L",language:"C++20",state:"confirmed",inSession:true,verdict:"CORRECT",elapsedMs:104492,submittedAt:session.startAt+104492}]}};
}
function stores() {
  const persistent=new Map(), local={};
  return {persistent,local,localStorage:{getItem:k=>persistent.get(k)??null,setItem:(k,v)=>persistent.set(k,String(v)),removeItem:k=>persistent.delete(k)},
    storage:{local:{get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:typeof keys==="string"?[keys]:Object.keys(local)).map(k=>[k,structuredClone(local[k])])),
      set:async values=>Object.assign(local,structuredClone(values)),remove:async key=>{delete local[key];}}}};
}
function page(saved, {blocked=false, snapshot=fixture(), search="", hash="#problems", handler}={}) {
  const elements=new Map(), calls=[], gates=new Map(), timers=[], listeners=[];
  const $=id=>{if(!elements.has(id)){const e=new Element();e.id=id;elements.set(id,e);}return elements.get(id);};
  for(const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const e=$(match[3]); e.tagName=match[1].toUpperCase(); e.className=match[2].match(/class="([^"]*)"/)?.[1]||""; e.hidden=/\bhidden\b/.test(match[2]);
  }
  const location={hash,search,reload:()=>{}};
  const window={addEventListener(){},localStorage:saved.localStorage};
  const context={window,localStorage:saved.localStorage,document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:()=>[],addEventListener(){},hidden:false},
    location,URL,URLSearchParams,Date,console,TextEncoder,TextDecoder,Uint8Array,ArrayBuffer,structuredClone,
    setTimeout,clearTimeout,setInterval:(handler,delay)=>timers.push({handler,delay}),clearInterval(){},
    bootstrap:{Modal:class {show(){} hide(){}},Dropdown:{getInstance:()=>null}},
    browser:{storage:saved.storage,runtime:{id:"fixture-extension",onMessage:{addListener:listener=>listeners.push(listener)},getURL:name=>"moz-extension://fixture/"+name,sendMessage:async message=>{
      calls.push(message); const method=message.method;
      if(handler) {const reply=await handler(message);if(reply!==undefined)return reply;}
      if(blocked) {if(!gates.has(method))gates.set(method,deferred());return gates.get(method).promise;}
      if(method==="hello")return {ok:true,result:{fixture:true,version:"0.3.1"}};
      if(method==="list_sessions")return {ok:true,result:{sessions:[snapshot.session]}};
      if(method==="board.snapshot")return {ok:true,result:{...context.VpBoardEngine.project(snapshot),inputKey:context.VpBoardEngine.inputKey(snapshot)}};
      if(method==="session_snapshot")return {ok:true,result:structuredClone(snapshot)};
      if(!gates.has(method))gates.set(method,deferred());return gates.get(method).promise;
    }}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync('src/firefox/board/generated/engine.js','utf8'),context);context.VpBoardView={render(){}};vm.runInContext(source,context);
  return {context,$,calls,gates,timers,listeners,state:()=>window.qojVpUi.getState()};
}

test("a reopened Problemset restores its title, fourteen cards and history before the helper connects",async()=>{
  const saved=stores(),first=page(saved);await ticks();
  assert.equal(first.$("problems-list").children.length,14);
  assert.equal(first.state().session.sessionId,sid);
  const reloaded=page(saved,{blocked:true});await ticks();
  assert.equal(reloaded.state().session?.sessionId,sid,"F5 must not show the no-contest shell while hello/list_sessions/session_snapshot waits");
  assert.equal(reloaded.$("session-label").textContent,"Saved Ucup");
  assert.equal(reloaded.$("problems-list").children.length,14);
  assert.equal(reloaded.$("submissions-body").children.length,1);
  assert.equal(reloaded.$("contest-view").hidden,false);
  assert.equal(reloaded.$("connection").classList.contains("d-none"),true,"normal startup has no blocking connection banner");
  assert.equal(reloaded.state().connected,false,"restoring display must not pretend the native helper is ready");
  assert.equal(reloaded.$("open-submit").getAttribute("aria-disabled"),"true");
  assert.equal(reloaded.calls.some(call=>call.method==="hello"),false,"startup must not spend a native round trip on an unused hello");
});

test("the saved view is already present synchronously, before browser storage or native replies",async()=>{
  const saved=stores();page(saved);await ticks();
  saved.storage.local.get=()=>new Promise(()=>{});
  const reloaded=page(saved,{blocked:true});
  assert.equal(reloaded.$("problems-list").children.length,14);
  assert.equal(reloaded.$("submissions-body").children.length,1);
  assert.equal(reloaded.state().session.sessionId,sid);
});

test("native verification retains cached card nodes and enables Submit only after the snapshot arrives",async()=>{
  const saved=stores(), data=fixture();page(saved,{snapshot:data});await ticks();
  const reloaded=page(saved,{blocked:true});await ticks();
  const card=reloaded.$("problems-list").children[0];
  reloaded.gates.get("list_sessions").resolve({ok:true,result:{sessions:[data.session]}});await ticks();
  assert.equal(reloaded.state().connected,false);assert.equal(reloaded.$("problems-list").children[0],card);
  assert.equal(reloaded.$("open-submit").getAttribute("aria-disabled"),"true");
  data.contest.problems[0].name="Fresh title";data.history.submissions[0].verdict="WRONG-ANSWER";
  reloaded.gates.get("session_snapshot").resolve({ok:true,result:data});await ticks();
  assert.equal(reloaded.state().connected,true);assert.equal(reloaded.$("problems-list").children[0],card);
  assert.equal(reloaded.$("open-submit").getAttribute("aria-disabled"),"false");
  assert.equal(reloaded.state().submissions[0].verdict,"WRONG-ANSWER");
  const again=page(saved,{blocked:true});await ticks();assert.equal(again.state().submissions[0].verdict,"WRONG-ANSWER");
});

test("a helper startup failure leaves cached cards and history readable",async()=>{
  const saved=stores();page(saved);await ticks();
  const reloaded=page(saved,{blocked:true});await ticks();
  reloaded.gates.get("list_sessions").reject(new Error("helper unavailable"));await ticks();
  assert.equal(reloaded.$("problems-list").children.length,14);assert.equal(reloaded.$("submissions-body").children.length,1);
  assert.equal(reloaded.$("contest-view").hidden,false);assert.equal(reloaded.state().connected,false);
  assert.match(reloaded.$("connection").textContent,/helper unavailable/);
});

test("an explicit other contest never displays the previously selected contest",async()=>{
  const saved=stores();page(saved);await ticks();
  const other="00000000-0000-4000-8000-000000000002";
  for(const options of [{search:"?session="+other},{hash:"#jury/contest/"+other}]) {
    const reloaded=page(saved,{blocked:true,...options});await ticks();
    assert.equal(reloaded.state().session,null);assert.equal(reloaded.$("problems-list").children.length,0);
  }
});

test("a deleted session is evicted and cannot reappear from display storage",async()=>{
  const saved=stores();page(saved);await ticks();
  const reloaded=page(saved,{blocked:true});await ticks();
  reloaded.gates.get("list_sessions").resolve({ok:true,result:{sessions:[]}});await ticks();
  assert.equal(reloaded.state().session,null);assert.equal(reloaded.$("contest-view").hidden,true);
  assert.equal(reloaded.$("empty-state").hidden,false);
  const again=page(saved,{blocked:true});await ticks();assert.equal(again.state().session,null);
  assert.equal([...saved.persistent.values()].some(raw=>JSON.parse(raw).contest),false);
});

test("corrupt or unavailable display storage does not block normal initialization",async()=>{
  for(const broken of ["invalid-json","disabled"]) {
    const saved=stores();page(saved);await ticks();
    if(broken==="invalid-json") for(const key of saved.persistent.keys()) saved.persistent.set(key,"{");
    else {saved.localStorage.getItem=()=>{throw Error("disabled");};saved.localStorage.setItem=()=>{throw Error("disabled");};}
    const reloaded=page(saved);await ticks();
    assert.equal(reloaded.state().connected,true);assert.equal(reloaded.$("problems-list").children.length,14);
  }
});

test("display persistence omits source files and form tokens",async()=>{
  const saved=stores(), data=fixture();data.contest.csrf="fake-sensitive-token";
  data.history.submissions[0].sourceBase64="fake-source-code";
  page(saved,{snapshot:data});await ticks();
  const serialized=[...saved.persistent.values()].join("\n");
  assert.doesNotMatch(serialized,/fake-sensitive-token|fake-source-code/);
  assert.match(serialized,/3338719/);
});

test("the register preparation URL runs the real resource workflow after the matching session and manifest load",async()=>{
  const data=fixture(), gate=deferred();
  Object.assign(data.session,{state:"prepared",startAt:null,qojVirtual:{mode:"qoj-native"}});
  data.contest.problems=data.contest.problems.slice(0,3);data.history.submissions=[];
  const ready=id=>({problemId:id,status:"ready",kind:"samples",resourceId:"a".repeat(64),sha256:"a".repeat(64),totalBytes:123,filename:"samples-"+id+".zip"});
  const view=page(stores(),{snapshot:data,search:"?session="+sid+"&resources=1&prepare=1",hash:"#home",handler:async request=>{
    if(request.method==="resource_manifest")return {ok:true,result:{origin:"https://qoj.ac",account:data.session.account,contestId:data.session.contestId,problems:[ready("100")]}};
    if(request.method==="prepare_resource") {
      assert.equal(request.args.sessionId,sid);
      if(request.args.problemId==="101")await gate.promise;
      return {ok:true,result:ready(request.args.problemId)};
    }
  }});
  await ticks();
  assert.equal(view.context.location.hash,"#jury/contest/"+sid);
  assert.equal(view.state().session.sessionId,sid);assert.equal(view.state().session.startAt,null);
  assert.deepEqual(view.calls.filter(call=>call.method==="prepare_resource").map(call=>call.args.problemId),["101"],"reuse the cached first problem, then prepare sequentially");
  assert.equal(view.state().resourcePreparing,true);
  gate.resolve();await ticks();
  assert.deepEqual(view.calls.filter(call=>call.method==="prepare_resource").map(call=>call.args.problemId),["101","102"]);
  assert.equal(view.state().resourcePreparing,false);assert.equal(view.state().resources.length,3);
  assert.equal(view.calls.some(call=>/^(start_session|qoj_confirm_virtual_start|qoj_submit)$/.test(call.method)),false);
});

test("the actual started message listener verifies native state before returning the prepared view to Home",async()=>{
  const data=fixture();Object.assign(data.session,{state:"prepared",startAt:null,qojVirtual:{mode:"qoj-native"}});
  const startAt=Date.now()-71234,started={...data.session,state:"running",startAt,qojVirtual:{mode:"qoj-native",startAt}};
  const view=page(stores(),{snapshot:data,hash:"#jury/contest/"+sid,handler:async request=>{
    if(request.method==="inspect_session")return {ok:true,result:started};
  }});await ticks();
  const notify=view.listeners[0],message={type:"vp.qoj.started",sessionId:sid};
  assert.equal(notify(message,{id:"foreign-extension"}),undefined);
  assert.equal(notify({...message,sessionId:"another"},{id:"fixture-extension"}),undefined);
  assert.equal(view.calls.some(call=>call.method==="inspect_session"),false);
  assert.equal((await notify(message,{id:"fixture-extension"})).handled,true);
  assert.equal(view.context.location.hash,"#home");assert.equal(view.state().session.startAt,startAt);
  assert.equal(view.state().session.state,"running");
  assert.equal(view.calls.filter(call=>call.method==="inspect_session").length,1);
});

test("an older prepared snapshot cannot undo the native Start notification or send Home back to resource preparation",async()=>{
  const data=fixture(), gate=deferred();
  Object.assign(data.session,{state:"prepared",startAt:null,qojVirtual:{mode:"qoj-native"}});
  const startAt=Date.now()-12345,started={...data.session,state:"running",startAt,qojVirtual:{mode:"qoj-native",startAt}};
  const view=page(stores(),{snapshot:data,search:"?session="+sid+"&resources=1&prepare=1",handler:async request=>{
    if(request.method==="session_snapshot")return gate.promise;
    if(request.method==="inspect_session")return {ok:true,result:started};
    if(request.method==="resource_manifest")return {ok:true,result:{origin:"https://qoj.ac",account:data.session.account,contestId:data.session.contestId,problems:[]}};
  }});await ticks();
  assert.equal((await view.listeners[0]({type:"vp.qoj.started",sessionId:sid},{id:"fixture-extension"})).handled,true);
  assert.equal(view.state().session.startAt,startAt);
  gate.resolve({ok:true,result:data});await ticks();
  assert.equal(view.state().session.startAt,startAt);assert.equal(view.state().session.state,"running");
  assert.equal(view.state().connected,true);assert.equal(view.$("problems-list").children.length,14);
  assert.equal(view.$("open-submit").getAttribute("aria-disabled"),"false");
  assert.equal(view.context.location.hash,"#home");
  assert.equal(view.calls.some(call=>call.method==="prepare_resource"),false);
});

test("a delayed session list and snapshot retain an already confirmed native start in navigation and display storage",async()=>{
  const saved=stores(),data=fixture();Object.assign(data.session,{state:"prepared",startAt:null,qojVirtual:{mode:"qoj-native"}});
  page(saved,{snapshot:data});await ticks();
  const gate=deferred(),startAt=Date.now()-12345,started={...data.session,state:"running",startAt,qojVirtual:{mode:"qoj-native",startAt}};
  const view=page(saved,{snapshot:data,handler:async request=>{
    if(request.method==="list_sessions")return gate.promise;
    if(request.method==="inspect_session")return {ok:true,result:started};
  }});await ticks();
  assert.equal((await view.listeners[0]({type:"vp.qoj.started",sessionId:sid},{id:"fixture-extension"})).handled,true);
  gate.resolve({ok:true,result:{sessions:[data.session]}});await ticks();
  assert.equal(view.state().session.startAt,startAt);assert.equal(view.state().session.state,"running");
  const index=JSON.parse(saved.persistent.get("vpUiDisplayIndexV1"));
  assert.equal(index.sessions[0].startAt,startAt);assert.equal(index.sessions[0].state,"running");
  assert.equal(view.context.location.hash,"#home");
});

test("native Start preserves an in-flight resource job and a late prepared settings reply cannot rewind its clock",async()=>{
  const data=fixture(), resourceGate=deferred(),settingsGate=deferred();
  Object.assign(data.session,{state:"prepared",startAt:null,qojVirtual:{mode:"qoj-native"}});
  data.contest.problems=data.contest.problems.slice(0,2);data.history.submissions=[];
  const startAt=Date.now()-12345,started={...data.session,state:"running",startAt,qojVirtual:{mode:"qoj-native",startAt}};
  const ready=id=>({problemId:id,status:"ready",kind:"samples",resourceId:"a".repeat(64),sha256:"a".repeat(64),totalBytes:123,filename:"samples-"+id+".zip"});
  const view=page(stores(),{snapshot:data,search:"?session="+sid+"&resources=1&prepare=1",handler:async request=>{
    if(request.method==="resource_manifest")return {ok:true,result:{origin:"https://qoj.ac",account:data.session.account,contestId:data.session.contestId,problems:[]}};
    if(request.method==="prepare_resource") {if(request.args.problemId==="100")await resourceGate.promise;return {ok:true,result:ready(request.args.problemId)};}
    if(request.method==="inspect_session")return {ok:true,result:started};
    if(request.method==="update_session")return settingsGate.promise;
  }});await ticks();
  assert.equal(view.state().resourcePreparing,true);
  const saving=view.$("rankland-form").listeners.submit({preventDefault(){},submitter:{disabled:false}});
  await ticks();assert.equal(view.calls.filter(call=>call.method==="update_session").length,1);
  await view.listeners[0]({type:"vp.qoj.started",sessionId:sid},{id:"fixture-extension"});
  assert.equal(view.state().resourcePreparing,true);assert.equal(view.context.location.hash,"#home");
  settingsGate.resolve({ok:true,result:data.session});await saving;
  assert.equal(view.state().session.startAt,startAt);assert.equal(view.state().session.state,"running");
  resourceGate.resolve();await ticks();
  assert.equal(view.state().resourcePreparing,false);assert.equal(view.state().resources.length,2);
  assert.deepEqual(view.calls.filter(call=>call.method==="prepare_resource").map(call=>call.args.problemId),["100","101"]);
  assert.equal(view.context.location.hash,"#home");
});

function ranklandPage({sync, configured=true, nextSnapshot, syncStatus=()=>null}={}) {
  const data=fixture();
  if(configured) data.session.ranklandUrl="https://vp.xcpc.link/?contest=synthetic&run="+sid;
  let imported=false;
  const view=page(stores(),{snapshot:data,hash:"#home",handler:async request=>{
    const {method,args}=request;
    if(method==="scoreboard.view") {const result=await sync?.(request);return {ok:true,result:result||{state:"ready",synced:1,pending:0}};}
    const selected=nextSnapshot?.session.sessionId===args?.sessionId?nextSnapshot:data;
    if(method==="session_snapshot")return {ok:true,result:structuredClone(selected)};
    if(method==="qoj_contest")return {ok:true,result:structuredClone(selected.contest)};
    if(method==="qoj_submissions")return {ok:true,result:{...structuredClone(selected.history),submissions:selected.history.submissions.map(item=>({...item,verdict:imported?"TIMELIMIT":item.verdict}))}};
    if(method==="rankland.snapshot")return {ok:true,result:{state:"unavailable",url:selected.session.ranklandUrl,snapshot:null,syncStatus:syncStatus()}};
    if(method==="scoreboard.resolve")return {ok:true,result:{source:configured?"rankland":"qoj",state:configured?"configured":"unmatched",url:selected.session.ranklandUrl||"https://qoj.ac/contest/4569",session:structuredClone(selected.session)}};
  }});
  return {...view,data};
}

test("Home hides exports and Jury opens a view-only historical board",async()=>{
 const view=ranklandPage();await ticks();
 assert.equal(view.$("sync-rankland").hidden,true);assert.equal(view.$("sync-rankland").disabled,true);
 assert.equal(view.$("stop-rankland-sync").hidden,true);
 view.context.location.hash="#jury/contest/"+sid;
 await view.$("sync-scoreboard").listeners.click();
 assert.equal(view.calls.filter(item=>item.method==="scoreboard.view").length,1);
 assert.equal(view.calls.filter(item=>item.method==="rankland.sync").length,0);
 assert.equal(view.state().submissions[0].verdict,"CORRECT");
});
test("opening a board coalesces clicks and leaves pending submissions and the editor untouched",async()=>{
 const gate=deferred(),view=ranklandPage({sync:()=>gate.promise});await ticks();
 const input=view.$("submit_problem_code"),file=Object.freeze({name:"L.cpp",size:27});input.files=[file];
 const first=view.$("sync-scoreboard").listeners.click();await ticks();
 assert.equal(view.$("sync-scoreboard").disabled,true);
 const second=view.$("sync-scoreboard").listeners.click();gate.resolve({source:"rankland"});await Promise.all([first,second]);
 assert.equal(view.calls.filter(item=>item.method==="scoreboard.view").length,1);
 assert.equal(view.calls.some(item=>item.method==="rankland.sync"),false);
 assert.equal(input.files[0],file);assert.equal(view.state().submissions[0].verdict,"CORRECT");
 assert.equal(view.$("sync-scoreboard").disabled,false);
});

test("Jury rule controls only require reveal settings for CCPC26",async()=>{
 const p=page(stores(),{hash:"#jury"});await ticks();
 for(const rule of ["ICPC","auto","CCPC26","ICPC"]) {
   p.$("board-rule").value=rule;p.$("board-rule").listeners.change();
   assert.equal(p.$("board-reveal-settings").hidden,rule!=="CCPC26");
   assert.equal(p.$("board-reveal-settings").disabled,rule!=="CCPC26");
 }
});

test("changing the rule updates the draft RankLand URL without saving the session",async()=>{
 const snapshot=fixture();
 snapshot.session.ranklandUrl="https://vp.xcpc.link/?contest=ccpc2024hv&rule=ICPC&at=2026-11-01T00%3A00%3A00Z&play=0&team=My+team";
 snapshot.session.board={rule:"ICPC",revealCount:50,revealRatio:20};
 const p=page(stores(),{snapshot,hash:"#jury"});await ticks();
 p.$("rankland-settings").listeners.click();
 p.$("board-rule").value="CCPC26";p.$("board-rule").listeners.change();
 let q=new URL(p.$("rankland-url").value).searchParams;
 assert.equal(q.get("rule"),"CCPC26");assert.equal(q.get("count"),"50");assert.equal(q.get("ratio"),"20");
 assert.equal(q.get("contest"),"ccpc2024hv");assert.equal(q.get("play"),"0");assert.equal(q.get("team"),"My team");
 assert.equal(q.get("at"),"2026-11-01T00:00:00Z");
 p.$("board-count").value="10";p.$("board-count").listeners.input();
 p.$("board-ratio").value="25";p.$("board-ratio").listeners.input();
 q=new URL(p.$("rankland-url").value).searchParams;
 assert.equal(q.get("count"),"10");assert.equal(q.get("ratio"),"25");
 p.$("board-rule").value="ICPC";p.$("board-rule").listeners.change();
 q=new URL(p.$("rankland-url").value).searchParams;
 assert.equal(q.get("rule"),"ICPC");assert.equal(q.has("count"),false);assert.equal(q.has("ratio"),false);
 p.$("board-rule").value="auto";p.$("board-rule").listeners.change();
 q=new URL(p.$("rankland-url").value).searchParams;
 assert.equal(q.has("rule"),false);assert.equal(q.has("count"),false);assert.equal(q.has("ratio"),false);
 assert.equal(p.calls.some(c=>c.method==="update_session"),false,"editing is a draft until Save");
 p.$("rankland-settings").listeners.click();
 assert.equal(p.$("board-rule").value,"ICPC");
 assert.equal(p.$("rankland-url").value,snapshot.session.ranklandUrl,"reopening discards unsaved edits");
 for(const raw of ["","https://"]) {
   p.$("rankland-url").value=raw;p.$("board-rule").value="CCPC26";p.$("board-rule").listeners.change();
   assert.equal(p.$("rankland-url").value,raw);
 }
});
