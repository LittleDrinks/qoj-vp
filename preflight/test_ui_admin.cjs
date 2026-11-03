"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm"), test = require("node:test");
const source = fs.readFileSync(require("node:path").join(__dirname, "../extension/ui.js"), "utf8");
function environment() {
  const nodes = new Map(), calls = [], notices = [], hidden = [], removed = [];
  const $ = id => { if (!nodes.has(id)) nodes.set(id, {id, value:"", checked:false, hidden:false, disabled:false, files:[], style:{}, setAttribute(){}, classList:{contains:()=>false}, reset(){}}); return nodes.get(id); };
  const session = {sessionId:"first", state:"prepared", durationMs:18000000, title:"Fixture", account:"fixture"};
  const state = {connected:true, session, sessions:[session], generation:1, adminBusy:false, submitting:false, intents:[{sessionId:"first"},{sessionId:"keep"}], resources:new Map(), resourceMutation:0, manualProblem:"123", manualSessionId:"first"};
  let handler = async () => {throw new Error("unexpected task");};
  const context = {$, state, TextEncoder, Uint8Array, btoa, Date, location:{hash:"#jury/contest/first"},
    MAX_MANUAL_BYTES:8388608, MAX_MANUAL_FILE_BYTES:4194304, ACTIVE_KEY:"vpUiActiveSession", INTENTS_KEY:"vpUiSubmissionIntents",
    isJuryRoute:()=>context.location.hash.startsWith("#jury"), current:(sid,gen)=>state.session?.sessionId===sid&&state.generation===gen,
    hideMessage:()=>{}, showMessage:(target,text)=>notices.push([target.id,text]), message:error=>error.message,
    call:async(method,args)=>{calls.push({method,args}); return handler(method,args);},
    resourceDescriptors:entry=>entry?.downloads||[], renderProblems:()=>{}, renderResourceModal:()=>{}, renderNavigation:()=>{}, renderSession:()=>{}, renderSummary:()=>{},
    confirm:()=>true, fail:error=>{throw error;}, submitAvailability:()=>{}, document:{querySelectorAll:()=>[]},
    modals:{"manual-samples":{hide:()=>hidden.push("manual")},"delete-contest":{hide:()=>hidden.push("delete"),show:()=>{}}},
    persistIntents:async()=>{}, localGet:async()=>"first", browser:{storage:{local:{remove:async key=>removed.push(key)}}},
    listSessions:async()=>{}, route:()=>{}, rememberDisplayIndex:()=>{},
  };
  vm.createContext(context);
  for(const [start,end] of [["  function preserveNativeStart(","  function displayJson("],["  function epoch(","  function submitAvailability("],["  function renderClock(","  function renderSession("],["  async function saveJuryConfig(","  // File-size/time formatting"]])
    vm.runInContext(source.slice(source.indexOf(start),source.indexOf(end)),context);
  $("manual-samples-mode").value="text"; $("manual-sample-input").value="2 3\n"; $("manual-sample-output").value="5\n"; $("manual-samples-replace-group").hidden=true;
  return {context,state,$,calls,notices,hidden,removed,setHandler:value=>handler=value};
}
const event={preventDefault(){}};
const file=(name,bytes)=>({name,size:bytes.length,arrayBuffer:async()=>Uint8Array.from(bytes).buffer});

test("pasted samples preserve whitespace and Unicode bytes including an empty expected output",async()=>{
 const view=environment(); view.$("manual-sample-input").value="  中文\n\n"; view.$("manual-sample-output").value="";
 const payload=await view.context.manualSamplesPayload();
 assert.deepEqual(Array.from(payload.files,item=>item.name),["1.in","1.ans"]);
 assert.equal(Buffer.from(payload.files[0].base64,"base64").toString(),"  中文\n\n"); assert.equal(payload.files[1].base64,"");
});
test("ZIP and paired uploads preserve bytes; invalid type or excessive bytes never reach the helper",async()=>{
 const view=environment(); view.$("manual-samples-mode").value="files";
 view.$("manual-samples-files").files=[file("samples.zip",Buffer.from([80,75,0,255]))];
 assert.equal((await view.context.manualSamplesPayload()).zipBase64,"UEsA/w==");
 view.$("manual-samples-files").files=[file("case.in",Buffer.from("1\r\n")),file("case.out",Buffer.from("2\n"))];
 const payload=await view.context.manualSamplesPayload(); assert.equal(Buffer.from(payload.files[0].base64,"base64").toString(),"1\r\n");
 view.$("manual-samples-files").files=[file("main.cpp",Buffer.from("ignored"))]; await assert.rejects(view.context.manualSamplesPayload(),/ZIP/);
 view.$("manual-samples-files").files=[{name:"x.zip",size:8388609,arrayBuffer:()=>{throw Error("should not read");}}]; await assert.rejects(view.context.manualSamplesPayload(),/8 MiB/);
 assert.equal(view.calls.length,0);
});
test("team route cannot import and existing samples require explicit replacement",async()=>{
 const view=environment(); view.context.location.hash="#problems"; await view.context.importManualSamples(event); assert.equal(view.calls.length,0);
 view.context.location.hash="#jury"; view.$("manual-samples-replace-group").hidden=false; await view.context.importManualSamples(event); assert.equal(view.calls.length,0); assert.match(view.notices.at(-1)[1],/替换/);
});
test("successful manual import updates only the selected problem and preserves the returned attachment",async()=>{
 const view=environment(), attachment={kind:"attachment",resourceId:"retained"};
 view.$("manual-samples-replace-group").hidden=false; view.$("manual-samples-replace").checked=true;
 const result={problemId:"123",status:"ready",downloads:[{kind:"samples",sampleSource:"manual"},attachment]};
 view.setHandler(async()=>result); await view.context.importManualSamples(event);
 assert.equal(view.calls[0].method,"import_samples"); assert.equal(view.calls[0].args.confirmedReplace,true);
 assert.equal(view.state.resources.get("123"),result); assert.equal(view.state.resources.get("123").downloads[1],attachment);
 assert.deepEqual(view.hidden,["manual"]); assert.equal(view.state.manualBusy,false);
});
test("a failed import retains old resources and a stale response cannot modify another selected contest",async()=>{
 const view=environment(), old={problemId:"123",status:"ready"}; view.state.resources.set("123",old);
 view.setHandler(async()=>{throw Error("unpaired files");}); await view.context.importManualSamples(event);
 assert.equal(view.state.resources.get("123"),old); assert.equal(view.hidden.length,0); assert.match(view.notices.at(-1)[1],/unpaired/);
 let release; view.setHandler(()=>new Promise(done=>release=done)); const pending=view.context.importManualSamples(event);
 await new Promise(setImmediate); view.state.session={sessionId:"second"}; view.state.generation++;
 release({problemId:"123",downloads:[{kind:"samples",sampleSource:"manual"}]}); await pending;
 assert.equal(view.state.resources.get("123"),old); assert.equal(view.hidden.length,0);
});
test("deletion requires confirmation and removes only matching local intent and active-session state",async()=>{
 const view=environment(); view.state.deleteSessionId="first";
 await view.context.deleteSession(event); assert.equal(view.calls.length,0);
 view.$("delete-contest-confirm").checked=true; view.setHandler(async()=>({deleted:true,sessionId:"first"})); await view.context.deleteSession(event);
 assert.deepEqual(view.calls.map(item=>[item.method,item.args.sessionId,item.args.confirmed]),[["delete_session","first",true]]);
 assert.deepEqual(view.state.intents.map(item=>item.sessionId),["keep"]); assert.equal(view.state.session,null);
 assert.equal(view.state.sessions.length,0); assert.deepEqual(view.removed,["vpUiActiveSession"]); assert.equal(view.context.location.hash,"#jury");
});
test("early finish keeps the clock frozen and disables further submission",()=>{
 const view=environment(), start=Date.now()-120000;
 view.state.session={...view.state.session,state:"finished",startAt:start,finishedAt:start+60000,durationMs:3600000};
 view.context.renderClock(); assert.equal(view.context.sessionState(),"finished"); assert.equal(view.$("timeleft").textContent,"contest ended");
 assert.equal(view.$("contest-progress").style.width,(60000/3600000*100)+"%");
 assert.equal(view.$("finish-session").hidden,true); assert.equal(view.$("delete-session").disabled,false);
});
test("configuration saves re-enable prepared fields and cannot edit a running contest",async()=>{
 const view=environment(); view.$("jury-title-input").value="Renamed"; view.$("jury-duration-input").value="90";
 view.setHandler(async(method,args)=>({...view.state.session,title:args.title,durationMs:args.durationMs})); await view.context.saveJuryConfig(event);
 assert.equal(view.state.session.title,"Renamed"); assert.equal(view.state.session.durationMs,5400000);
 for(const id of ["jury-title-input","jury-duration-input","jury-config-save"]) assert.equal(view.$(id).disabled,false);
 view.state.session.state="running"; view.state.session.startAt=Date.now(); await view.context.saveJuryConfig(event); assert.equal(view.calls.length,1);
});


test("a concurrent import exposes replacement consent without discarding entered data", async()=>{
 const view=environment(); view.setHandler(async()=>{const error=new Error("existing samples");error.code="CONFIRMATION_REQUIRED";throw error;});
 await view.context.importManualSamples(event);
 assert.equal(view.$("manual-samples-replace-group").hidden,false);
 assert.equal(view.$("manual-samples-replace").checked,false);
 assert.equal(view.$("manual-sample-input").value,"2 3\n");
 assert.equal(view.hidden.length,0); assert.equal(view.state.manualBusy,false);
 assert.match(view.notices.at(-1)[1],/勾选/);
});
