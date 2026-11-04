"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm"), test = require("node:test");
const source = fs.readFileSync(require("node:path").join(__dirname, "../../src/firefox/ui.js"), "utf8");
const sid = "00000000-0000-4000-8000-000000000001", other = "00000000-0000-4000-8000-000000000002";
const deferred = () => {let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const tick = () => new Promise(setImmediate);
class Element {
 constructor(tag="div") {this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.style={};this.attributes={};this.className="";this.textContent="";this.listeners={};this.classList={
  contains:n=>this.className.split(/\s+/).includes(n), add:n=>this.classList.toggle(n,true),remove:n=>this.classList.toggle(n,false),
  toggle:(n,yes)=>{this.className=this.className.split(/\s+/).filter(v=>v&&v!==n).concat(yes?[n]:[]).join(" ");}};}
 append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;this.replacementCount=(this.replacementCount||0)+1;if(this.id==="submit_problem_language"||this.id==="submit_problem_problem")this.value=items[0]?.value||"";} setAttribute(k,v){this.attributes[k]=String(v);} removeAttribute(k){delete this.attributes[k];}
 addEventListener(k,v){this.listeners[k]=v;} get firstChild(){return this.children[0];}
 get options(){return this.children;}
}
function snapshot(id=sid, {cached=true}={}) {
 const contestId=id===sid?"3387":"1051", account="fixture";
 const session={sessionId:id,contestId,account,title:"Fixture "+contestId,state:"running",startAt:1793500000000,durationMs:18000000};
 return {session,contest:cached?{id:contestId,account,name:session.title,problems:Array.from({length:14},(_,i)=>({id:String(100+i),label:String.fromCharCode(65+i),name:"Problem "+i}))}:null,
  history:{account,submissions:[{id:"333",problemId:"100",problemLabel:"A",language:"C++20",state:"confirmed",inSession:true,elapsedMs:1000,submittedAt:1793500001000,verdict:"CORRECT"}],coverage:{complete:false,warning:"Cached history; refresh to query QOJ"}}};
}
function environment({first=snapshot(), second=snapshot(other), snapshotWait}={}) {
 const snapshots=new Map([[sid,first],[other,second]]), calls=[], pending=new Map(), elements=new Map(), observed=[];
 const state={connected:true,sessions:[first.session,second.session],session:null,contest:null,submissions:[],intents:[],generation:0,submitting:false,
  forms:new Map(),resources:new Map(),resourceActivity:new Map(),resourceInteractive:new Map(),resourceDownloads:new Set(),resourceReadSequence:0,
  contestRequests:new Map(),historyRequests:new Map(),sessionRequest:null,refreshPromise:null,refreshSession:null,historyLoaded:false};
 const $=id=>{if(!elements.has(id)){const e=new Element();e.id=id;elements.set(id,e);}return elements.get(id);};
 const context={state,$,URL,Date,location:{hash:"#home"},ACTIVE_KEY:"active",document:{createElement:t=>new Element(t)},
  browser:{storage:{local:{set:async()=>{}}}},persistIntents:async()=>{},
  current:(id,gen)=>state.session?.sessionId===id&&state.generation===gen,
  call:async(method,args)=>{calls.push({method,args});
    if(method==="session_snapshot") {if(snapshotWait)await snapshotWait.promise;return structuredClone(snapshots.get(args.sessionId));}
    const key=method+":"+args.sessionId; if(!pending.has(key))pending.set(key,deferred());return pending.get(key).promise;
  },
  renderBoard:()=>{},resetRanklandSnapshot:()=>{},refreshBoard:()=>{},resetScoreboardSource:()=>{},resolveScoreboardSource:()=>{},renderScoreboardSource:()=>{},loadResourceManifest:()=>{},renderResourceModal:()=>{},renderNavigation:()=>{},renderSession:()=>{},renderClock:()=>{},
  renderSummary:()=>observed.push({contest:state.contest,submissions:state.submissions.slice()}),message:e=>e.message,fail:e=>{throw e;},
  showMessage:(target,text)=>{target.textContent=text;target.hidden=false;},hideMessage:target=>{target.textContent="";target.hidden=true;},
  safeQojUrl:(url,fallback)=>url||fallback,problemUrl:p=>"https://qoj.ac/problem/"+p.id,readyResources:()=>[],updateResourceBusyControls:()=>{},cardSubmit:()=>new Element("a"),
  badge:label=>{const e=new Element("span");e.textContent=label;return e;},
  contestName:contest=>contest.name,
 };
 vm.createContext(context);
 for(const [begin,end] of [["  function node(","  function showMessage("],["  function epoch(","  function canSubmit("],
   ["  function renderSubmissions(","  function isProblemsRoute("],["  function isProblemsRoute(","  async function listSessions("],
   ["  function sharedRead(","  function openSessionSetup("]])vm.runInContext(source.slice(source.indexOf(begin),source.indexOf(end)),context);
 return {context,state,$,calls,pending,observed,snapshots};
}

test("reload renders fourteen cached cards and cached submissions before either network promise settles",async()=>{
 const view=environment(); await view.context.selectSession(sid);
 assert.equal(view.$("problems-list").children.length,14);assert.equal(view.$("submissions-body").children.length,1);
 assert.equal(view.state.historyLoaded,true);assert.equal(view.$("history-warning").hidden,true);
 assert.match(view.$("refresh-status").textContent,/已保存记录可继续查看/);
 assert.equal(view.pending.size,2);assert.equal(view.state.contestRefreshing,true);
 view.context.location.hash="#problems";view.context.route();
 assert.equal(view.$("problems-view").hidden,false);assert.equal(view.$("problems-list").children.length,14);
 view.context.location.hash="#home";view.context.route();assert.equal(view.$("home-view").hidden,false);
 // A fresh page instance (F5) independently restores the same durable snapshot.
 const reloaded=environment();await reloaded.context.selectSession(sid);
 assert.equal(reloaded.$("problems-list").children.length,14);assert.equal(reloaded.$("submissions-body").children.length,1);
});

test("slow local snapshot coalesces duplicate selection and slow network coalesces repeated refreshes",async()=>{
 const gate=deferred(),view=environment({snapshotWait:gate});
 const first=view.context.selectSession(sid),second=view.context.selectSession(sid);
 assert.equal(view.calls.filter(c=>c.method==="session_snapshot").length,1);
 const earlyRefresh=view.context.refresh(true);
 assert.equal(view.calls.filter(c=>c.method==="qoj_submissions").length,0,"network history must wait until local snapshot is applied");
 gate.resolve();await Promise.all([first,second]);
 const refreshes=Array.from({length:20},()=>view.context.refresh(true));
 assert.equal(view.calls.filter(c=>c.method==="qoj_submissions").length,1);
 const result={...snapshot().history,submissions:[{...snapshot().history.submissions[0],id:"334",verdict:"WRONG-ANSWER"}],coverage:{complete:true}};
 view.pending.get("qoj_submissions:"+sid).resolve(result);await Promise.all([...refreshes,earlyRefresh]);
 assert.equal(view.$("submissions-body").children.length,1);assert.equal(view.state.submissions[0].id,"334");
 assert.equal(view.$("refresh-submissions").disabled,false);
 // A same-session selection also retains the cards throughout local reload.
 const selection=view.context.selectSession(sid);assert.equal(view.$("problems-list").children.length,14);await selection;
 assert.equal(view.calls.filter(c=>c.method==="qoj_contest").length,1);
});

test("history updates independently of a blocked contest refresh and failures retain both cached views",async()=>{
 const view=environment();await view.context.selectSession(sid);
 view.pending.get("qoj_submissions:"+sid).resolve({...snapshot().history,submissions:[{...snapshot().history.submissions[0],id:"335"}],coverage:{complete:true}});
 await tick();assert.equal(view.state.submissions[0].id,"335");assert.equal(view.state.contestRefreshing,true);
 view.pending.get("qoj_contest:"+sid).reject(new Error("network timeout"));await tick();
 assert.equal(view.$("problems-list").children.length,14);assert.equal(view.$("submissions-body").children.length,1);
 assert.match(view.$("problemset-status").textContent,/保留已保存/);assert.equal(view.$("refresh-contest").hidden,false);
 view.pending.set("qoj_submissions:"+sid,deferred());const again=view.context.refresh(true);
 view.pending.get("qoj_submissions:"+sid).reject(new Error("network unavailable"));await assert.rejects(again);
 assert.equal(view.state.submissions[0].id,"335");assert.match(view.$("refresh-status").textContent,/保留已保存/);
});

test("a missing cached contest still shows history and an explicit problem-loading state",async()=>{
 const view=environment({first:snapshot(sid,{cached:false})});await view.context.selectSession(sid);
 assert.equal(view.$("submissions-body").children.length,1);assert.equal(view.$("problems-list").children.length,0);
 assert.match(view.$("problemset-title").textContent,/Fixture 3387/);assert.match(view.$("problemset-status").textContent,/正在读取题表/);
 view.pending.get("qoj_contest:"+sid).resolve(snapshot().contest);await tick();assert.equal(view.$("problems-list").children.length,14);
});

test("late provider replies from the previous contest cannot overwrite the selected contest",async()=>{
 const view=environment();await view.context.selectSession(sid);await view.context.selectSession(other);
 view.pending.get("qoj_contest:"+sid).resolve({...snapshot().contest,name:"OLD RESPONSE"});
 view.pending.get("qoj_submissions:"+sid).resolve({...snapshot().history,submissions:[]});await tick();
 assert.equal(view.state.session.sessionId,other);assert.equal(view.state.contest.id,"1051");
 assert.equal(view.$("problems-list").children.length,14);assert.equal(view.$("submissions-body").children.length,1);
});

test("malformed provider refreshes preserve the last verified data",async()=>{
 const view=environment();await view.context.selectSession(sid);
 view.pending.get("qoj_contest:"+sid).resolve({...snapshot().contest,problems:null});
 view.pending.get("qoj_submissions:"+sid).resolve({account:"different-account",submissions:[]});await tick();
 assert.equal(view.$("problems-list").children.length,14);assert.equal(view.$("submissions-body").children.length,1);
 assert.equal(view.state.submissions[0].id,"333");
});

test("a late live contest response updates card text without detaching the card being used",async()=>{
 const view=environment();await view.context.selectSession(sid);
 const list=view.$("problems-list"),cards=list.children.slice(),replacements=list.replacementCount;
 const firstBody=cards[0].children[0].children[0],submit=firstBody.children[3].children[0];
 const fresh=snapshot().contest;fresh.problems[0].name="Updated statement title";
 view.pending.get("qoj_contest:"+sid).resolve(fresh);await tick();
 assert.equal(list.replacementCount,replacements,"live refresh must not detach an unchanged problem list");
 cards.forEach((card,index)=>assert.equal(list.children[index],card,"the visible card must survive the async response"));
 assert.equal(firstBody.children[1].textContent,"Updated statement title");
 assert.equal(firstBody.children[3].children[0],submit,"Submit identity must remain valid while the user is pointing at it");
 const selected=view.context.selectSession(sid);await selected;
 assert.equal(list.children[0],cards[0],"same-contest local reload also retains existing controls");
});

test("first submit dialog becomes ready after language loading and background refresh preserves the chosen file and language",async()=>{
 const view=environment(),{context,$}=view;let resets=0,shown=false;
 view.state.formGeneration=0;
 context.Option=function(label,value){const option=new Element("option");option.textContent=label;option.value=value;return option;};
 context.canSubmit=()=>true;context.problemById=id=>view.state.contest.problems.find(p=>p.id===id);
 context.modals={submit:{show:()=>shown=true}};
 $("submit_problem_code").files=[];
 $("submit-form").reset=()=>{resets++;$("submit_problem_code").files=[];};
 for(const [begin,end] of [["  function inferLanguage(","  function bytesBase64("],["  function renderSession(","  function ranklandViewIdentity("]])
  vm.runInContext(source.slice(source.indexOf(begin),source.indexOf(end,source.indexOf(begin))),context);
 await context.selectSession(sid);
 const opening=context.openSubmit("100"),language=$("submit_problem_language"),sourceInput=$("submit_problem_code");
 assert.equal(shown,true);assert.equal(language.disabled,true);assert.equal(language.options.length,1);
 const loadingOption=language.options[0],file=Object.freeze({name:"A.cpp",size:27});
 sourceInput.files=[file];
 view.pending.get("qoj_problem_form:"+sid).resolve({languages:["C++20","Python3"]});await opening;
 assert.equal(language.disabled,false);assert.equal(language.value,"C++20");
 assert.ok(!language.options.includes(loadingOption),"the initial placeholder is intentionally replaced only when the form becomes usable");
 language.value="Python3";const selectedOption=language.options[2];
 view.pending.get("qoj_contest:"+sid).resolve({...snapshot().contest,name:"Fresh contest title"});
 view.pending.get("qoj_submissions:"+sid).resolve({...snapshot().history,coverage:{complete:true}});await tick();
 assert.equal($("submit_problem_code"),sourceInput);assert.equal(sourceInput.files[0],file);
 assert.equal($("submit_problem_language"),language);assert.equal(language.value,"Python3");assert.equal(language.options[2],selectedOption);
 assert.equal(resets,1,"background contest/history updates must never reset an open submit form");
});
