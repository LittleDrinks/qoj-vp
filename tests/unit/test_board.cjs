'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={URL,console};vm.createContext(context);
for(const file of ['board/generated/engine.js','board/service.js']) vm.runInContext(fs.readFileSync('src/firefox/'+file,'utf8'),context);
const engine=context.VpBoardEngine;
const duration=18000000;
function input(records=[]) {return {session:{sessionId:'practice',contestId:'1',account:'me',startAt:1000000,
 durationMs:duration,elapsedMs:duration,state:'finished'},contest:{problems:[{id:'1',label:'A'},{id:'2',label:'B'}]},history:{submissions:records}};}
function submission(id,elapsedMs,verdict='CORRECT',extra={}) {return {id:String(id),problemId:'1',state:'confirmed',inSession:true,elapsedMs,verdict,pending:false,timeSource:'provider-absolute',...extra};}
function archive() {return {version:'0.3.14',type:'general',contest:{title:'test',startAt:'2020-01-01T00:00:00Z',duration:[5,'h'],frozenDuration:[1,'h']},
 problems:[{alias:'A'},{alias:'B'}],series:[{title:'Rank',rule:{preset:'Normal'}}],sorter:{algorithm:'ICPC',config:{penalty:[20,'min'],timePrecision:'min'}},
 rows:[{user:{id:'opponent',name:'Opponent'},score:{value:1,time:[30,'min']},statuses:[{result:'AC',tries:1,time:[30,'min'],solutions:[{result:'AC',time:[30,'min']}]},{solutions:[]}]}]};}
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
test('unavailable source degrades to own score and is backed off; cached invalid source cannot supply a rank',async()=>{
 const i=input([submission(1,60000)]);i.session.ranklandUrl='https://vp.xcpc.link/?contest=fixture';let reads=0;
 const board=context.VpBoard.create({readSnapshot:async()=>i,engine,cache:{get:async()=>null,set:async()=>{}},clock:()=>10000,
 sources:{loadArchive:async()=>{reads++;throw Error('offline');}}});
 const b=await board.snapshot('practice');assert.equal(b.own.rank,null);assert.equal(b.own.score,1);
 await board.snapshot('practice');assert.equal(reads,1);
});
