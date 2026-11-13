'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={URL,console};vm.createContext(context);
for(const file of ['board/generated/engine.js','board/service.js']) vm.runInContext(fs.readFileSync('src/firefox/'+file,'utf8'),context);
const engine=context.VpBoardEngine;
const duration=18000000;
test('QOJ Changchun rounds each accepted problem before summing the reported 776 minute penalty',()=>{
 const labels='ABCDEFGHIJKLM'.split('');
 const i=input();i.contest.problems=labels.map((label,index)=>({id:String(index+1),label}));
 const acs={A:[0,23,30],C:[1,1,51],J:[0,14,14],K:[1,35,13],G:[3,50,23],M:[3,15,8],E:[2,18,29]};
 const ms=([h,m,s])=>((h*60+m)*60+s)*1000;
 i.history.submissions=Object.entries(acs).map(([label,time],index)=>submission(index+1,ms(time),'CORRECT',{problemId:String(labels.indexOf(label)+1)}));
 i.history.submissions.push(submission(20,ms([2,9,42]),'WRONG-ANSWER',{problemId:'5'}),
  submission(21,ms([0,23,30]),'COMPILER-ERROR',{problemId:'5'}),
  submission(22,ms([3,0,37]),'RUN-ERROR',{problemId:'5'}));
 const a=archive();a.problems=labels.map(alias=>({alias}));a.rows=[];
 a.sorter.config.timePrecision='s';
 const original=JSON.stringify(i.history);
 const result=engine.project(i,a);
 assert.equal(result.own.score,7);assert.equal(result.own.penaltyMinutes,776);
 assert.equal(JSON.stringify(i.history),original,'Scoring must not rewrite original submission timestamps');
});
function input(records=[]) {return {session:{sessionId:'practice',contestId:'1',account:'me',startAt:1000000,
 durationMs:duration,elapsedMs:duration,state:'finished'},contest:{problems:[{id:'1',label:'A'},{id:'2',label:'B'}]},history:{submissions:records}};}
function submission(id,elapsedMs,verdict='CORRECT',extra={}) {return {id:String(id),problemId:'1',state:'confirmed',inSession:true,elapsedMs,verdict,pending:false,timeSource:'provider-absolute',...extra};}
function archive() {return {version:'0.3.14',type:'general',contest:{title:'test',startAt:'2020-01-01T00:00:00Z',duration:[5,'h'],frozenDuration:[1,'h']},
 problems:[{alias:'A'},{alias:'B'}],series:[{title:'Rank',rule:{preset:'Normal'}}],sorter:{algorithm:'ICPC',config:{penalty:[20,'min'],timePrecision:'min'}},
 rows:[{user:{id:'opponent',name:'Opponent'},score:{value:1,time:[30,'min']},statuses:[{result:'AC',tries:1,time:[30,'min'],solutions:[{result:'AC',time:[30,'min']}]},{solutions:[]}]}]};}
test('Jinan untouched cells with zero time and no solutions remain valid empty history',()=>{
 const a=archive();a.rows[0].statuses[1]={result:null,time:[0,'s'],tries:0};
 const b=engine.project(input(),a);
 assert.equal(b.scope,'historical');assert.equal(b.ranklist.rows.find(r=>r.user.name==='Opponent').score.value,1);
 for(const change of [{tries:1},{result:'AC'},{time:[1,'s']}]) {
  const invalid=structuredClone(a);Object.assign(invalid.rows[0].statuses[1],change);
  assert.throws(()=>engine.project(input(),invalid),/BOARD_HISTORY_INCOMPLETE/);
 }
});
test('delayed AC scores the original minute; rejudge replaces the submission without duplication',()=>{
 const i=input([submission(1,20*60000)]);i.session.elapsedMs=25*60000;
 let result=engine.project(i,archive());assert.equal(result.own.penaltyMinutes,20);assert.equal(result.own.rank,1);
 i.history.submissions[0].verdict='WRONG-ANSWER';result=engine.project(i,archive());assert.equal(result.own.score,0);
 assert.equal(result.own.progress[0].judged,1);
});
test('late earlier WA recalculates penalty without hiding a confirmed AC; pending is never a wrong try',()=>{
 const i=input([submission(1,10*60000,'JUDGING',{pending:true}),submission(2,20*60000)]);
 let b=engine.project(i);assert.equal(b.own.score,1);assert.equal(b.own.penaltyMinutes,20);assert.equal(b.provisional,true);
 i.history.submissions[0].pending=false;i.history.submissions[0].verdict='WRONG-ANSWER';
 b=engine.project(i);assert.equal(b.own.penaltyMinutes,40);assert.equal(b.own.progress[0].judged,2);
});
test('receipt ambiguity, local intent times, before/after-window facts and foreign problems do not invent scores',()=>{
 const i=input([submission(1,-1),submission(2,duration),submission(3,100,{},{state:'unknown',operationId:'x'}),
 submission(4,60000,'CORRECT',{timeSource:'local-intent'}),submission(5,60000,'CORRECT',{inSession:false})]);
 assert.equal(engine.project(i).own.score,0);
 assert.throws(()=>engine.project(input([submission(6,1,'CORRECT',{problemId:'999'})])),/MAPPING/);
});
test('duplicate delivery does not merge distinct submissions sharing problem/time/verdict',()=>{
 const i=input([submission(1,60000,'WRONG-ANSWER'),submission(2,60000,'WRONG-ANSWER'),submission(3,120000)]);
 assert.equal(engine.project(i).own.penaltyMinutes,42);
 i.history.submissions.push(submission(3,120000));assert.throws(()=>engine.project(i),/DUPLICATE/);
});
test('compile errors are excluded and an explicit early finish defines the scoring window',()=>{
 const i=input([submission(1,60000,'COMPILER-ERROR'),submission(2,120000),submission(3,240000,'CORRECT',{problemId:'2'})]);
 i.session.finishedAt=i.session.startAt+180000;
 const b=engine.project(i);assert.equal(b.own.score,1);assert.equal(b.own.penaltyMinutes,2);
});
test('full board and self summary use the same score, penalty, rank and problem statuses',()=>{
 const b=engine.project(input([submission(1,40*60000)]),archive());
 const me=b.ranklist.rows.find(row=>row.user.name==='me');
 assert.equal(b.own.rank,2);assert.equal(me.score.value,b.own.score);
 assert.equal(me.score.time[0]/60000,b.own.penaltyMinutes);assert.equal(me.rankValues[0].rank,b.own.rank);
});
test('freeze masks opponents but not own submissions; final replay reveals opponents',()=>{
 const a=archive();a.rows[0].statuses[1]={solutions:[{result:'AC',time:[250,'min']}]};
 const i=input([submission(1,245*60000)]);i.session.elapsedMs=260*60000;
 let b=engine.project(i,a);assert.equal(b.ranklist.rows.find(r=>r.user.name==='Opponent').score.value,1);assert.equal(b.own.score,1);
 i.session.elapsedMs=duration;b=engine.project(i,a);assert.equal(b.ranklist.rows.find(r=>r.user.name==='Opponent').score.value,2);
});
test('replay is pure; moving backwards excludes future submissions without changing input',()=>{
 const i=input([submission(1,40*60000)]),a=archive(),before=JSON.stringify([i,a]);
 assert.equal(engine.project(i,a,20*60000).own.score,0);
 assert.equal(engine.project(i,a,50*60000).own.score,1);assert.equal(JSON.stringify([i,a]),before);
 a.contest.startAt='2024-11-03T09:00:00+08:00';const projected=engine.project(i,a,50*60000);
 assert.ok(projected.ranklist.contest.startAt.endsWith('+08:00'));
 assert.equal(Date.parse(projected.ranklist.contest.startAt),i.session.startAt);
});
test('running projections cannot reveal future or final history, including through the service',async()=>{
 const i=input(),a=archive();Object.assign(i.session,{state:'running',elapsedMs:20*60000});
 a.rows[0].statuses[1]={solutions:[{result:'AC',time:[250,'min']}]};
 const before=JSON.stringify(i);
 const future=engine.project(i,a,duration);
 assert.equal(future.elapsedMs,20*60000);
 assert.equal(future.ranklist.rows.find(r=>r.user.name==='Opponent').score.value,0);
 i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';
 const board=context.VpBoard.create({readSnapshot:async()=>i,engine,cache:{get:async()=>({archive:a}),set:async()=>{}},sources:{}});
 assert.equal((await board.snapshot('practice',{elapsedMs:duration})).elapsedMs,20*60000);
 delete i.session.ranklandUrl;assert.equal(JSON.stringify(i),before);
});
test('prepared projections remain at zero even when a final instant is requested',()=>{
 const i=input();Object.assign(i.session,{state:'prepared',startAt:null,elapsedMs:0});
 assert.equal(engine.project(i,archive(),duration).elapsedMs,0);
});
test('early finish keeps own scoring cutoff but permits full historical replay',()=>{
 const i=input([submission(1,10*60000),submission(2,40*60000,'CORRECT',{problemId:'2'})]),a=archive();
 Object.assign(i.session,{finishedAt:i.session.startAt+20*60000,elapsedMs:20*60000});
 a.rows[0].statuses[1]={solutions:[{result:'AC',time:[250,'min']}]};
 const live=engine.project(i,a),final=engine.project(i,a,duration);
 assert.equal(live.elapsedMs,20*60000);
 assert.equal(final.elapsedMs,duration);assert.equal(final.own.score,1);
 assert.equal(final.ranklist.rows.find(r=>r.user.name==='Opponent').score.value,2);
});
test('summarized-only history, mismatched duration/problem links and unknown algorithms fail explicitly',()=>{
 const i=input(),a=archive();delete a.rows[0].statuses[0].solutions;
 assert.throws(()=>engine.project(i,a),/HISTORY_INCOMPLETE/);
 a.rows=[];a.contest.duration=[4,'h'];assert.throws(()=>engine.project(i,a),/CONTEST_MISMATCH/);
 a.contest.duration=[5,'h'];a.problems[0].link='https://qoj.ac/problem/999';assert.throws(()=>engine.project(i,a),/MAPPING/);
 delete a.problems[0].link;a.sorter.config.extendedAlgorithms=[{algorithm:'Other'}];assert.throws(()=>engine.project(i,a),/UNSUPPORTED_BOARD_RULE/);
});
test('explicit rules override archive defaults while auto preserves CCPC26',()=>{
 const i=input(),a=archive();a.sorter.config.extendedAlgorithms=[{algorithm:'CCPC26',config:{problemRevealAcceptedThreshold:{count:3}}}];
 assert.equal(engine.project(i,a).ranklist.sorter.config.extendedAlgorithms[0].algorithm,'CCPC26');
 i.session.board={rule:'ICPC'};assert.equal(engine.project(i,a).ranklist.sorter.config.extendedAlgorithms,undefined);
 i.session.board={rule:'CCPC26',revealCount:7,revealRatio:25};
 assert.equal(engine.project(i,a).ranklist.sorter.config.extendedAlgorithms[0].config.problemRevealAcceptedThreshold.ratio,.25);
 i.session.board={rule:'CCPC26',revealCount:0,revealRatio:0};assert.throws(()=>engine.project(i,a),/INVALID_BOARD_RULE/);
});
test('data adapter cache survives service restart; no external tab or source fetch is needed to score',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';
 const saved=new Map();let reads=0;const cache={get:async k=>saved.get(k),set:async(k,v)=>saved.set(k,v)};
 const options={readSnapshot:async()=>i,cache,engine,sources:{loadArchive:async()=>{reads++;return {archive:archive(),hash:'hash',contestKey:'fixture'};}}};
 let board=context.VpBoard.create(options);const results=await Promise.all(Array.from({length:20},()=>board.snapshot('practice')));
 assert.equal(reads,1);assert.ok(results.every(r=>r.own.rank===1));
 board=context.VpBoard.create({...options,sources:{loadArchive:async()=>{throw Error('offline');}}});
 assert.equal((await board.snapshot('practice')).own.rank,1);
 assert.equal((await board.snapshot('practice',{refresh:true})).own.rank,1);
});
test('preparing a new board downloads and persists it before use, preserving the active contest',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=old';
 const before=JSON.stringify(i),saved=new Map();let downloads=0;
 const options={readSnapshot:async()=>i,engine,cache:{get:async k=>saved.get(k),set:async(k,v)=>saved.set(k,v)},
  sources:{loadArchive:async()=>{downloads++;return {archive:archive(),contestKey:'new',fetchedAt:1234};}}};
 const service=context.VpBoard.create(options);
 const preview=await service.prepare('practice',{url:'https://rl.algoux.cn/ranklist/new',board:{rule:'ICPC'}});
 assert.equal(preview.teams,1);assert.equal(preview.problems,2);assert.equal(preview.submissions,1);
 assert.equal(preview.stored,true);assert.equal(downloads,1);assert.equal(JSON.stringify(i),before);
 i.session.ranklandUrl='https://vp.xcpc.link/?contest=new';
 const restarted=context.VpBoard.create({...options,sources:{loadArchive:async()=>{throw Error('offline');}}});
 const result=await restarted.snapshot('practice');assert.equal(result.scope,'historical');assert.equal(result.stored,true);
 assert.equal(result.own.score,1);assert.equal(result.own.penaltyMinutes,1);
});
test('failed downloads or storage cannot confirm a new board or replace the current data',async()=>{
 const i=input();i.session.ranklandUrl='https://vp.xcpc.link/?contest=old';
 for(const fault of ['download','storage']) {
  const service=context.VpBoard.create({readSnapshot:async()=>i,engine,cache:{get:async()=>null,set:async()=>{throw Error('disk full');}},
   sources:{loadArchive:async()=>{if(fault==='download')throw Error('offline');return {archive:archive(),contestKey:'new'};}}});
  await assert.rejects(service.prepare('practice',{url:'https://vp.xcpc.link/?contest=new'}),fault==='download'?/offline/:/BOARD_CACHE_FAILED/);
  const result=await service.snapshot('practice');assert.equal(result.scope,'self');assert.equal(result.stored,false);
 }
});
test('a mismatched replacement leaves the last downloaded board usable offline',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';
 const saved=new Map(),original=JSON.stringify(i);let broken=false;
 const service=context.VpBoard.create({readSnapshot:async()=>i,engine,
  cache:{get:async k=>saved.get(k),set:async(k,v)=>saved.set(k,v)},sources:{loadArchive:async()=>{
   const a=archive();if(broken)a.problems[0].alias='C';return {archive:a,contestKey:'fixture'};
  }}});
 await service.prepare('practice',{url:i.session.ranklandUrl});broken=true;
 await assert.rejects(service.prepare('practice',{url:i.session.ranklandUrl}),/MAPPING_MISMATCH/);
 const current=await service.snapshot('practice');
 assert.equal(current.scope,'historical');assert.equal(current.own.score,1);assert.equal(current.own.penaltyMinutes,1);
 assert.equal(current.ranklist.problems[0].alias,'A');assert.equal(JSON.stringify(i),original);
});
test('unavailable source degrades to own score and is backed off; cached invalid source cannot supply a rank',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';let reads=0;
 const board=context.VpBoard.create({readSnapshot:async()=>i,engine,cache:{get:async()=>null,set:async()=>{}},clock:()=>10000,
 sources:{loadArchive:async()=>{reads++;throw Error('offline');}}});
 const b=await board.snapshot('practice');assert.equal(b.own.rank,null);assert.equal(b.own.score,1);
 await board.snapshot('practice');assert.equal(reads,1);
});
test('event scheduling and explicit projections preserve multi-series metadata and isolate display time',async()=>{
 const i=input([submission(1,40*60000),submission(2,50*60000,'JUDGING',{pending:true})]),a=archive();
 a.series=[{title:'#',rule:{preset:'Normal'}},{title:'S#',rule:{preset:'Normal'}}];
 const initial=engine.project(i,a,0);assert.equal(initial.nextEventMs,30*60000);
 assert.equal(initial.ranklist.series.length,2);assert.equal(initial.ranklist.series[1].title,'S#');
 assert.equal(initial.own.score,0);assert.equal(initial.ranklist.rows.length,2);
 assert.equal(initial.ranklist.rows[0].user.id,initial.own.id,'Zero-score own row must follow the VP user-id tie order');
 assert.equal(engine.project(i,a,40*60000).nextEventMs,50*60000);
 assert.equal(engine.project(i,a,50*60000).nextEventMs,4*3600000);
 i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';
 const board=context.VpBoard.create({readSnapshot:async()=>i,engine,cache:{get:async()=>({archive:a,hash:'hash'}),set:async()=>{}},
  sources:{loadArchive:async()=>{throw Error('unexpected network');}}});
 const reads=[];const original=board.snapshot('practice');const zero=board.snapshot('practice',{elapsedMs:0});
 const same=board.snapshot('practice',{elapsedMs:0}),later=board.snapshot('practice',{elapsedMs:50*60000});
 const results=await Promise.all([original,zero,same,later]);
 assert.equal(results[1],results[2]);assert.notEqual(results[0],results[1]);assert.notEqual(results[1],results[3]);
 assert.equal(results[1].own.score,0);assert.equal(results[3].own.score,1);assert.equal(results[3].provisional,true);
});

test('view-only local score bypasses historical archives even when cached or refresh is requested',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';
 const fail=()=>{throw Error('Historical data must not be read for local score');};
 const board=context.VpBoard.create({readSnapshot:async()=>i,engine,cache:{get:fail,set:fail},sources:{loadArchive:fail}});
 const result=await board.snapshot('practice',{localOnly:true,refresh:true});
 assert.equal(result.scope,'self');assert.equal(result.own.rank,null);assert.equal(result.own.score,1);
 assert.equal(result.own.penaltyMinutes,1);
});

test('explicit refresh checks the source during a concurrent cached read',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';
 let release,reads=0,loads=0;const gate=new Promise(resolve=>{release=resolve;});
 const board=context.VpBoard.create({readSnapshot:async()=>{if(++reads===1)await gate;return i;},engine,
  cache:{get:async()=>({archive:archive()}),set:async()=>{}},
  sources:{loadArchive:async()=>{loads++;throw Error('offline');}}});
 const cached=board.snapshot('practice');const refreshed=board.snapshot('practice',{refresh:true});
 release();const results=await Promise.all([cached,refreshed]);
 assert.equal(loads,1);assert.equal(results[1].scope,'historical');assert.equal(results[1].cached,true);
 assert.equal(results[1].warning,'offline');assert.equal(results[1].own.score,1);
});
