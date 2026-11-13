"use strict";
const test=require("node:test"), assert=require("node:assert/strict"), fs=require("node:fs"), vm=require("node:vm");
const tick=()=>new Promise(setImmediate);
function page() {
  const elements=new Map(), messages=[],events={}, calls=[];
  const element=id=>{
    if(!elements.has(id))elements.set(id,{value:id==="ready-language"?"cpp":"A",children:[],listeners:{},
      append(value){this.children.push(value);},replaceChildren(){this.children=[];},addEventListener(type,fn){this.listeners[type]=fn;}});
    return elements.get(id);
  };
  const session={sessionId:"session",contestId:"4686",account:"User",state:"prepared",startAt:null};
  const contest={name:"Contest",problems:[{id:"1",label:"A"},{id:"2",label:"B"}]};
  const model={history:false,stored:true,missing:true,cli:false,hold:null},state={generation:0};
  const parent={postMessage:message=>messages.push(structuredClone(message))};
  const context={setTimeout,clearTimeout,Option:class{constructor(label,value){this.label=label;this.value=value;}},
    document:{getElementById:element,createElement:()=>({}),querySelector:()=>null},
    window:{parent,addEventListener:(type,fn)=>{events[type]=fn;}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync("src/firefox/ready-ui.js","utf8"),context);
  const call=async(method,args)=>{
    calls.push({method,args});
    if(method==="connect")return {session,contest};
    if(method==="inspect_session")return session;
    if(method==="qoj_problem_form"&&model.missing&&args.problemId==="2")throw Error("offline");
    if(method==="board.snapshot") {if(model.hold)return model.hold;return {scope:model.history?"historical":"local",stored:model.stored};}
    if(method==="submitter_check"&&!model.cli)throw Error("请运行 qoj login");
    if(method==="submitter_check"||method==="submitter_bind")return {ready:true,account:"User",language:"C++20",output:"Dry run: no submission sent."};
    return {};
  };
  const ui=context.VpReadyUi.create({token:"ticket",state,call,modals:Object.fromEntries(["resources","manual-samples","rankland","ready-judger","ready-warning"].map(id=>[id,{show(){},hide(){}}])),
    openResources(){},openRanklandSettings(){},loadResourceManifest:async()=>{},prepareResources:async()=>{},readyResource:()=>true});
  return {ui,model,element,calls,state,messages,latest:()=>messages.filter(m=>m.action==="state").at(-1).states,
    check:()=>events.message({source:parent,origin:"https://qoj.ac",data:{type:"vp.ready.ui",token:"ticket",action:"check"}})};
}
test("cached samples, a board URL and browser login do not substitute for the three real checks", async()=>{
  const p=page();await p.ui.initialize();
  assert.equal(p.latest().resources.state,"attention");assert.match(p.latest().resources.detail,/B/);
  assert.equal(p.latest().board.state,"attention");assert.equal(p.latest().judger.state,"attention");
  p.model.missing=false;p.model.history=true;p.model.cli=true;p.check();await tick();await tick();
  assert.deepEqual(Object.values(p.latest()).map(x=>x.state),["ready","ready","ready"]);
  p.element("ready-language").listeners.change();assert.equal(p.latest().judger.state,"attention");
  await p.element("ready-judger-bind").listeners.click();await tick();
  assert.equal(p.calls.at(-1).method,"submitter_bind");assert.equal(p.latest().judger.state,"ready");
  assert.equal(p.state.session.startAt,null);
  p.ui.invalidate("board");p.ui.failed("board",new Error("保存失败，请重试"));
  assert.equal(p.latest().board.state,"attention");
});
test("editing the board while its old request completes keeps the new setting unconfirmed", async()=>{
  const p=page();let release;p.model.hold=new Promise(resolve=>{release=resolve;});
  const job=p.ui.initialize();await tick();
  p.element("rankland-form").listeners.input();release({scope:"historical"});await job;
  assert.equal(p.latest().board.state,"attention");assert.match(p.latest().board.detail,/保存/);
});
test("board readiness requires the downloaded archive to be saved locally", async()=>{
  const p=page();p.model.history=true;p.model.stored=false;await p.ui.initialize();
  assert.equal(p.latest().board.state,"attention");
  p.model.stored=true;p.check();await tick();await tick();
  assert.equal(p.latest().board.state,"ready");
});
test("switching from resources to manual samples keeps the frame visible through backdrop animation", async()=>{
  const p=page();
  p.element("resources-modal").listeners["show.bs.modal"]();
  p.element("resources-modal").listeners["hidden.bs.modal"]();
  p.element("manual-samples-modal").listeners["show.bs.modal"]();
  await new Promise(resolve=>setTimeout(resolve,40));
  assert.equal(p.messages.filter(m=>m.action==="close").length,0);
  p.element("manual-samples-modal").listeners["hidden.bs.modal"]();
  await new Promise(resolve=>setTimeout(resolve,40));
  assert.equal(p.messages.filter(m=>m.action==="close").length,1);
});
