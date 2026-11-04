"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),test=require("node:test");
const source=fs.readFileSync(require("node:path").join(__dirname,"../../src/firefox/ui.js"),"utf8");
const sid="00000000-0000-4000-8000-000000000001";
const rankland=`https://vp.xcpc.link/?contest=fixture&run=${sid}`;
function environment(initialUrl=null){
 const nodes=new Map(),calls=[],messages=[],snapshots=[];
 const session={sessionId:sid,contestId:"3387",account:"fixture",ranklandUrl:initialUrl};
 const state={session,sessions:[session],generation:1,scoreboardRequestSequence:0,scoreboardRequest:null,scoreboardSource:null};
 let handler=async()=>({source:"qoj",state:"unmatched",url:"https://qoj.ac/contest/3387/standings"});
 const context={state,URL,location:{hash:"#home"},route(){},$:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);},
  current:(id,generation)=>state.session?.sessionId===id&&state.generation===generation,
  call:async(method,args)=>{calls.push({method,args});return handler(method,args);},
  resetRanklandSnapshot:()=>snapshots.push("reset"),refreshBoard:async()=>snapshots.push("read"),adoptRanklandUrl:()=>{},
  showMessage:(_,text)=>messages.push(text),message:e=>e.message,
 };
 vm.createContext(context);
 for(const [begin,end] of [["  function epoch(","  function formatDate("],["  function renderRanklandSyncControls(","  function ranklandViewIdentity("],
  ["  function safeQojUrl(","  function problemUrl("],["  function ranklandViewIdentity(","  function validRanklandSnapshot("],
  ["  function scoreboardFallback(","  async function syncScoreboard("]])vm.runInContext(source.slice(source.indexOf(begin),source.indexOf(end)),context);
 return {context,state,calls,messages,snapshots,nodes,setHandler:value=>handler=value};
}
test("Scoreboard opens the local view even without an external source",async()=>{
 const e=environment();await e.context.openScoreboard();
 assert.equal(e.context.location.hash,"#scoreboard");assert.equal(e.calls.length,0);
 assert.equal(e.messages.length,0);assert.deepEqual(e.snapshots,["read"]);
});
test("a unique match adopts only the RankLand URL and preserves locally changed session lifecycle",async()=>{
 const e=environment();e.state.session.state="finished";e.state.session.finishedAt=12345;
 e.setHandler(async()=>({source:"rankland",state:"matched",url:rankland,session:{sessionId:sid,ranklandUrl:rankland,state:"running"}}));
 await e.context.resolveScoreboardSource();
 assert.equal(e.state.session.ranklandUrl,rankland);assert.equal(e.state.session.state,"finished");assert.equal(e.state.session.finishedAt,12345);
 assert.equal(e.state.sessions[0].ranklandUrl,rankland);assert.equal(e.nodes.get("scoreboard-source-status").textContent,"已自动匹配");
 assert.deepEqual(e.snapshots,["reset","read"]);
});
test("slow source detection does not overwrite a later manually configured RankLand URL",async()=>{
 const e=environment();let resolve;e.setHandler(()=>new Promise(done=>resolve=done));
 const pending=e.context.resolveScoreboardSource();e.state.session.ranklandUrl=rankland;
 resolve({source:"qoj",state:"unmatched",url:"https://qoj.ac/contest/3387"});await pending;
 assert.equal(e.state.session.ranklandUrl,rankland);assert.equal(e.state.scoreboardSource,null);assert.equal(e.messages.length,0);
});
test("existing RankLand configuration survives unmatched or unavailable detection",async()=>{
 const e=environment(rankland);await e.context.resolveScoreboardSource();assert.equal(e.state.session.ranklandUrl,rankland);
 e.setHandler(async()=>{throw Error("offline");});await e.context.resolveScoreboardSource(true);
 assert.equal(e.state.scoreboardSource.source,"rankland");assert.equal(e.state.scoreboardSource.state,"configured");assert.equal(e.messages.length,0);
});
test("a changed session cannot receive the previous contest source",async()=>{
 const e=environment();let resolve;e.setHandler(()=>new Promise(done=>resolve=done));
 const pending=e.context.resolveScoreboardSource();e.state.generation++;
 resolve({source:"rankland",state:"matched",url:rankland});await pending;assert.equal(e.state.session.ranklandUrl,null);

});
test("foreign QOJ fallback URLs are replaced by the known contest page",async()=>{
 const e=environment();e.setHandler(async()=>({source:"qoj",state:"unverified",url:"https://elsewhere.invalid/"}));
 await e.context.resolveScoreboardSource();assert.equal(e.state.scoreboardSource.url,"https://qoj.ac/contest/3387");
});
test("explicit scoreboard retry bypasses a cached temporary failure",async()=>{
 const e=environment();
 e.setHandler(async(_method,args)=>args.refresh===true?
  {source:"rankland",state:"matched",url:rankland}:
  {source:"qoj",state:"unavailable",url:"https://qoj.ac/contest/3387"});
 await e.context.resolveScoreboardSource();
 assert.equal(e.calls[0].args.refresh,undefined);assert.equal(e.state.scoreboardSource.source,"qoj");
 await e.context.resolveScoreboardSource(true);
 assert.equal(e.calls[1].args.refresh,true);assert.equal(e.state.scoreboardSource.source,"rankland");
 assert.equal(e.state.session.ranklandUrl,rankland);
});
