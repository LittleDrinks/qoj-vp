"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const root = path.join(__dirname, "..");
const background = fs.readFileSync(path.join(root, "extension/background.js"), "utf8");
const content = fs.readFileSync(path.join(root, "extension/qoj-prepare-content.js"), "utf8");
const sid = "11111111-2222-4333-8444-555555555555", otherSid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const account = "LittleDrinks", cid = "4582";
const ready = id => ({problemId:id,status:"ready",kind:"attachment",resourceId:"a".repeat(64),sha256:"a".repeat(64),totalBytes:123});
const sender = {id:"extension-test",frameId:0,url:"https://qoj.ac/contest/4582",tab:{id:7}};
function environment(initial = []) {
  const calls=[],progress=[],opened=[],sessions=initial.map(value=>({...value})); let prepareActive=0,maximum=0;
  const context = {URL,Map,Set,Promise,crypto:{randomUUID:()=>"test-job"},native:async(method,args={})=>{
    calls.push({method,args});
    if(method==="qoj_contest")return{id:cid,account,name:"CCPC Changchun - Dashboard - Contest - QOJ.ac",problems:[{id:"22910",label:"A"},{id:"22913",label:"D"}]};
    if(method==="list_sessions")return{sessions};
    if(method==="create_session"){const value={...args,sessionId:sid,state:"prepared",startAt:null};sessions.push(value);return value;}
    if(method==="resource_manifest")return{origin:"https://qoj.ac",account,contestId:cid,problems:[ready("22910")]};
    if(method==="prepare_resource"){prepareActive++;maximum=Math.max(maximum,prepareActive);await new Promise(setImmediate);prepareActive--;return ready(args.problemId);}
    throw Error("Forbidden or unexpected native action: "+method);
  },browser:{runtime:{id:"extension-test",getURL:name=>"moz-extension://resource-test/"+name},
    tabs:{get:async()=>({id:7,url:sender.url}),sendMessage:async(tabId,message)=>progress.push({tabId,message}),
      query:async()=>[{id:9,url:"moz-extension://resource-test/ui.html"}],
      update:async(id,args)=>{opened.push({id,...args});return{id};},create:async args=>{opened.push(args);return{id:10};}},
    storage:{local:{set:async()=>{}}}}};
  vm.createContext(context);
  vm.runInContext(background.slice(background.indexOf("  const resourcePreparationJobs"), background.indexOf("  async function ranklandTab(")),context);
  return {context,calls,progress,opened,sessions,get maximum(){return maximum;}};
}
const results=[];
async function check(name,run){await run();results.push(name);}

function contentEnvironment({recognized=true,url="https://qoj.ac/contest/4582"}={}) {
  let submits=0;const messages=[],listeners=[],observers=[];
  class Element {
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.style={};this.listeners={};this.textContent="";this.parentElement=null;this.type="";}
    get isConnected(){return this===body||!!this.parentElement?.isConnected;}
    getAttribute(name){return this.attributes[name]??null;}
    setAttribute(name,value){this.attributes[name]=value;}
    append(...items){for(const item of items){item.parentElement=this;this.children.push(item);}}
    after(item){const parent=this.parentElement;item.parentElement=parent;parent.children.splice(parent.children.indexOf(this)+1,0,item);}
    remove(){this.parentElement.children=this.parentElement.children.filter(item=>item!==this);this.parentElement=null;}
    addEventListener(type,listener){this.listeners[type]=listener;}
    submit(){submits++;}requestSubmit(){submits++;}
  }
  const body=new Element("body"),form=new Element("form"),nativeButton=new Element("button"),token=new Element("input");
  form.attributes={id:"form-regvir",method:"POST",action:"/contest/4582"};nativeButton.attributes={id:"button-submit-regvir",type:"submit",name:"submit-regvir"};nativeButton.type="submit";token.attributes={type:"hidden",name:"_token"};
  form.querySelector=selector=>selector.startsWith("input")?token:selector.startsWith("button")&&recognized?nativeButton:null;
  form.append(token,nativeButton);body.append(form);
  const walk=node=>[node,...node.children.flatMap(walk)];
  const original=JSON.stringify({form:form.attributes,button:nativeButton.attributes,token:token.attributes,childCount:form.children.length});
  const location=new URL(url);
  const context={URL,location,document:{body,createElement:tag=>new Element(tag),querySelector:selector=>selector==="form#form-regvir"?form:null,getElementById:id=>walk(body).find(node=>node.id===id)},
    MutationObserver:class{constructor(callback){observers.push(callback);}observe(){}},
    browser:{runtime:{id:"extension-test",onMessage:{addListener:listener=>listeners.push(listener)},sendMessage:async message=>{
      messages.push(message);
      if(message.type==="vp.resources.prepareContest"){
        listeners.forEach(listener=>listener({type:"vp.resources.progress",cid,jobId:"test-job",sessionId:sid,done:1,total:2,ready:1,unknown:0},{id:"extension-test"}));
        return{ok:true,result:{jobId:"test-job",cid,sessionId:sid,done:2,total:2,ready:2,unknown:0}};
      }
      return{ok:true,result:{sessionId:sid}};
    }}}};
  context.window=context;context.top=context;vm.createContext(context);vm.runInContext(content,context);
  return{body,form,nativeButton,token,messages,observers,get submits(){return submits;},original,
    snapshot:()=>JSON.stringify({form:form.attributes,button:nativeButton.attributes,token:token.attributes,childCount:form.children.length})};
}
(async()=>{
  await check("same-account/cid concurrent prepare coalesces and creates only prepared session",async()=>{
    const e=environment();const [first,second]=await Promise.all([e.context.prepareResourceContest({cid},sender),e.context.prepareResourceContest({cid},sender)]);
    assert.equal(first.sessionId,second.sessionId);assert.equal(e.calls.filter(call=>call.method==="create_session").length,1);
    assert.equal(e.calls.filter(call=>call.method==="prepare_resource").length,1);assert.equal(e.maximum,1);
    const created=e.calls.find(call=>call.method==="create_session").args;assert.equal(created.durationMs,18000000);assert.equal(created.startAt,undefined);
    assert.equal(first.ready,2);assert.equal(first.unknown,0);assert.equal(e.progress.at(-1).message.done,2);
  });
  await check("prepared session preferred; running timer never changed",async()=>{
    const running={sessionId:otherSid,contestId:cid,account,state:"running",startAt:12345};
    const prepared={sessionId:sid,contestId:cid,account,state:"prepared",startAt:null};const e=environment([running,prepared]);
    const result=await e.context.prepareResourceContest({cid},sender);assert.equal(result.sessionId,sid);
    assert.equal(e.calls.some(call=>["create_session","start_session","update_session"].includes(call.method)),false);
    assert.equal(e.sessions[0].startAt,12345);
  });
  await check("running-only session reuse preserves original start",async()=>{
    const e=environment([{sessionId:otherSid,contestId:cid,account,state:"running",startAt:12345}]);
    const result=await e.context.prepareResourceContest({cid},sender);assert.equal(result.sessionId,otherSid);assert.equal(e.sessions[0].startAt,12345);
    assert.equal(e.calls.some(call=>/start|update|create/.test(call.method)),false);
  });
  await check("sender origin/path/cid/frame mismatch never reaches native",async()=>{
    for(const changed of [{url:"https://elsewhere.invalid/contest/4582"},{url:"https://qoj.ac/contest/4582/problem/22913"},{frameId:1},{id:"other-extension"}]){
      const e=environment();await assert.rejects(e.context.prepareResourceContest({cid},{...sender,...changed}));assert.equal(e.calls.length,0);
    }
    const e=environment();await assert.rejects(e.context.prepareResourceContest({cid:"1051"},sender));assert.equal(e.calls.length,0);
  });
  await check("open files restores exact account-scoped session/resources URL",async()=>{
    const e=environment([{sessionId:sid,contestId:cid,account,state:"prepared",startAt:null}]);await e.context.openResourceContest({cid,sessionId:sid},sender);
    const target=new URL(e.opened[0].url);assert.equal(target.searchParams.get("session"),sid);assert.equal(target.searchParams.get("resources"),"1");
    assert.ok(e.calls.every(call=>["qoj_contest","list_sessions"].includes(call.method)));
    await assert.rejects(e.context.openResourceContest({cid,sessionId:otherSid},sender));
  });
  await check("actual workbench entry selects requested UUID before opening resource modal",async()=>{
    const ui=fs.readFileSync(path.join(root,"extension/ui.js"),"utf8");
    const begin=ui.indexOf("      const entry = new URLSearchParams(location.search)");
    const end=ui.indexOf("\n    } catch (error)",begin);let chosen,opened=0;
    const target={URLSearchParams,location:{search:"?session="+sid+"&resources=1"},state:{session:null},
      listSessions:async preferred=>{chosen=preferred;target.state.session={sessionId:preferred||otherSid};},openResources:async()=>opened++};
    vm.createContext(target);await vm.runInContext("(async()=>{"+ui.slice(begin,end)+"})()",target);
    assert.equal(chosen,sid);assert.equal(opened,1);
    target.location.search="?session=invalid&resources=1";opened=0;
    await vm.runInContext("(async()=>{"+ui.slice(begin,end)+"})()",target);assert.equal(chosen,undefined);assert.equal(opened,0);
  });
  await check("actual content button events keep native Start/form unchanged and submit zero",async()=>{
    const e=contentEnvironment();const panel=e.body.children.find(node=>node.id==="qoj-vp-resource-preparation");assert.ok(panel);
    assert.equal(panel.parentElement,e.form.parentElement);assert.equal(e.form.children.length,2);
    for(const observer of e.observers)observer();assert.equal(e.body.children.filter(node=>node.id===panel.id).length,1);
    const [prepare,open]=panel.children;assert.equal(prepare.type,"button");assert.equal(open.type,"button");
    const event=()=>({preventDefault(){},stopPropagation(){}});
    await prepare.listeners.click(event());await open.listeners.click(event());
    assert.deepEqual(e.messages.map(message=>message.type),["vp.resources.prepareContest","vp.resources.openContest"]);
    assert.equal(e.messages[1].sessionId,sid);assert.equal(e.submits,0);assert.equal(e.snapshot(),e.original);assert.equal(e.nativeButton.disabled,undefined);
  });
  await check("unknown form and non-contest pages receive no panel",async()=>{
    for(const options of [{recognized:false},{url:"https://qoj.ac/contest/4582/problem/22913"},{url:"https://elsewhere.invalid/contest/4582"}]){
      const e=contentEnvironment(options);assert.equal(e.body.children.length,1);assert.equal(e.messages.length,0);assert.equal(e.submits,0);
    }
  });
  console.log(JSON.stringify({pass:true,count:results.length,cases:results}));
})().catch(error=>{console.error(error);process.exitCode=1;});
