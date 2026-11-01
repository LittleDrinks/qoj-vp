'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup({fixture=false,ranklandUrl=null}={}){
 const session={sessionId:'local-practice',account:'me',contestId:'4569',durationMs:18000000,ranklandUrl};
 const contest={id:'4569',title:'Dolgoprudny',problems:[{id:'23137',label:'L'}],scoreboardUrl:'https://qoj.ac/results/QOJ4569?mode=pc2'};
 const calls=[],tabs=[],cache={},matches=[];const listener={addListener(){}};
 const env={session,contest,calls,tabs,cache,matches,fixture,now:Date.now(),result:{source:'qoj',state:'unmatched',reason:'NO_MATCH'}};
 const context={URL,Map,Set,Date:class extends Date {static now(){return env.now;}},Promise,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto,
  VpScoreboardSources:{resolve:async(...a)=>{matches.push(a);return env.resolve?env.resolve(...a):env.result;}},
  VpTransport:{pause:async()=>{}},
  __native:async(method,args={})=>{calls.push({method,args});switch(method){
   case 'hello':return {fixture:env.fixture};
   case 'session_snapshot':return {session:{...session},contest:{...contest}};
   case 'qoj_contest':return {...contest};
   case 'inspect_session':return {...session};
   case 'list_sessions':return {sessions:[{...session}]};
   case 'update_session':if(session.ranklandUrl===args.expectedRanklandUrl && session.durationMs===args.expectedDurationMs)session.ranklandUrl=args.ranklandUrl+'&run=local-practice';return {...session};
   default:throw Error('Unexpected native '+method);
  }},browser:{runtime:{id:'test',getURL:n=>'moz-extension://test/'+n,onMessage:listener,onInstalled:listener},action:{onClicked:listener},alarms:{create(){},onAlarm:listener},
   tabs:{create:async o=>{tabs.push(o);return {id:5,...o};}},storage:{local:{get:async k=>({[k]:cache[k]}),set:async o=>Object.assign(cache,o)}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('extension/background.js','utf8').replace(/\}\)\(\);\s*$/,'native=globalThis.__native;globalThis.dispatch=dispatch;})();'),context);
 env.run=(method,args={})=>context.dispatch(method,{sessionId:session.sessionId,...args});return env;
}
test('unmatched Ucup opens the observed original QOJ board and persists discovery',async()=>{
 const f=setup();const first=await f.run('scoreboard.resolve');assert.equal(first.source,'qoj');assert.equal(first.url,f.contest.scoreboardUrl);
 assert.equal(f.tabs.length,0);await f.run('scoreboard.open');assert.equal(f.tabs[0].url,f.contest.scoreboardUrl);assert.equal(f.matches.length,1);
 assert.equal(f.calls.filter(c=>c.method==='update_session').length,0);
});
test('existing RankLand replay remains intact without catalogue requests',async()=>{
 const f=setup({ranklandUrl:'https://vp.xcpc.link/?contest=x&run=existing&from=.25'});
 assert.equal((await f.run('scoreboard.resolve')).url,f.session.ranklandUrl);assert.equal(f.matches.length,0);assert.equal(f.calls.length,1);
});
test('exact match saves a session-owned replay using compare-and-set',async()=>{
 const f=setup();f.result={source:'rankland',state:'matched',ranklandUrl:'https://vp.xcpc.link/?contest=verified'};
 const r=await f.run('scoreboard.resolve');assert.equal(r.source,'rankland');assert.match(r.url,/run=local-practice/);
 assert.equal(f.calls.find(c=>c.method==='update_session').args.expectedRanklandUrl,null);
});
test('manual edit wins against a slow automatic candidate',async()=>{
 const f=setup();f.resolve=async()=>{f.session.ranklandUrl='https://vp.xcpc.link/?contest=manual&run=local-practice';return {source:'rankland',state:'matched',ranklandUrl:'https://vp.xcpc.link/?contest=auto'};};
 const r=await f.run('scoreboard.resolve');assert.equal(r.url,f.session.ranklandUrl);assert.match(r.url,/manual/);
});
test('fixture profiles resolve locally, and unsafe fallback links cannot open',async()=>{
 const f=setup({fixture:true});f.contest.scoreboardUrl='https://qoj.ac/results/QOJ99?mode=pc2';
 const r=await f.run('scoreboard.open');assert.equal(r.url,'https://qoj.ac/contest/4569');assert.equal(f.matches.length,0);assert.equal(f.tabs.length,0);assert.equal(r.opened,false);
});
test('concurrent page reload discoveries share one match task',async()=>{
 const f=setup();let finish;f.resolve=()=>new Promise(resolve=>{finish=resolve;});
 const reads=Array.from({length:20},()=>f.run('scoreboard.resolve'));
 await new Promise(setImmediate);assert.equal(f.matches.length,1);finish(f.result);await Promise.all(reads);
});

test('duration edits invalidate a slow automatic match before saving',async()=>{
 const f=setup();f.resolve=async()=>{f.session.durationMs=14400000;return {source:'rankland',state:'matched',ranklandUrl:'https://vp.xcpc.link/?contest=auto'};};
 const r=await f.run('scoreboard.resolve');assert.equal(f.session.ranklandUrl,null);assert.equal(r.source,'qoj');assert.equal(r.reason,'SESSION_CHANGED');
});
test('temporary detail failure retries after 30 seconds and explicit refresh bypasses cache',async()=>{
 const f=setup();f.result={source:'qoj',state:'unverified',reason:'INCOMPLETE_VERIFICATION'};
 await f.run('scoreboard.resolve');f.now+=61000;await f.run('scoreboard.resolve');assert.equal(f.matches.length,2);
 await f.run('scoreboard.resolve',{refresh:true});assert.equal(f.matches.length,3);
});
test('a changed CLI contest name invalidates the negative match cache',async()=>{
 const f=setup();f.contest.name='Old title';await f.run('scoreboard.resolve');f.contest.name='New title';await f.run('scoreboard.resolve');assert.equal(f.matches.length,2);
});
