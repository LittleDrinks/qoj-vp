"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../../src/firefox/ui.js"),"utf8");
const nodes={"history-warning":{hidden:true},"history-time-status":{hidden:true}},context={
 $:id=>nodes[id], showMessage:(target,text,kind)=>Object.assign(target,{hidden:false,textContent:text,kind}),
 hideMessage:target=>Object.assign(target,{hidden:true,textContent:""})};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf("  function historyCoverageMessage("),source.indexOf("  function renderProblems(")),context);
const records=Array.from({length:13},(_,index)=>({id:String(index+1),timeSource:"unverified-display"}));
const warning=records.map(item=>"#"+item.id+": absolute submission time is not verified").join("; ");
const before=JSON.stringify(records), stable=[];
for(const remaining of [13,9,6,3]){
 context.renderHistoryCoverage({complete:false,warning},records.slice(0,remaining));
 assert.equal(nodes["history-warning"].hidden,true,"time backfill alone must not show a yellow error banner");
 assert.equal(nodes["history-time-status"].hidden,false);
 assert.match(nodes["history-time-status"].textContent,/暂不计入/);
 assert.doesNotMatch(nodes["history-time-status"].textContent,/\d|#|absolute/);
 stable.push(nodes["history-time-status"].textContent);
}
assert.equal(new Set(stable).size,1,"display text must stay stable as the time backfill progresses");
assert.equal(JSON.stringify(records),before,"presentation must not rewrite verification facts");
context.renderHistoryCoverage({complete:false,warning:"History exceeded ten pages; earlier submissions remain unverified"},records);
assert.equal(nodes["history-warning"].hidden,false);assert.match(nodes["history-warning"].textContent,/历史未读完/);
context.renderHistoryCoverage({complete:false,warning:"#2: detailed verdict unavailable; refresh to retry"},records);
assert.equal(nodes["history-warning"].hidden,false);assert.match(nodes["history-warning"].textContent,/判定未核实/);
context.renderHistoryCoverage({complete:false,warning:"unexpected provider format"},records);
assert.equal(nodes["history-warning"].hidden,false);assert.match(nodes["history-warning"].textContent,/未确认项/);
context.renderHistoryCoverage({complete:true},[]);
assert.equal(nodes["history-warning"].hidden,true);assert.equal(nodes["history-time-status"].hidden,true);assert.equal(nodes["history-time-status"].textContent,"");
context.renderHistoryCoverage({complete:false},[]);
assert.equal(nodes["history-warning"].hidden,false);assert.match(nodes["history-warning"].textContent,/历史尚未核实/);
console.log(JSON.stringify({pass:true,count:6,cases:["time backfill uses a stable non-warning note","partial reads remain explicit","verdict gaps stay visible","unknown provider errors remain visible","complete history clears the note","unexplained incompleteness remains a warning"]}));
