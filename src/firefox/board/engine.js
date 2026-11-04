/** Pure Board interface: project({session, contest, history}, archive, elapsedMs).
 * No browser storage, networking, QOJ DOM or RankLand page state belongs here.
 */
import {regenerateRanklistBySolutions, convertToStaticRanklist, formatTimeDuration} from '@algoux/standard-ranklist-utils';
const OWN = '__qoj_vp_local_team__';
const verdicts = {'CORRECT':'AC','WRONG-ANSWER':'WA','TIMELIMIT':'TLE','RUN-ERROR':'RTE',
  'COMPILER-ERROR':'CE','NO-OUTPUT':'NOUT','OUTPUT-LIMIT':'OLE','MEMORY-LIMIT':'MLE','PRESENTATION-ERROR':'PE'};
const fail = code => {throw Object.assign(new Error(code),{code});};
const clone = value => JSON.parse(JSON.stringify(value));
export function milliseconds(time) {
  if (!Array.isArray(time) || time.length !== 2 || typeof time[0] !== 'number' || !Number.isFinite(time[0]) ||
      !['ms','s','min','h','d'].includes(time[1])) fail('INVALID_BOARD_TIME');
  const ms = formatTimeDuration(time, 'ms');
  if (!Number.isSafeInteger(ms) || ms < 0) fail('INVALID_BOARD_TIME');
  return ms;
}
export function configuration(session) {
  // One-time compatibility read for existing sessions; explicit board fields win.
  const query = new URL(session.ranklandUrl || 'https://vp.xcpc.link/').searchParams;
  const input = session.board || {};
  const rule = input.rule || query.get('rule') || 'auto';
  if (!['auto','ICPC','CCPC26'].includes(rule)) fail('UNSUPPORTED_BOARD_RULE');
  const count = Number(input.revealCount ?? query.get('count') ?? 50);
  const ratio = Number(input.revealRatio ?? query.get('ratio') ?? 20);
  if (!Number.isInteger(count) || count < 0 || !Number.isFinite(ratio) || ratio < 0 || ratio > 100) fail('INVALID_BOARD_RULE');
  return {...input, rule, revealCount:count, revealRatio:ratio};
}
function sourceFor(input, archive) {
  const {session,contest} = input;
  const problems=contest?.problems || [];
  if (!problems.length) fail('BOARD_PROBLEMS_UNAVAILABLE');
  const config=configuration(session);
  let source=archive ? clone(archive) : {version:'0.3.14',type:'general',
    contest:{title:session.title,startAt:new Date(session.startAt ?? 0).toISOString(),duration:[session.durationMs,'ms']},
    problems:problems.map(p=>({alias:p.label,title:p.name})),rows:[],series:[{title:'Rank',rule:{preset:'Normal'}}],
    sorter:{algorithm:'ICPC',config:{penalty:[20,'min'],timePrecision:'min',rankingTimePrecision:'min'}}};
  if (source.type !== 'general' || !/^0\.3\.(?:[0-9]|1[0-4])$/.test(source.version) || source.sorter?.algorithm !== 'ICPC' ||
      !Array.isArray(source.rows) || source.rows.length > 20000 || !Array.isArray(source.problems)) fail('UNSUPPORTED_BOARD_DATA');
  if (milliseconds(source.contest.duration) !== session.durationMs || source.problems.length !== problems.length) fail('BOARD_CONTEST_MISMATCH');
  const indexes=problems.map(p=>source.problems.findIndex(s=>String(s.alias).toUpperCase()===String(p.label).toUpperCase()));
  if (indexes.some(i=>i<0) || new Set(indexes).size!==problems.length) fail('BOARD_PROBLEM_MAPPING_MISMATCH');
  for (const [i,p] of problems.entries()) {
    const link=source.problems[indexes[i]].link;
    if (link) {
      const match=String(link).match(/^https:\/\/qoj\.ac\/(?:contest\/\d+\/)?problem\/(\d+)\/?$/);
      if (match && match[1]!==String(p.id)) fail('BOARD_PROBLEM_MAPPING_MISMATCH');
    }
  }
  const extensions=source.sorter.config?.extendedAlgorithms || [];
  if (config.rule==='auto' && extensions.some(e=>e.algorithm!=='CCPC26')) fail('UNSUPPORTED_BOARD_RULE');
  source.sorter.config={...source.sorter.config};
  if(config.rule==='ICPC') delete source.sorter.config.extendedAlgorithms;
  if(config.rule==='CCPC26') source.sorter.config.extendedAlgorithms=[{algorithm:'CCPC26',config:{
    problemRevealAcceptedThreshold:{count:config.revealCount,ratio:config.revealRatio/100}}}];
  source.series=[{title:'Rank',rule:{preset:'Normal'}}];
  // Historical names/links are data; never load remote avatars or executable links.
  function sanitize(value) {
    if (!value || typeof value!=='object') return;
    for(const key of Object.keys(value)) {
      if (['avatar','logo','backgroundImage'].includes(key)) delete value[key];
      else if (['link','url'].includes(key) && typeof value[key]==='string' && !/^https:\/\//.test(value[key])) delete value[key];
      else sanitize(value[key]);
    }
  }
  sanitize(source);
  return {source,indexes,config};
}
export function project(input, archive=null, elapsedMs=null) {
  const {session,contest,history}=input;
  const {source,indexes,config}=sourceFor(input,archive);
  const end=session.finishedAt!=null && session.startAt!=null ? Math.min(session.durationMs,session.finishedAt-session.startAt) : session.durationMs;
  const elapsed=Math.max(0,Math.min(end,elapsedMs ?? session.elapsedMs ?? 0));
  const timelines=[], ids=new Set();
  let freeze=source.contest.frozenDuration ? session.durationMs-milliseconds(source.contest.frozenDuration) : session.durationMs;
  let partial=false;
  source.rows.forEach((row,i)=>{
    const id='historical:'+i; row.user={...row.user,id};
    if (!Array.isArray(row.statuses) || row.statuses.length!==source.problems.length) fail('INVALID_BOARD_HISTORY');
    row.statuses.forEach((status,index)=>{
      if (!Array.isArray(status.solutions) && (status.result || status.tries || status.time)) fail('BOARD_HISTORY_INCOMPLETE');
      if (!status.solutions?.length && (status.result || status.tries)) fail('BOARD_HISTORY_INCOMPLETE');
      for(const solution of status.solutions || []) {
        const at=milliseconds(solution.time);
        if(at>=session.durationMs || at>elapsed) continue;
        const result=elapsed<session.durationMs && at>=freeze ? '?' : solution.result;
        if(solution.result==='?') partial=true;
        timelines.push([id,index,result,[at,'ms']]);
      }
    });
  });
  source.rows.push({user:{id:OWN,name:session.account || 'My team',official:true},statuses:source.problems.map(()=>({solutions:[]})),score:{value:0}});
  const ownPending=new Array(source.problems.length).fill(0);
  let unverified=0;
  const records=[...(history?.submissions || [])].sort((a,b)=>a.elapsedMs-b.elapsedMs || String(a.id).localeCompare(String(b.id),undefined,{numeric:true}));
  for(const item of records) {
    // Only server-confirmed, scoped timestamps enter a score. Never clamp old submissions to zero.
    if(item.state!=='confirmed' || item.inSession!==true || !item.id || !Number.isSafeInteger(item.elapsedMs) ||
       item.elapsedMs<0 || item.elapsedMs>=end || item.timeSource==='local-intent') {if(item.operationId)unverified++;continue;}
    const key=String(item.id);
    if(ids.has(key)) fail('DUPLICATE_BOARD_SUBMISSION');
    ids.add(key);
    const local=contest.problems.findIndex(p=>String(p.id)===String(item.problemId));
    if(local<0) fail('BOARD_PROBLEM_MAPPING_MISMATCH');
    if(item.elapsedMs>elapsed) continue;
    const index=indexes[local], result=verdicts[item.verdict];
    if(item.pending || !result) ownPending[index]++;
    else timelines.push([OWN,index,result,[item.elapsedMs,'ms']]);
  }
  // Stable sort retains source order / submission ID order for ties.
  timelines.sort((a,b)=>a[3][0]-b[3][0]);
  // '?' must not turn a later AC into an extra wrong attempt in upstream scoring.
  const waiting=timelines.filter(t=>t[2]==='?');
  let ranklist=regenerateRanklistBySolutions(source,timelines.filter(t=>t[2]!=='?'));
  for(const [id,index,,time] of waiting) {
    const status=ranklist.rows.find(r=>r.user.id===id).statuses[index];
    status.solutions.push({result:'?',time});
    if(!['AC','FB'].includes(status.result)) {status.result='?';status.tries=(status.tries||0)+1;}
  }
  const own=ranklist.rows.find(row=>row.user.id===OWN);
  const progress=contest.problems.map((problem,i)=>{
    const status=own.statuses[indexes[i]],accepted=['AC','FB'].includes(status.result);
    return {problemId:String(problem.id),acceptedMs:accepted?milliseconds(status.time):null,
      judged:status.tries||0,pending:ownPending[indexes[i]]};
  });
  own.statuses.forEach((status,i)=>{
    if(ownPending[i] && !['AC','FB'].includes(status.result)) {status.result='?';status.tries=(status.tries||0)+ownPending[i];}
  });
  ranklist.contest.startAt=new Date(session.startAt??0).toISOString();
  ranklist.time=new Date((session.startAt??0)+elapsed).toISOString();
  ranklist=convertToStaticRanklist(ranklist);
  const self=ranklist.rows.find(row=>row.user.id===OWN);
  return {version:1,sessionId:session.sessionId,elapsedMs:elapsed,rule:config.rule,ranklist,
    own:{score:self.score.value,penaltyMinutes:Math.floor(milliseconds(self.score.time)/60000),
      rank:archive?self.rankValues[0]?.rank??null:null,progress},
    provisional:partial || ownPending.some(Boolean) || unverified>0,unverified,
    scope:archive?'historical':'self'};
}

export function inputKey(input) {
  const s=input.session;
  return JSON.stringify([s.sessionId,s.account,s.startAt,s.durationMs,s.finishedAt??null,s.ranklandUrl??null,s.board??null,
    input.contest?.problems?.map(p=>[String(p.id),p.label]),
    (input.history?.submissions||[]).map(r=>[r.id??null,r.operationId??null,String(r.problemId),r.state,r.elapsedMs,
      r.inSession,r.pending,r.verdict,r.timeSource]).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)))]);
}
