'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const p=require('../extension/rankland-protocol.js');
const base='https://vp.xcpc.link/?contest=ccpc2026ladies&at=2026-11-04T00%3A00%3A00Z&play=1&from=0&speed=1';
test('clock uses QOJ start once, including a late two-hour open and end clamp',()=>{
 const now=Date.parse('2026-11-04T02:00:00.123Z');
 assert.deepEqual(p.clock(base,18000000,now),{elapsed:7200123,running:true,speed:1});
 assert.equal(p.clock(base,18000000,now+18000000).elapsed,18000000);
 assert.equal(p.clock(base,18000000,now+18000000).running,false);
});
test('pause and speed anchors change playback without changing submission identity',()=>{
 const paused=base.replace('from=0','from=32.5').replace('play=1','play=0')+'&anchor=2026-11-04T01%3A00%3A00Z';
 assert.equal(p.identity(paused),p.identity(base));
 assert.equal(p.clock(paused,18000000,Date.parse('2026-11-04T02:00:00Z')).elapsed,1950000);
 const resumed=paused.replace('play=0','play=1').replace('speed=1','speed=2');
 assert.equal(p.clock(resumed,18000000,Date.parse('2026-11-04T01:01:00Z')).elapsed,2070000);
});
test('same instant in a different timezone and obsolete UUID retain one identity and store',()=>{
 const other=base.replace('2026-11-04T00%3A00%3A00Z','2026-11-04T08%3A00%3A00%2B08%3A00')+'&run=old&team=Test';
 assert.equal(p.identity(other),p.identity(base));
 assert.equal(p.archiveKey(other),p.archiveKey(base));
 assert.notEqual(p.identity(base+'&ratio=30'),p.identity(base));
});
test('empty modern storage requires explicit capability approval and unknown records are refused',()=>{
 const storage={getItem:()=>null};
 assert.throws(()=>p.read(storage,base),{code:'RANKLAND_SCHEMA_CHANGED'});
 assert.deepEqual(p.read(storage,base,{allowEmpty:true}).value.manual,[]);
 for(const record of [{problemIndex:0,timeMs:10,result:'new-result'},{problemIndex:0,timeMs:-1,result:'AC'}, {problemIndex:12,timeMs:10,result:'AC'}]){
  assert.throws(()=>p.decode(JSON.stringify([record]),'submissions',base,{problemCount:12,durationMs:18000000}),{code:'RANKLAND_SCHEMA_CHANGED'});
 }
});
test('private old archive is retained when reading a legacy page, never rewritten in place',()=>{
 const oldUrl=base+'&run=old',key=p.legacyKey(oldUrl);
 const archive={version:2,elapsed:123,savedAt:12345,running:false,speed:1,ownName:'Old',manual:[]};
 const state=p.read({getItem:k=>k===key?JSON.stringify(archive):null},oldUrl);
 assert.equal(state.kind,'v2');assert.equal(state.key,key);
 assert.deepEqual(JSON.parse(p.encode(state,[{problemIndex:0,timeMs:100,result:'WA'}])),{...archive,manual:[{problemIndex:0,timeMs:100,result:'WA'}]});
});
