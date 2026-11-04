'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
function fixture() {
 const calls=[], callbacks=[], listeners={}, storage={}, refreshSessions=[];
 const listener={addListener() {}};
 const context={URL,Map,Set,Promise,Date,crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,
  VpTransport:{pause:async()=>{}},
  __native:(method,args)=>{calls.push({method,args});
    if(method==='settlement_sessions')return Promise.resolve({sessions:refreshSessions});
    return new Promise((resolve,reject)=>callbacks.push({resolve,reject}));},
  browser:{runtime:{id:'test',getURL:n=>'moz-extension://test/'+n,onMessage:listener,onInstalled:listener},
   action:{onClicked:listener},alarms:{create(){},onAlarm:{addListener:f=>listeners.alarm=f}},
   storage:{local:{get:async k=>({[k]:storage[k]}),set:async v=>Object.assign(storage,v)}}}};
 vm.createContext(context);
 for (const file of ['board/generated/engine.js','board/cache.js','board/service.js'])
  vm.runInContext(fs.readFileSync('extension/'+file,'utf8'),context);
 if (!context.VpScoreboardSources) context.VpScoreboardSources={};
  vm.runInContext(fs.readFileSync('extension/rankland-protocol.js','utf8'),context);
 vm.runInContext(fs.readFileSync('extension/qoj-lifecycle.js','utf8'),context);
 vm.runInContext(fs.readFileSync('extension/background.js','utf8').replace(/\}\)\(\);\s*$/,
  'native=globalThis.__native; exclusiveSync=async()=>({});globalThis.dispatch=dispatch;})();'),context);
 return {...context,calls,callbacks,listeners,storage,refreshSessions};
}
test('reloads coalesce provider reads while local session snapshot stays independent', async()=>{
 const f=fixture(),pending=[];
 for(let n=0;n<20;n++)pending.push(f.dispatch('qoj_contest',{sessionId:'same',contestId:'4569'}));
 assert.equal(f.calls.length,1);
 const local=f.dispatch('session_snapshot',{sessionId:'same'});
 assert.equal(f.calls.length,2);
 f.callbacks[1].resolve({session:{sessionId:'same'},contest:{id:'4569'},history:{submissions:[]}});
 assert.equal((await local).contest.id,'4569');
 f.callbacks[0].resolve({id:'4569'});await Promise.all(pending);
 const next=f.dispatch('qoj_contest',{sessionId:'same',contestId:'4569'});
 assert.equal(f.calls.length,3);f.callbacks[2].resolve({id:'4569'});await next;
});
test('same history refresh joins alarm, fresh tabs and repeated clicks, failed reads can retry', async()=>{
 const f=fixture();f.storage.sessions=[];
 f.refreshSessions.push({sessionId:'same',state:'finished',refreshRequired:true,ranklandUrl:'https://vp.xcpc.link/?contest=fixture&run=same'});
 const first=f.dispatch('qoj_submissions',{sessionId:'same',refresh:true});
 const alarm=f.listeners.alarm({name:'vp-refresh'});
 await new Promise(setImmediate);
 const second=f.dispatch('qoj_submissions',{refresh:true,sessionId:'same'});
 assert.equal(f.calls.filter(call=>call.method==='settlement_sessions').length,1,"alarm discovers work from the durable ledger");
 assert.equal(f.calls.filter(call=>call.method==='qoj_submissions').length,1,"alarm, repeated clicks and fresh UI contexts share one provider read");
 f.callbacks[0].resolve({submissions:[]});await Promise.all([first,alarm,second]);
 const failed=f.dispatch('qoj_submissions',{sessionId:'same',refresh:true});
 f.callbacks[1].reject(Error('temporary failure'));await assert.rejects(failed,/temporary/);
 const retry=f.dispatch('qoj_submissions',{sessionId:'same',refresh:true});
 assert.equal(f.calls.filter(call=>call.method==='qoj_submissions').length,3);f.callbacks[2].resolve({submissions:[]});await retry;
});
test('different sessions and cached history reads do not join a provider request',async()=>{
 const f=fixture();const jobs=[f.dispatch('qoj_submissions',{sessionId:'a',refresh:true}),f.dispatch('qoj_submissions',{sessionId:'b',refresh:true}),f.dispatch('qoj_submissions',{sessionId:'a',refresh:false})];
 assert.equal(f.calls.length,3);f.callbacks.forEach(x=>x.resolve({submissions:[]}));await Promise.all(jobs);
});
