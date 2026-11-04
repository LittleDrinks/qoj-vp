/* Historical data is a replaceable cache; the native ledger owns session facts. */
"use strict";
globalThis.VpBoardCache = (() => {
  let connection;
  function database() {
    return connection ||= new Promise((resolve,reject)=>{
      const request=indexedDB.open('qoj-vp-board',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('archives');
      request.onsuccess=()=>resolve(request.result);
      request.onerror=()=>{connection=null;reject(request.error);};
    });
  }
  async function access(mode,key,value) {
    const db=await database();
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('archives',mode),store=tx.objectStore('archives');
      const request=mode==='readonly'?store.get(key):store.put(value,key);
      tx.oncomplete=()=>resolve(request.result);
      tx.onerror=()=>reject(tx.error);
      tx.onabort=()=>reject(tx.error || new Error('BOARD_CACHE_ABORTED'));
    });
  }
  return {get:key=>access('readonly',key),set:(key,value)=>access('readwrite',key,value)};
})();
