"use strict";
const test = require("node:test"), assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm");
test("a readiness frame is scoped to its original QOJ tab and session and cannot submit code", async () => {
  const register = "https://qoj.ac/contest/4686/virtual/register", values = {}, calls = [];
  const runtime = {id:"extension",getURL:path=>"https://extension.invalid/"+path};
  let currentUrl = register;
  const source = {id:runtime.id,frameId:0,tab:{id:8},url:register};
  const context = {URL,Date,crypto:require("node:crypto").webcrypto};
  vm.createContext(context);vm.runInContext(fs.readFileSync("src/firefox/readiness-bridge.js","utf8"),context);
  const bridge = context.VpReadinessBridge.create({runtime,tabs:{get:async()=>({url:currentUrl})},
    storage:{get:async key=>({[key]:values[key]}),set:async value=>Object.assign(values,value)},
    lifecycle:{registration:async()=>{},bind:async()=>({sessionId:"bound-session"})},
    dispatch:async(method,args)=>{calls.push({method,args});return {session:{sessionId:"bound-session"}};}});
  const opened = await bridge.handle({type:"vp.ready.open",cid:"4686"},source);
  const frame = {...source,frameId:5,url:opened.url};
  await bridge.handle({type:"vp.ready.task",token:opened.token,method:"connect"},frame);
  await bridge.handle({type:"vp.ready.task",token:opened.token,method:"qoj_problem_form",args:{sessionId:"bound-session",httpTabId:99}},frame);
  assert.equal(calls.at(-1).args.httpTabId,8);
  await bridge.handle({type:"vp.ready.task",token:opened.token,method:"update_session",args:{sessionId:"bound-session",ranklandUrl:"https://rl.algoux.cn/ranklist/example"}},frame);
  assert.deepEqual(Object.keys(calls.at(-1).args),["sessionId","ranklandUrl"]);
  const before = calls.length;
  for (const changed of [{method:"qoj_submit",args:{sessionId:"bound-session"}},
    {method:"submitter_check",args:{sessionId:"another-session"}}, {token:"another-ticket"}]) {
    await assert.rejects(bridge.handle({type:"vp.ready.task",token:opened.token,method:"connect",...changed},frame));
  }
  await assert.rejects(bridge.handle({type:"vp.ready.task",token:opened.token,method:"connect"},{...frame,tab:{id:9}}));
  currentUrl = "https://qoj.ac/contest/4687/virtual/register";
  await assert.rejects(bridge.handle({type:"vp.ready.task",token:opened.token,method:"connect"},frame));
  assert.equal(calls.length,before);
});
