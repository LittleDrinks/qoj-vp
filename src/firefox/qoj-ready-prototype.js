/* Interactive UI prototype for the native QOJ virtual/register page.
 * Example checks stay in memory. Capture the original Start before its handlers
 * so exploring this prototype cannot start an actual contest. */
(() => {
  "use strict";
  const form = document.getElementById("form-register_vp");
  const start = document.getElementById("button-submit-register_vp");
  if (location.origin !== "https://qoj.ac" || !/^\/contest\/\d+\/virtual\/register\/?$/.test(location.pathname) || !form || !start) {
    return {mounted:false, reason:"请先打开已登录的 QOJ 开始虚拟参赛页面。"};
  }
  window.__qojReadyPrototypeDispose?.();
  const host = document.createElement("div");
  host.id = "qoj-vp-ready-prototype";
  const root = host.attachShadow({mode:"open"});
  root.innerHTML = `
    <style>
      :host { display:block; margin:18px 0 20px; color:#222b35; font:13px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }
      * { box-sizing:border-box; }
      [hidden] { display:none !important; }
      button,input,select,textarea { font:inherit; }
      button { cursor:pointer; color:inherit; }
      button:disabled { cursor:wait; opacity:.6; }
      button:focus-visible { outline:2px solid #80baff; outline-offset:3px; }
      .heading { display:flex; align-items:center; justify-content:space-between; margin-bottom:4px; border-top:1px solid #e7e9ec; padding-top:15px; }
      .heading h2 { font-size:14px; font-weight:600; margin:0; }
      .count { font-size:11px; color:#86909c; }
      .count strong { color:#435367; font-weight:500; }
      .station { display:grid; grid-template-columns:27px 1fr auto 8px; gap:9px; width:100%; background:#fff; border:0; border-bottom:1px solid #eff0f2; padding:13px 0; align-items:center; text-align:left; }
      .station:hover { background:#f8fafc; }
      .lights { display:flex; align-items:center; gap:4px; }
      .light { width:6px; height:6px; border-radius:50%; border:1px solid #ccd0d5; background:#fff; }
      .station[data-state=ready] .green { background:#269756; border-color:#269756; }
      .station[data-state=attention] .red { background:#dd4242; border-color:#dd4242; }
      .station[data-state=checking] .yellow { background:#e2ae25; border-color:#e2ae25; animation:pulse 1s infinite; }
      .name { display:block; color:#24364b; font-size:13px; font-weight:500; }
      .description { display:block; margin-top:1px; font-size:10px; color:#8b929c; line-height:1.6; }
      .status { font:500 10px/1.4 ui-monospace,"Cascadia Mono",monospace; letter-spacing:.2px; color:#278956; white-space:nowrap; }
      [data-state=attention] .status { color:#c64545; }
      [data-state=checking] .status { color:#a88324; }
      .chevron { font-size:18px; color:#a6aeb7; }
      .panel-foot { display:flex; justify-content:space-between; align-items:center; gap:10px; padding-top:9px; }
      .demo-label { font-size:10px; color:#969da6; }
      .text-button { border:0; background:transparent; padding:3px 0; color:#587b9f; font-size:11px; }
      .notice { color:#687c95; font-size:11px; padding:10px 0 0; }
      @keyframes pulse { 50% { opacity:.4; } }
      @media(prefers-reduced-motion:reduce) { * { animation:none !important; } }
    </style>
    <section aria-labelledby="ready-title">
      <header class="heading"><h2 id="ready-title">比赛准备</h2><span class="count" aria-live="polite"><strong id="count">2 / 3</strong> Ready</span></header>
      <div id="stations"></div>
      <footer class="panel-foot"><span class="demo-label">UI 预览 · 示例状态</span><button class="text-button" id="recheck">↻ 重新检查</button></footer>
      <div class="notice" id="notice" role="status" hidden></div>
    </section>
  `;
  form.before(host);
  const $ = id => root.getElementById(id);
  const keys = ["resources","board","judger"];
  const names = {resources:"题面与样例",board:"Board 数据",judger:"Judger"};
  const account = document.querySelector('ul.nav.nav-pills.float-right a[href^="/user/profile/"]')?.textContent.trim() || "当前账号";
  const contest = document.title.split(" - ")[0];
  let state = {
    resources:{status:"ready",message:"13 / 13 题已准备",missing:false},
    board:{status:"attention",message:"请设置历史榜单来源",detail:"粘贴本场比赛的榜单链接后，保存并检查。"},
    judger:{status:"ready",message:"dry-run 通过 · C++20",detail:"示例演练通过 · 当前账号 · 当前比赛 · A · C++20"}
  };
  let disposed = false, resourceFrame, frameReady, activeSection="resources";
  for (const key of keys) {
    const button=document.createElement("button");
    button.className="station"; button.id="station-"+key; button.type="button";
    button.setAttribute("aria-haspopup","dialog");
    button.innerHTML='<span class="lights" aria-hidden="true"><i class="light red"></i><i class="light yellow"></i><i class="light green"></i></span><span><span class="name">'+names[key]+'</span><span class="description" id="description-'+key+'"></span></span><span class="status" id="status-'+key+'"></span><span class="chevron" aria-hidden="true">›</span>';
    button.addEventListener("click",()=>openSettings(key)); $("stations").append(button);
  }
  function render() {
    $("count").textContent=keys.filter(key=>state[key].status==="ready").length+" / 3";
    for (const key of keys) {
      $("station-"+key).dataset.state=state[key].status;
      $("status-"+key).textContent={ready:"READY",attention:"NOT READY",checking:"CHECKING"}[state[key].status];
      $("description-"+key).textContent=state[key].message;
    }
    $("recheck").disabled=keys.some(key=>state[key].status==="checking");
  }
  function notice(message) { $("notice").hidden=false; $("notice").textContent=message; }
  async function ensureWorkbench() {
    if(frameReady)return frameReady;
    frameReady=(async()=>{
      const compressed=/* WORKBENCH_FRAME */null;
      if(!compressed)throw new Error("请通过 npm run preview:ready 加载工作台组件。");
      const bytes=Uint8Array.from(atob(compressed),char=>char.charCodeAt(0));
      const html=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
      if(disposed)return;
      resourceFrame=document.createElement("iframe");
      resourceFrame.title="DOMjudge 工作台 · 比赛准备";
      resourceFrame.setAttribute("sandbox","allow-scripts allow-downloads");
      resourceFrame.style.cssText="position:fixed;inset:0;width:100vw;height:100vh;border:0;background:transparent;z-index:2147483000;";
      resourceFrame.hidden=true;
      const loaded=new Promise(resolve=>resourceFrame.addEventListener("load",resolve,{once:true}));
      resourceFrame.srcdoc=html;root.append(resourceFrame);await loaded;
    })();
    return frameReady;
  }
  async function openSettings(section, pending) {
    try {
      await ensureWorkbench();if(disposed)return;
      if(keys.includes(section))activeSection=section;
      delete resourceFrame.dataset.open;
      resourceFrame.hidden=false;
      resourceFrame.contentWindow.postMessage({type:"qoj-ready-open",section,account,contest,pending},"*");
    }catch(error){notice(error.message);}
  }
  function workbenchMessage(event) {
    if(!resourceFrame||event.source!==resourceFrame.contentWindow)return;
    if(event.data?.type==="qoj-ready-close") {resourceFrame.hidden=true;delete resourceFrame.dataset.open;$("station-"+activeSection).focus();}
    if(event.data?.type==="qoj-ready-modal-shown")resourceFrame.dataset.open=event.data.name;
    if(event.data?.type==="qoj-ready-state") {
      const {key,status,message}=event.data;
      if(!keys.includes(key)||!["ready","attention","checking"].includes(status)||typeof message!=="string")return;
      state[key]={status,message};render();
    }
    if(event.data?.type==="qoj-ready-start-confirmed")notice("预览：已确认仍然开始。当前页面继续保留在赛前准备状态。");
  }
  window.addEventListener("message",workbenchMessage);
  $("recheck").addEventListener("click",async()=>{
    try {await ensureWorkbench();if(!disposed)resourceFrame.contentWindow.postMessage({type:"qoj-ready-check-all"},"*");}
    catch(error){notice(error.message);}
  });
  function beforeStart(event) {
    event.preventDefault();event.stopImmediatePropagation();
    const pending=keys.filter(key=>state[key].status!=="ready");
    if(!pending.length){notice("预览：已确认开始，将在 QOJ 确认后进入工作台。");return;}
    openSettings("warning",pending.map(key=>({key,name:names[key],message:state[key].message})));
  }
  start.addEventListener("click",beforeStart,true);
  form.addEventListener("submit",beforeStart,true);
  window.__qojReadyPrototypeDispose=()=>{disposed=true;window.removeEventListener("message",workbenchMessage);root.querySelectorAll("dialog[open]").forEach(dialog=>dialog.close());start.removeEventListener("click",beforeStart,true);form.removeEventListener("submit",beforeStart,true);host.remove();delete window.__qojReadyPrototypeDispose;};
  render();
  return {mounted:true,contest,preview:true};
})();
