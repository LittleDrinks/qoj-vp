"use strict";
globalThis.VpReadyUi = (() => {
  const names = {resources:"题面与样例",board:"榜单数据",judger:"提交工具"};
  function create({token,state,modals,call,openResources,openRanklandSettings,loadResourceManifest,prepareResources,readyResource}) {
    const $ = id => document.getElementById(id), states = {}, jobs = {}, changes = {}, revisions = {}, repeat = {};
    let connectionError = "正在连接助手…", connectionSection, initialization;
    const connectionHints = {resources:"连接后检查题面与样例",board:"连接后设置并抓取榜单",judger:"连接后检查提交配置"};
    const connectionMessage = () => /403/.test(connectionError) ? "QOJ 拒绝读取比赛（403），请在原站完成验证后重新连接。"
      : /network|connection|timeout|timed out|fetch/i.test(connectionError) ? "连接中断，请检查网络后重新连接。" : connectionError;
    const post = (action, extra={}) => window.parent.postMessage({type:"vp.ready.host",token,action,...extra}, "https://qoj.ac");
    function set(section,status,detail) {
      states[section] = {state:status,detail}; post("state", {states,connection:state.connected ? "" : connectionMessage()});
      if (section === "judger") {
        $("ready-judger-status").className = "alert alert-" + (status === "ready" ? "success" : status === "checking" ? "info" : "warning");
        $("ready-judger-status").textContent = detail;
      }
    }
    function invalidate(section, method) {
      if (method === "prepare_resource" && jobs.resources) return;
      revisions[section] = (revisions[section] || 0) + 1;
      set(section,"checking","正在检查…");
    }
    function edited(section, detail) {invalidate(section);set(section,"attention",detail);}
    function checked(section, action) {
      if (jobs[section]) return jobs[section];
      set(section,"checking","正在检查…");
      const revision = revisions[section] || 0;
      const report = (status,detail) => {if ((revisions[section] || 0) === revision) set(section,status,detail);};
      jobs[section] = (async () => {
        try {
          if (!state.connected) throw new Error(connectionError);
          await action(report);
        } catch (error) {report("attention",error.message);}
      })().finally(() => {
        delete jobs[section];
        if (repeat[section]) {delete repeat[section];checks[section]();}
      });
      return jobs[section];
    }
    function resources() {
      return checked("resources", async report => {
        await loadResourceManifest();
        await prepareResources();
        const problems = state.contest.problems, missing = [];
        for (const [index,problem] of problems.entries()) {
          report("checking",`检查题面 ${index + 1} / ${problems.length}`);
          try {
            await call("qoj_problem_form",{sessionId:state.session.sessionId,problemId:String(problem.id)});
            if (!readyResource(String(problem.id))) missing.push(problem.label);
          } catch (_) {missing.push(problem.label);}
        }
        if (state.resourceManifestError) throw new Error(state.resourceManifestError);
        report(missing.length ? "attention" : "ready", missing.length ? "待处理：" + missing.join("、") : problems.length + " 题题面与样例已确认");
      });
    }
    function board() {
      return checked("board", async report => {
        const sessionId = state.session.sessionId;
        await call("scoreboard.resolve",{sessionId});
        state.session = await call("inspect_session",{sessionId});
        const result = await call("board.snapshot",{sessionId,includeHistory:true,refresh:true,elapsedMs:0});
        if (result.scope !== "historical" || !result.stored) throw new Error("请抓取并保存本场历史榜单数据，核对题目对应关系。");
        state.board = result;
        report("ready","历史榜单已保存，题目对应关系已确认" + (result.cached ? " · 使用缓存" : ""));
      });
    }
    function judger(bind=false) {
      return checked("judger", async report => {
        const controls = [$("ready-judger-check"),$("ready-judger-bind"),$("ready-problem"),$("ready-language")];
        controls.forEach(control => {control.disabled = true;});
        try {
          const result = await call(bind ? "submitter_bind" : "submitter_check",{sessionId:state.session.sessionId,
            problem:$("ready-problem").value,language:$("ready-language").value});
          $("ready-judger-output").textContent = result.output;
          report("ready",result.account + " · dry-run 通过 · " + ($("ready-language").selectedOptions?.[0]?.textContent || result.language));
        } finally {controls.forEach(control => {control.disabled = false;});}
      });
    }
    const checks = {resources,board,judger};
    function changed(section, method) {
      if (method === "prepare_resource" && jobs.resources) return;
      if (jobs[section]) {repeat[section] = true;return;}
      clearTimeout(changes[section]); changes[section] = setTimeout(() => checks[section](), 150);
    }
    function warning() {
      const list = $("ready-warning-list"); list.replaceChildren();
      if (!state.connected) {
        const item = document.createElement("li"); item.textContent = connectionMessage(); list.append(item);
      }
      for (const [id,name] of Object.entries(state.connected ? names : {})) {
        if (states[id]?.state === "ready") continue;
        const item = document.createElement("li"); item.textContent = name + "：" + (states[id]?.detail || connectionError); list.append(item);
      }
      if (!list.children.length) {const item=document.createElement("li");item.textContent="准备状态已超过五分钟，请重新检查。";list.append(item);}
      modals["ready-warning"].show();
    }
    function openSettings(section) {
      if (!names[section]) return;
      if (!state.connected) {
        connectionSection = section;
        $("ready-connection-title").textContent = names[section];
        $("ready-connection-message").textContent = connectionMessage();
        $("ready-connection-details").textContent = connectionError;
        modals["ready-connection"].show(); return;
      }
      if (section === "resources") openResources();
      if (section === "board") openRanklandSettings();
      if (section === "judger") modals["ready-judger"].show();
    }
    $("ready-connection-retry").addEventListener("click", async () => {
      const button = $("ready-connection-retry"); button.disabled = true;
      try {
        await initialize();
        $("ready-connection-message").textContent = connectionMessage();
        $("ready-connection-details").textContent = connectionError;
        if (state.connected) {
          $("ready-connection-modal").addEventListener("hidden.bs.modal", () => openSettings(connectionSection), {once:true});
          modals["ready-connection"].hide();
        }
      } finally {button.disabled = false;}
    });
    const openModals = new Set();
    for (const id of ["resources","manual-samples","rankland","ready-judger","ready-warning","ready-connection"]) {
      $(id+"-modal").addEventListener("show.bs.modal", () => openModals.add(id));
      $(id+"-modal").addEventListener("hidden.bs.modal", () => {
        openModals.delete(id);
        // Bootstrap starts the next backdrop before adding its modal's show class.
        setTimeout(() => {if (!openModals.size) post("close");}, 30);
      });
    }
    $("ready-continue").addEventListener("click", () => {post("continue");modals["ready-warning"].hide();});
    $("ready-judger-check").addEventListener("click", () => judger());
    $("ready-judger-bind").addEventListener("click", () => judger(true));
    for (const id of ["ready-problem","ready-language"]) $(id).addEventListener("change", () => {
      $("ready-judger-output").textContent=""; edited("judger","设置已更新，点击运行 dry-run。");
    });
    $("rankland-form").addEventListener("input", () => edited("board","设置已更新，保存后重新检查。"));
    $("resources-list").addEventListener("change", () => {invalidate("resources");changed("resources");});
    window.addEventListener("message", event => {
      if (event.source !== window.parent || event.origin !== "https://qoj.ac" || event.data?.type !== "vp.ready.ui" || event.data.token !== token) return;
      const {action,section} = event.data;
      if (action === "check") {if (!state.connected) initialize(); else for (const check of Object.values(checks)) check();}
      if (action === "warning") warning();
      if (action === "open") openSettings(section);
      if (action === "appearance") {
        const {fontFamily,fontSize,lineHeight} = event.data;
        if (typeof fontFamily === "string") document.body.style.fontFamily = fontFamily;
        if (typeof fontSize === "string") document.documentElement.style.fontSize = fontSize;
        if (typeof lineHeight === "string") document.body.style.lineHeight = lineHeight;
      }
    });
    function initialize() {
      if (initialization) return initialization;
      initialization = connect().finally(() => {initialization = null;});
      return initialization;
    }
    async function connect() {
      for (const section of Object.keys(names)) invalidate(section);
      try {
        const result = await call("connect");
        if (!result.contest?.problems?.length) throw new Error("请在 QOJ 确认本场题目可访问后重新检查。");
        state.session = result.session; state.sessions = [result.session]; state.contest = result.contest;
        state.connected = true; state.generation++;
        $("ready-account").textContent = result.session.account;
        $("ready-contest").textContent = result.contest.name + " (" + result.session.contestId + ")";
        $("ready-problem").replaceChildren();
        for (const problem of result.contest.problems) $("ready-problem").append(new Option(problem.label,problem.label));
        await Promise.all(Object.values(checks).map(check => check()));
      } catch (error) {
        state.connected = false; connectionError = error.message;
        for (const section of Object.keys(names)) set(section,"unavailable",connectionHints[section]);
      }
    }
    return {initialize,invalidate,changed,failed:(section,error)=>edited(section,error.message)};
  }
  return {create};
})();
