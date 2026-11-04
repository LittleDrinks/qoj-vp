"use strict";
globalThis.VpBoard = (() => {
  function create({readSnapshot, sources, cache, engine, clock=Date.now}) {
    const pending=new Map(),archives=new Map(),failures=new Map();
    function keyFor(url) {
      const parsed=new URL(url);
      return parsed.origin+':'+parsed.searchParams.get('contest');
    }
    async function project(sessionId,refresh) {
      const input=await readSnapshot(sessionId);
      if(input.session.sessionId!==sessionId) throw new Error('BOARD_SESSION_MISMATCH');
      let record=null,warning=null,cached=false;
      const url=input.session.ranklandUrl;
      if(url) {
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
      try { result=engine.project(input,record?.archive || null); }
      catch(error) {warning=error.code || error.message;record=null;result=engine.project(input);}
      return {...result,inputKey:engine.inputKey(input),observedAt:clock(),warning,cached,
        source:record?{provider:'rankland',contestKey:record.contestKey,hash:record.hash,fetchedAt:record.fetchedAt}:null};
    }
    function snapshot(sessionId,{refresh=false}={}) {
      // A manual refresh joins an existing read; it never creates another writer.
      if(!pending.has(sessionId)) pending.set(sessionId,project(sessionId,refresh).finally(()=>pending.delete(sessionId)));
      return pending.get(sessionId);
    }
    return {snapshot};
  }
  return {create};
})();
