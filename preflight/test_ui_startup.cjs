"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../extension/ui.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../extension/ui.html"), "utf8");
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
function page(saved, {blocked=false, snapshot=fixture(), search="", hash="#problems"}={}) {
  const elements=new Map(), calls=[], gates=new Map(), timers=[];
  const $=id=>{if(!elements.has(id)){const e=new Element();e.id=id;elements.set(id,e);}return elements.get(id);};
  for(const match of html.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const e=$(match[3]); e.tagName=match[1].toUpperCase(); e.className=match[2].match(/class="([^"]*)"/)?.[1]||""; e.hidden=/\bhidden\b/.test(match[2]);
  }
  const location={hash,search,reload:()=>{}};
  const window={addEventListener(){},localStorage:saved.localStorage};
  const context={window,localStorage:saved.localStorage,document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:()=>[],addEventListener(){},hidden:false},
    location,URL,URLSearchParams,Date,console,TextEncoder,TextDecoder,Uint8Array,ArrayBuffer,structuredClone,
    setTimeout,clearTimeout,setInterval:f=>timers.push(f),clearInterval(){},
    bootstrap:{Modal:class {show(){} hide(){}},Dropdown:{getInstance:()=>null}},
    browser:{storage:saved.storage,runtime:{getURL:name=>"moz-extension://fixture/"+name,sendMessage:async message=>{
      calls.push(message); const method=message.method;
      if(blocked) {if(!gates.has(method))gates.set(method,deferred());return gates.get(method).promise;}
      if(method==="hello")return {ok:true,result:{fixture:true,version:"0.3.1"}};
      if(method==="list_sessions")return {ok:true,result:{sessions:[snapshot.session]}};
      if(method==="session_snapshot")return {ok:true,result:structuredClone(snapshot)};
      if(!gates.has(method))gates.set(method,deferred());return gates.get(method).promise;
    }}}};
  vm.createContext(context);vm.runInContext(source,context);
  return {context,$,calls,gates,timers,state:()=>window.qojVpUi.getState()};
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
