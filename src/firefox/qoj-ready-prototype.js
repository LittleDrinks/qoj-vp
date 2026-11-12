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
      dialog { width:min(590px,calc(100vw - 32px)); max-height:calc(100vh - 40px); padding:0; border:1px solid #d6dce4; border-radius:5px; color:#26374a; background:#fff; box-shadow:0 16px 65px #172b4440; }
      dialog::backdrop { background:#15263966; }
      .dialog-head { display:flex; justify-content:space-between; align-items:start; gap:15px; padding:20px 23px 16px; border-bottom:1px solid #e7ebf0; }
      .dialog-head h2 { font-size:18px; font-weight:500; margin:0 0 4px; }
      .dialog-head p { margin:0; font-size:12px; color:#84909f; }
      .close { border:0; background:transparent; font-size:22px; color:#8993a0; padding:0 3px; line-height:1; }
      .dialog-body { padding:20px 23px; }
      .dialog-actions { display:flex; align-items:center; justify-content:flex-end; gap:9px; padding:14px 23px; border-top:1px solid #e7ebf0; background:#fbfcfd; }
      .button { border:1px solid #d1d9e3; border-radius:3px; padding:7px 14px; background:#fff; color:#4a6079; font-size:12px; }
      .button:hover { background:#f3f7fb; }
      .button.primary { background:#007bff; border-color:#007bff; color:#fff; }
      .button.primary:hover { background:#086bd7; }
      .label { display:block; color:#4c5c70; font-size:12px; margin-bottom:6px; }
      input,select,textarea { width:100%; min-width:0; padding:9px 10px; color:#34465b; background:#fff; border:1px solid #ced7e2; border-radius:3px; }
      input:focus,select:focus,textarea:focus { outline:2px solid #d3e8ff; border-color:#80baff; }
      input::placeholder,textarea::placeholder { color:#a0a8b1; }
      .helper { font-size:11px; color:#8b96a4; margin:7px 0 0; }
      .feedback { padding:11px 12px; margin-top:16px; border-left:2px solid #d1a048; background:#fffbf3; color:#a17e36; font-size:12px; }
      .feedback.success { border-color:#55a16c; background:#f4faf6; color:#528466; }
      .feedback.checking { border-color:#7d9ec5; background:#f5f9ff; color:#6483a6; }
      .detail-actions { display:flex; align-items:center; gap:14px; margin-top:16px; }
      .problems { display:grid; grid-template-columns:repeat(7,1fr); gap:7px; }
      .problem { padding:9px 4px; border:1px solid #dce6df; border-radius:3px; background:#fff; color:#405a4a; }
      .problem:hover { background:#f3f9f5; }
      .problem strong { display:block; font-size:14px; font-weight:500; }
      .problem small { display:block; color:#81968a; font-size:10px; }
      .problem.missing { border-color:#e8cb9b; color:#a47c39; background:#fffaf1; }
      .problem.missing small { color:#a47c39; }
      .resource-count { color:#688371; font-size:12px; margin:0 0 13px; }
      .fields { display:grid; grid-template-columns:1fr 1fr; gap:15px; }
      .account { padding:9px 10px; background:#f7f9fb; border:1px solid #e0e6ed; border-radius:3px; }
      .pending { list-style:none; margin:17px 0 0; padding:0; }
      .pending li { border-left:2px solid #d48573; padding:10px 13px; margin-top:8px; background:#fff8f5; font-size:13px; }
      .pending small { display:block; color:#a58a7c; font-size:11px; margin-top:2px; }
      textarea { height:130px; resize:vertical; font:12px/1.6 ui-monospace,monospace; }
      .notice { color:#687c95; font-size:11px; padding:10px 0 0; }
      .scenario { width:auto; padding:3px 5px; font-size:11px; color:#78899d; }
      @keyframes pulse { 50% { opacity:.4; } }
      @media(prefers-reduced-motion:reduce) { * { animation:none !important; } }
      @media(max-width:480px) { .dialog-body,.dialog-head { padding:18px; } .problems { grid-template-columns:repeat(5,1fr); } .fields { grid-template-columns:1fr; } }
    </style>
    <section aria-labelledby="ready-title">
      <header class="heading"><h2 id="ready-title">比赛准备</h2><span class="count" aria-live="polite"><strong id="count">2 / 3</strong> Ready</span></header>
      <div id="stations"></div>
      <footer class="panel-foot"><span class="demo-label">UI 预览 · 示例状态</span><button class="text-button" id="recheck">↻ 重新检查</button></footer>
      <div class="notice" id="notice" role="status" hidden></div>
    </section>
    <dialog id="settings" aria-labelledby="settings-title">
      <header class="dialog-head"><div><h2 id="settings-title"></h2><p id="settings-subtitle"></p></div><button class="close" id="close-settings" aria-label="关闭设置">×</button></header>
      <div class="dialog-body">
        <section id="detail-resources" hidden><p class="resource-count" id="resource-count"></p><div class="problems" id="problems"></div><div class="detail-actions"><button class="button" id="check-resources">重新获取</button><span class="helper">点击题号补充输入与输出样例。</span></div></section>
        <section id="detail-board" hidden><label class="label" for="board-url">RankLand 榜单或 VP 链接</label><input type="url" id="board-url" placeholder="粘贴本场比赛的榜单链接" autocomplete="off" spellcheck="false"><p class="helper">支持 rl.algoux.cn 和 vp.xcpc.link。</p><div id="board-feedback" class="feedback" role="status"></div><div class="detail-actions"><button class="button primary" id="check-board">保存并检查</button><button class="text-button" id="auto-board">重新自动匹配</button></div></section>
        <section id="detail-judger" hidden><div class="fields"><div><span class="label">提交账号</span><div class="account" id="account"></div></div><div><label class="label" for="judger-contest">绑定比赛</label><select id="judger-contest"><option value="current">当前比赛</option><option value="none">选择比赛</option></select></div><div><label class="label" for="judger-language">语言</label><select id="judger-language"><option>C++20</option><option>C++17</option><option>Python 3</option></select></div><div><label class="label" for="judger-problem">演练题号</label><select id="judger-problem"><option>A</option><option>B</option><option>C</option><option>D</option></select></div></div><div id="judger-feedback" class="feedback" role="status"></div><div class="detail-actions"><button class="button primary" id="check-judger">运行 dry-run</button><span class="helper">演练检查准备流程，代码留在本地。</span></div></section>
      </div><footer class="dialog-actions"><span class="demo-label" style="margin-right:auto">交互预览 · 示例数据</span><button class="button" id="done-settings">完成</button></footer>
    </dialog>
    <dialog id="warning" aria-labelledby="warning-title"><header class="dialog-head"><div><h2 id="warning-title"></h2><p>你可以先完成设置，也可以现在开始。</p></div><button class="close" id="close-warning" aria-label="关闭提示">×</button></header><div class="dialog-body"><ul class="pending" id="pending" style="margin-top:0"></ul></div><footer class="dialog-actions"><button class="button" id="back-settings">返回设置</button><button class="button primary" id="continue-start">仍然开始</button></footer></dialog>
    <dialog id="sample" aria-labelledby="sample-title"><header class="dialog-head"><div><h2 id="sample-title"></h2><p>补充一组样例输入和对应输出。</p></div><button class="close" id="close-sample" aria-label="关闭样例">×</button></header><div class="dialog-body"><div class="fields"><div><label class="label" for="sample-input">样例输入</label><textarea id="sample-input"></textarea></div><div><label class="label" for="sample-output">样例输出</label><textarea id="sample-output"></textarea></div></div><p class="helper" id="sample-note"></p></div><footer class="dialog-actions"><button class="button" id="cancel-sample">取消</button><button class="button primary" id="save-sample">保存样例</button></footer></dialog>
  `;
  form.before(host);
  const $ = id => root.getElementById(id);
  const keys = ["resources","board","judger"];
  const names = {resources:"题面与样例",board:"Board 数据",judger:"Judger"};
  const subtitles = {resources:"逐题核对题面与样例，补充缺少的文件。",board:"读取历史榜单，并核对本场比赛的题目对应关系。",judger:"使用 qoj-submitter 的账号与比赛配置演练提交准备。"};
  const account = document.querySelector('a[href^="/user/profile/"]')?.textContent.trim() || "当前账号";
  const contest = document.title.split(" - ")[0];
  $("account").textContent = account;
  $("judger-contest").options[0].textContent = contest + " · 当前比赛";
  let state = {
    resources:{status:"ready",message:"13 / 13 题已准备",missing:false},
    board:{status:"attention",message:"请设置历史榜单来源",detail:"粘贴本场比赛的榜单链接后，保存并检查。"},
    judger:{status:"ready",message:"dry-run 通过 · C++20",detail:"示例演练通过 · 当前账号 · 当前比赛 · A · C++20"}
  };
  let disposed = false, sampleProblem = "A";
  const samples = new Map();
  for (const key of keys) {
    const button=document.createElement("button");
    button.className="station"; button.id="station-"+key; button.type="button";
    button.setAttribute("aria-haspopup","dialog");
    button.innerHTML='<span class="lights" aria-hidden="true"><i class="light red"></i><i class="light yellow"></i><i class="light green"></i></span><span><span class="name">'+names[key]+'</span><span class="description" id="description-'+key+'"></span></span><span class="status" id="status-'+key+'"></span><span class="chevron" aria-hidden="true">›</span>';
    button.addEventListener("click",()=>openSettings(key)); $("stations").append(button);
    $("check-"+key).addEventListener("click",()=>check(key));
  }
  function render() {
    $("count").textContent=keys.filter(key=>state[key].status==="ready").length+" / 3";
    for (const key of keys) {
      $("station-"+key).dataset.state=state[key].status;
      $("status-"+key).textContent={ready:"READY",attention:"NOT READY",checking:"CHECKING"}[state[key].status];
      $("description-"+key).textContent=state[key].message;
      $("check-"+key).disabled=state[key].status==="checking";
    }
    $("recheck").disabled=keys.some(key=>state[key].status==="checking");
    for (const key of ["board","judger"]) { $(key+"-feedback").textContent=state[key].detail; $(key+"-feedback").className="feedback "+(state[key].status==="ready"?"success":state[key].status==="checking"?"checking":""); }
    $("resource-count").textContent=(state.resources.missing?12:13)+" / 13 题已准备 · 点击题号查看或补充样例";
    $("problems").replaceChildren(...[..."ABCDEFGHIJKLM"].map(label=>{
      const button=document.createElement("button"), missing=label==="M"&&state.resources.missing;
      button.className="problem"+(missing?" missing":""); button.innerHTML="<strong>"+label+"</strong><small>"+(missing?"待补充":"样例 ✓")+"</small>";
      button.addEventListener("click",()=>{sampleProblem=label;$("sample-title").textContent=label+" · 题面与样例";$("sample-input").value=samples.get(label)?.input||"";$("sample-output").value=samples.get(label)?.output||"";$("sample-note").textContent="示例：题面可访问，可追加输入与输出样例。";$("sample").showModal();}); return button;
    }));
  }
  function openSettings(key) {
    keys.forEach(item=>$("detail-"+item).hidden=item!==key);
    $("settings-title").textContent=names[key]==="Judger"?"Judger · 提交工具":names[key];
    $("settings-subtitle").textContent=subtitles[key];
    if(!$("settings").open) $("settings").showModal();
  }
  function notice(message) { $("notice").hidden=false; $("notice").textContent=message; }
  async function check(key) {
    const item=state[key]; if(item.status==="checking")return;
    item.status="checking"; item.message="正在检查…"; item.detail="正在检查…";render();
    await new Promise(resolve=>setTimeout(resolve,700));
    if(disposed||state[key]!==item)return;
    if(key==="resources") { item.status=item.missing?"attention":"ready";item.message=item.missing?"12 / 13 题 · M 题样例待补充":"13 / 13 题已准备"; }
    if(key==="board") {
      let valid=false;try {const u=new URL($("board-url").value.trim());valid=u.protocol==="https:"&&!u.username&&!u.password&&((u.hostname==="rl.algoux.cn"&&/^\/ranklist\/[^/]+/.test(u.pathname))||(u.hostname==="vp.xcpc.link"&&(u.search.length>1||u.pathname.length>1)));}catch(_){}
      item.status=valid?"ready":"attention";item.message=valid?"历史数据已加载 · 题目对应一致":"请设置历史榜单来源";
      item.detail=valid?"示例：历史榜单已加载，题目对应关系已确认。":"请填写本场 RankLand 榜单或 VP 比赛的完整链接。";
    }
    if(key==="judger") {const valid=$("judger-contest").value==="current";item.status=valid?"ready":"attention";item.message=valid?"dry-run 通过 · "+$("judger-language").value:"需要绑定当前比赛";item.detail=valid?"示例演练通过 · "+account+" · "+contest+" · "+$("judger-problem").value+" · "+$("judger-language").value:"请选择当前比赛，然后运行 dry-run。";}
    render();
  }
  $("board-url").addEventListener("input",()=>{state.board={status:"attention",message:"来源已修改，等待检查",detail:"保存并检查后确认榜单与题目对应关系。"};render();});
  for(const id of ["judger-contest","judger-language","judger-problem"]) $(id).addEventListener("change",()=>{state.judger={status:"attention",message:"设置已修改，等待演练",detail:"运行 dry-run 检查当前提交配置。"};render();});
  $("recheck").addEventListener("click",()=>Promise.all(keys.map(check)));
  $("auto-board").addEventListener("click",()=>{$("board-feedback").textContent="示例：自动匹配暂未找到榜单，请粘贴本场比赛链接。";});
  for(const id of ["close-settings","done-settings"]) $(id).addEventListener("click",()=>$("settings").close());
  for(const id of ["close-sample","cancel-sample"]) $(id).addEventListener("click",()=>$("sample").close());
  $("save-sample").addEventListener("click",()=>{if(!$("sample-input").value.trim()||!$("sample-output").value.trim()){$("sample-note").textContent="请填写样例输入和对应输出。";return;}samples.set(sampleProblem,{input:$("sample-input").value,output:$("sample-output").value});if(sampleProblem==="M")state.resources.missing=false;$("sample").close();check("resources");});
  function beforeStart(event) {
    event.preventDefault();event.stopImmediatePropagation();
    const pending=keys.filter(key=>state[key].status!=="ready");
    if(!pending.length){notice("预览：已确认开始，将在 QOJ 确认后进入工作台。");return;}
    $("warning-title").textContent="还有 "+pending.length+" 项准备需要确认";
    $("pending").replaceChildren(...pending.map(key=>{const li=document.createElement("li"),name=document.createElement("span"),small=document.createElement("small");name.textContent=names[key];small.textContent=state[key].message;li.append(name,small);return li;}));
    if(!$("warning").open)$("warning").showModal();
  }
  start.addEventListener("click",beforeStart,true);
  form.addEventListener("submit",beforeStart,true);
  $("close-warning").addEventListener("click",()=>$("warning").close());
  $("back-settings").addEventListener("click",()=>{$("warning").close();const pending=keys.find(key=>state[key].status!=="ready");if(pending)openSettings(pending);});
  $("continue-start").addEventListener("click",()=>{$("warning").close();notice("预览：已确认仍然开始。当前页面继续保留在赛前准备状态。");});
  window.__qojReadyPrototypeDispose=()=>{disposed=true;root.querySelectorAll("dialog[open]").forEach(dialog=>dialog.close());start.removeEventListener("click",beforeStart,true);form.removeEventListener("submit",beforeStart,true);host.remove();delete window.__qojReadyPrototypeDispose;};
  render();
  return {mounted:true,contest,preview:true};
})();
