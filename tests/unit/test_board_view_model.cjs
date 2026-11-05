'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={console,URL,TextEncoder,TextDecoder,setTimeout,clearTimeout,setInterval,clearInterval,queueMicrotask,structuredClone};
vm.createContext(context);
vm.runInContext(fs.readFileSync('src/firefox/board/generated/view.js','utf8'),context);
const view=context.VpBoardView;

test('display settings use the upstream defaults and reject unknown or stale values',()=>{
 const settings=view.normalizeSettings({statusCellPreset:'compact',emptyStatusPlaceholder:'dot',userAvatarPlacement:'name',theme:'dark',rowStriped:false});
 assert.equal(settings.statusCellPreset,'compact');assert.equal(settings.emptyStatusPlaceholder,'dot');
 assert.equal(settings.userAvatarPlacement,'user');assert.equal(settings.theme,'dark');assert.equal(settings.rowStriped,false);
 const defaults=view.normalizeSettings({statusCellPreset:'invalid',theme:'other',feed:false});
 assert.equal(defaults.statusCellPreset,'classic');assert.equal(defaults.theme,'system');assert.equal(defaults.feed,false);
 assert.equal(defaults.preferCCPC26,true);assert.equal(defaults.tableBordered,false);
});

test('view playback is independent of the immutable contest clock and survives a paused restore',()=>{
 const session={startAt:1000000,durationMs:300000},before=JSON.stringify(session);
 const initial=view.initialPlayback(session,null,1000000);
 assert.equal(initial.custom,false);assert.equal(initial.elapsedMs,0);
 const paused=view.playbackForToggle(initial,0,60000,1060000,300000);
 assert.equal(paused.custom,true);assert.equal(paused.playing,false);
 assert.equal(view.advancePlayback(paused,90000,1120000,300000).elapsedMs,60000);
 const playing=view.playbackForToggle(paused,60000,90000,1120000,300000);
 assert.equal(view.advancePlayback({...playing,speed:5},90000,1122000,300000).elapsedMs,70000);
 const sought=view.playbackForSeek(playing,120000,300000,1122000);
 assert.equal(sought.playing,false);assert.equal(sought.elapsedMs,120000);
 const restored=view.initialPlayback(session,{version:1,startAt:session.startAt,elapsedMs:120000,playing:false,speed:5,custom:true,savedAt:1122000},1200000);
 assert.equal(restored.elapsedMs,120000);assert.equal(restored.playing,false);assert.equal(restored.custom,true);
 assert.equal(JSON.stringify(session),before);
 assert.equal(view.liveElapsed({startAt:null,durationMs:300000},9999999),0);
});

test('feed diff preserves same-time submissions, recognizes late rejudges and never replays backwards',()=>{
 const a=['team',0,'WA',[60000,'ms']],b=['team',0,'WA',[60000,'ms']],ac=['team',0,'AC',[120000,'ms']];
 assert.equal(view.feedSolutions([],[a,b],true).length,2);
 assert.equal(view.feedSolutions([a],[a,b],true).length,1);
 assert.deepEqual(Array.from(view.feedSolutions([a],[ac],true),x=>Array.from(x)),[ac]);
 assert.equal(view.feedSolutions([ac],[a],false).length,0);
});

test('row windows retain absolute positions and bounded rich rendering',()=>{
 const range=view.uniformRowWindow(2000,-30000,60,0,1000);
 assert.ok(range.start>0&&range.end>range.start&&range.end<=2000);
 assert.ok(range.end-range.start<100);
 const empty=view.uniformRowWindow(0,0,60,0,1000);assert.equal(empty.start,0);assert.equal(empty.end,0);
});

test('display filtering retains rank columns and computes statistics from visible rows only',()=>{
 const source={version:'0.3.14',type:'general',contest:{title:'x',startAt:'2026-01-01T00:00:00Z',duration:[1,'h']},
  problems:[{alias:'A'}],series:[{title:'#',rule:{preset:'Normal'}},{title:'S#',rule:{preset:'Normal'}}],
  sorter:{algorithm:'ICPC',config:{penalty:[20,'min']}},
  rows:[{user:{id:'a',name:'A',organization:'One',official:true},score:{value:1,time:[1,'min']},rankValues:[{rank:1},{rank:1}],statuses:[{result:'AC',tries:1,time:[1,'min']}]},
   {user:{id:'b',name:'B',organization:'Two',official:false},score:{value:0},rankValues:[{rank:null},{rank:null}],statuses:[{result:null,tries:0}]}]};
 const presented=view.presentRanklist(source,{organizations:[],officialOnly:true,marker:''},view.normalizeSettings());
 assert.equal(presented.data.series.length,2);assert.equal(presented.data.rows.length,1);
 assert.equal(presented.data.problems[0].statistics.accepted,1);
 assert.equal(presented.data.rows[0].rankValues.length,2);
});

test('contest time formatting retains the source offset and clock text is stable',()=>{
 const range=view.formatContestTimeRange('2024-11-03T09:00:00+08:00',[5,'h']);
 assert.equal(range.startText,'2024-11-03 09:00:00');assert.equal(range.endText,'2024-11-03 14:00:00 +08:00');
 assert.equal(view.formatClock(3723000),'01:02:03');
});
