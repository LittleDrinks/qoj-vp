/* In-memory adapter for the workbench dialogs, sharing their Bootstrap styles. */
const $ = id => document.getElementById(id);
document.body.insertAdjacentHTML("beforeend", `
<div id="judger-modal" class="modal fade" tabindex="-1" aria-labelledby="judger-title" aria-hidden="true"><div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 id="judger-title" class="modal-title">提交工具</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
  <form id="judger-form"><div class="modal-body">
    <div id="judger-error" class="alert alert-danger d-none" role="status"></div>
    <div class="mb-3"><label class="form-label" for="judger-account">QOJ 账号</label><input id="judger-account" class="form-control" readonly></div>
    <div class="mb-3"><label class="form-label" for="judger-contest">比赛</label><select id="judger-contest" class="form-select"><option value="current">当前比赛</option><option value="none">Select a contest</option></select></div>
    <div class="mb-3"><label class="form-label" for="judger-language">Language</label><select id="judger-language" class="form-select"><option>C++20</option><option>C++17</option><option>Python 3</option></select></div>
    <div class="mb-3"><label class="form-label" for="judger-problem">Problem</label><select id="judger-problem" class="form-select"><option>A</option><option>B</option><option>C</option><option>D</option></select></div>
    <p class="form-text mb-0">通过 qoj-submitter 的 dry-run 检查账号、比赛、题号与语言。演练期间代码保留在本地。</p>
  </div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button><button id="judger-check" type="submit" class="btn btn-success">运行 dry-run</button></div></form>
</div></div></div>
<div id="warning-modal" class="modal fade" tabindex="-1" aria-labelledby="warning-title" aria-hidden="true"><div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 id="warning-title" class="modal-title">确认比赛准备</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
  <div class="modal-body"><p>以下准备需要确认。可以先完成设置，也可以现在开始。</p><ul id="pending-items" class="list-group"></ul></div>
  <div class="modal-footer"><button id="warning-settings" type="button" class="btn btn-secondary">返回设置</button><button id="warning-start" type="button" class="btn btn-success">仍然开始</button></div>
</div></div></div>`);
const MAX_RESOURCE_BYTES = 64 * 1024 * 1024;
const state = {
  session:{sessionId:"ui-preview",contestId:"preview"},
  contest:{problems:[..."ABCDEFGHIJKLM"].map(label=>({id:label,label,name:"示例题目 "+label}))},
  resources:new Map(),resourceInteractive:new Map(),resourceActivity:new Map(),resourceDownloads:new Set(),
  resourceSummary:"界面预览 · 示例题目与文件",resourceJob:null,resourceReading:false,manualBusy:false
};
const modals = {};
const problemById = id => state.contest.problems.find(problem=>problem.id===id);
const isJuryRoute = () => true;
const renderProblems = () => {};
function exampleResource(id, manual=false) {
  return {problemId:id,status:"ready",kind:"samples",resourceId:"a".repeat(64),sha256:"b".repeat(64),
    filename:id+"-samples.zip",totalBytes:2048,sampleSource:manual?"manual":"download"};
}
for(const problem of state.contest.problems)state.resources.set(problem.id,exampleResource(problem.id));
function announceReady() {
  const ready=state.contest.problems.filter(problem=>readyResources(problem.id).length).length;
  report("resources",ready===state.contest.problems.length?"ready":"attention",ready+" / "+state.contest.problems.length+" 题已准备");
}
function report(key,status,message) { parent.postMessage({type:"qoj-ready-state",key,status,message},"*"); }
function resourceDownloadAction(control,problem) {
  control.addEventListener("click",event=>{
    event.preventDefault();const anchor=document.createElement("a");
    anchor.href="data:application/zip;base64,"+EXAMPLE_SAMPLE_ZIP;
    anchor.download="example-"+problem.label+"-samples.zip";
    anchor.click();
  });
}
async function prepareResources(ids=state.contest.problems.map(problem=>problem.id)) {
  if(state.resourceJob)return;
  report("resources","checking","正在检查题目文件…");
  state.resourceJob=true;
  for(const id of ids)state.resourceActivity.set(id,"正在准备…");
  renderResourceModal();
  await new Promise(resolve=>setTimeout(resolve,600));
  for(const id of ids){state.resourceActivity.delete(id);if(!state.resources.has(id))state.resources.set(id,exampleResource(id));}
  state.resourceJob=false;renderResourceModal();announceReady();
}
for(const name of ["resources","manual-samples","rankland","judger","warning"]) {
  modals[name]=new bootstrap.Modal($(name+"-modal"));
  const caption=node("small","text-muted me-auto","UI 预览 · 示例数据");
  $(name+"-modal").querySelector(".modal-footer").prepend(caption);
  $(name+"-modal").addEventListener("shown.bs.modal",()=>parent.postMessage({type:"qoj-ready-modal-shown",name},"*"));
  $(name+"-modal").addEventListener("hidden.bs.modal",()=>setTimeout(()=>{
    if(!document.querySelector(".modal.show"))parent.postMessage({type:"qoj-ready-close"},"*");
  },400));
}
$("manual-samples-mode").addEventListener("change",renderManualMode);
$("manual-samples-form").addEventListener("submit",event=>{
  event.preventDefault();hideMessage($("manual-samples-error"));
  const text=$("manual-samples-mode").value==="text";
  if(text&&!$("manual-sample-input").value&&!$("manual-sample-output").value){showMessage($("manual-samples-error"),"请粘贴样例输入或输出。");return;}
  if(!text&&!$("manual-samples-files").files.length){showMessage($("manual-samples-error"),"请选择样例 ZIP 或输入/输出文件。");return;}
  if(!$("manual-samples-replace-group").hidden&&!$("manual-samples-replace").checked){showMessage($("manual-samples-error"),"请确认是否替换已有样例。");return;}
  state.resources.set(state.manualProblem,exampleResource(state.manualProblem,true));
  renderResourceModal();announceReady();modals["manual-samples"].hide();
});
$("manual-samples-modal").addEventListener("hidden.bs.modal",()=>modals.resources.show());
$("prepare-resources").addEventListener("click",()=>prepareResources());
$("refresh-resources").addEventListener("click",()=>prepareResources());
let pending=[];
function openSection(key) {
  const name=key==="board"?"rankland":key;
  if(!modals[name])return;
  const active=document.querySelector(".modal.show");
  if(active&&active.id!==name+"-modal") {
    active.addEventListener("hidden.bs.modal",()=>modals[name].show(),{once:true});
    bootstrap.Modal.getInstance(active).hide();
  }else modals[name].show();
}
async function checkBoard() {
  report("board","checking","正在检查榜单数据…");
  await new Promise(resolve=>setTimeout(resolve,600));
  let valid=false;
  try {const u=new URL($("rankland-url").value.trim());valid=u.protocol==="https:"&&!u.username&&!u.password&&((u.hostname==="rl.algoux.cn"&&/^\/ranklist\/[^/]+/.test(u.pathname))||(u.hostname==="vp.xcpc.link"&&(u.search.length>1||u.pathname.length>1)));}catch(_){}
  showMessage($("rankland-error"),valid?"示例：榜单数据已加载，题目对应关系已确认。":"请填写本场 RankLand 榜单或 VP 比赛链接。",valid?"success":"warning");
  report("board",valid?"ready":"attention",valid?"历史数据已加载 · 题目对应一致":"请设置历史榜单来源");
}
$("rankland-url").addEventListener("input",()=>report("board","attention","来源已修改，等待检查"));
$("rankland-form").addEventListener("submit",event=>{event.preventDefault();checkBoard();});
$("board-rule").addEventListener("change",()=>{const reveal=$("board-rule").value==="CCPC26";$("board-reveal-settings").hidden=!reveal;$("board-reveal-settings").disabled=!reveal;report("board","attention","赛制已修改，等待检查");});
async function checkJudger() {
  $("judger-check").disabled=true;report("judger","checking","正在执行 dry-run…");
  await new Promise(resolve=>setTimeout(resolve,600));
  const valid=$("judger-contest").value==="current";
  showMessage($("judger-error"),valid?"示例：提交准备通过，账号、比赛、题号与语言已确认。":"请选择当前比赛。",valid?"success":"warning");
  report("judger",valid?"ready":"attention",valid?"dry-run 通过 · "+$("judger-language").value:"需要绑定当前比赛");
  $("judger-check").disabled=false;
}
for(const id of ["judger-contest","judger-language","judger-problem"])$(id).addEventListener("change",()=>report("judger","attention","设置已修改，等待演练"));
$("judger-form").addEventListener("submit",event=>{event.preventDefault();checkJudger();});
$("warning-settings").addEventListener("click",()=>openSection(pending[0]?.key||"resources"));
$("warning-start").addEventListener("click",()=>{modals.warning.hide();parent.postMessage({type:"qoj-ready-start-confirmed"},"*");});
window.addEventListener("message",event=>{
  if(event.source!==parent)return;
  if(event.data?.type==="qoj-ready-check-all") {prepareResources();checkBoard();checkJudger();}
  if(event.data?.type!=="qoj-ready-open")return;
  $("judger-account").value=event.data.account||"示例账号";
  $("judger-contest").options[0].textContent=event.data.contest||"当前比赛";
  if(event.data.section==="warning") {
    pending=Array.isArray(event.data.pending)?event.data.pending:[];
    $("pending-items").replaceChildren(...pending.map(item=>{const li=node("li","list-group-item"),title=node("strong","",item.name),message=node("div","small text-muted",item.message);li.append(title,message);return li;}));
  }
  openSection(event.data.section);
});
renderResourceModal();
