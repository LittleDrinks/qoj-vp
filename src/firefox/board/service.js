"use strict";
globalThis.VpBoard = (() => {
  function create({readSnapshot, sources, cache, engine, clock=Date.now}) {
    const pending=new Map(),archives=new Map(),failures=new Map();
    function keyFor(url) {
      const parsed=new URL(url);
      return parsed.origin+':'+parsed.searchParams.get('contest');
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
            const candidate=await sources.loadArchive(url);
            // Validate before persisting; summarized standings are not a replay.
            engine.project(input,candidate.archive);
            record=candidate;
            archives.set(key,record);failures.delete(key);
            await cache.set(key,record).catch(()=>{});
          } catch(error) {
            warning=error.code || error.message || 'BOARD_SOURCE_UNAVAILABLE';
            failures.set(key,clock()+30000); cached=Boolean(record);
          }
        }
      }
      let result;
      try { result=engine.project(input,record?.archive || null,elapsedMs); }
      catch(error) {warning=error.code || error.message;record=null;result=engine.project(input,null,elapsedMs);}
      return {...result,inputKey:engine.inputKey(input),observedAt:clock(),warning,cached,
        source:record?{provider:'rankland',contestKey:record.contestKey,hash:record.hash,fetchedAt:record.fetchedAt}:null};
    }
    function snapshot(sessionId,{refresh=false,elapsedMs=null,localOnly=false}={}) {
      if(elapsedMs!==null && (!Number.isFinite(elapsedMs) || elapsedMs<0)) return Promise.reject(new Error('INVALID_BOARD_TIME'));
      // Each display instant has its own read; identical seeks join one writer.
      const key=sessionId+':'+(localOnly?'self:':'historical:')+(elapsedMs===null?'live':elapsedMs);
      if(!pending.has(key)) pending.set(key,project(sessionId,refresh,elapsedMs,localOnly).finally(()=>pending.delete(key)));
      return pending.get(key);
    }
    return {snapshot};
  }
  return {create};
})();
