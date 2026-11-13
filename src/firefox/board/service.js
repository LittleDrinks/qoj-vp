"use strict";
globalThis.VpBoard = (() => {
  function create({readSnapshot, sources, cache, engine, clock=Date.now}) {
    const pending=new Map(),archives=new Map(),failures=new Map();
    function keyFor(url) {
      const parsed=new URL(url);
      return parsed.origin+':'+parsed.searchParams.get('contest');
    }
    function sourceUrl(raw) {
      const url=new URL(raw), main=url.origin==='https://rl.algoux.cn' && url.pathname.match(/^\/ranklist\/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\/?$/);
      if(main && !url.username && !url.password) return 'https://vp.xcpc.link/?contest='+encodeURIComponent(main[1]);
      if(url.username || url.password || url.pathname!=='/' ||
        !(url.origin==='https://vp.xcpc.link' || url.protocol==='http:' && ['localhost','127.0.0.1'].includes(url.hostname)) ||
        !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(url.searchParams.get('contest') || '')) throw new Error('INVALID_BOARD_SOURCE');
      return url.origin+'/?contest='+encodeURIComponent(url.searchParams.get('contest'));
    }
    async function download(input,url) {
      const record=await sources.loadArchive(url);
      engine.project(input,record.archive);
      try {await cache.set(keyFor(url),record);}
      catch (_) {throw new Error('BOARD_CACHE_FAILED');}
      archives.set(keyFor(url),record);failures.delete(keyFor(url));
      return record;
    }
    async function prepare(sessionId,{url,board,refresh=true}) {
      const input=await readSnapshot(sessionId);
      if(input.session.sessionId!==sessionId) throw new Error('BOARD_SESSION_MISMATCH');
      url=sourceUrl(url);
      const draft={...input,session:{...input.session,ranklandUrl:url,...(board ? {board} : {})}};
      let record=!refresh && (archives.get(keyFor(url)) || await cache.get(keyFor(url)).catch(()=>null));
      if(record) engine.project(draft,record.archive);
      else record=await download(draft,url);
      const title=record.archive.contest.title;
      return {stored:true,url,title:typeof title==='string'?title:title?.zh_CN || title?.en_US || record.contestKey,
        teams:record.archive.rows.length,problems:record.archive.problems.length,
        labels:record.archive.problems.map(problem=>problem.alias),fetchedAt:record.fetchedAt,
        submissions:record.archive.rows.reduce((total,row)=>total+row.statuses.reduce((sum,status)=>sum+(status.solutions?.length || 0),0),0)};
    }
    async function project(sessionId,refresh,elapsedMs,localOnly) {
      const input=await readSnapshot(sessionId);
      if(input.session.sessionId!==sessionId) throw new Error('BOARD_SESSION_MISMATCH');
      let record=null,warning=null,cached=false;
      const url=input.session.ranklandUrl;
      if(url && !localOnly) {
        const key=keyFor(url);
        record=archives.get(key) || await cache.get(key).catch(()=>null);
        if(record) archives.set(key,record);
        if(refresh || !record && (failures.get(key)||0)<clock()) {
          try {
            record=await download(input,url);
          } catch(error) {
            warning=error.code || error.message || 'BOARD_SOURCE_UNAVAILABLE';
            failures.set(key,clock()+30000); cached=Boolean(record);
          }
        }
      }
      let result;
      try { result=engine.project(input,record?.archive || null,elapsedMs); }
      catch(error) {warning=error.code || error.message;record=null;result=engine.project(input,null,elapsedMs);}
      return {...result,inputKey:engine.inputKey(input),observedAt:clock(),warning,cached,stored:Boolean(record),
        source:record?{provider:'rankland',contestKey:record.contestKey,hash:record.hash,fetchedAt:record.fetchedAt}:null};
    }
    function snapshot(sessionId,{refresh=false,elapsedMs=null,localOnly=false}={}) {
      if(elapsedMs!==null && (!Number.isFinite(elapsedMs) || elapsedMs<0)) return Promise.reject(new Error('INVALID_BOARD_TIME'));
      // Each display instant has its own read; identical seeks join one writer.
      const key=sessionId+':'+(localOnly?'self:':'historical:')+(refresh?'refresh:':'read:')+(elapsedMs===null?'live':elapsedMs);
      if(!pending.has(key)) pending.set(key,project(sessionId,refresh,elapsedMs,localOnly).finally(()=>pending.delete(key)));
      return pending.get(key);
    }
    return {snapshot,prepare};
  }
  return {create};
})();
