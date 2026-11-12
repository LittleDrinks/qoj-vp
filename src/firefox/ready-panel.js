"use strict";
globalThis.VpReadyPanel = (() => {
  const names = {resources: "题面与样例", board: "Board 数据", judger: "Judger"};
  function mount({form, panelId, send}) {
    const panel = document.createElement("div"); panel.id = panelId;
    const root = panel.attachShadow({mode: "open"}), rows = {};
    const style = document.createElement("style");
    style.textContent = `:host{display:block;background:white;color:#212529;font:14px Arial,sans-serif;margin:18px 0}
      header,footer{display:flex;justify-content:space-between;align-items:center;padding:10px 0;font-size:12px}
      header{border-top:1px solid #dee2e6}header strong{font-size:15px}button{font:inherit;cursor:pointer}
      .row{display:flex;align-items:center;gap:10px;width:100%;padding:14px 0;background:white;border:0;border-bottom:1px solid #dee2e6;text-align:left;color:inherit}
      .dot{width:10px;height:10px;border-radius:50%;background:#b94040;flex:none}.checking .dot{background:#d69b25}.ready .dot{background:#31905b}
      .label{flex:1;min-width:0}.label small{display:block;color:#6c757d;font-size:11px;margin-top:5px;overflow-wrap:anywhere;line-height:1.5}
      .status{font:10px monospace;white-space:nowrap}.ready .status{color:#28794c}.attention .status{color:#a23333}
      footer{color:#6c757d}footer button{border:0;background:none;color:#0069d9;font-size:12px;padding:4px 0}
      button:focus-visible{outline:2px solid #007bff;outline-offset:3px}`;
    root.append(style);
    const heading = document.createElement("header"), title = document.createElement("strong"), count = document.createElement("span");
    title.textContent = "Contest readiness"; count.textContent = "0 / 3 Ready"; heading.append(title, count); root.append(heading);
    let frame, token, frameOrigin, states = {}, pending = false, allowed = false, checkedAt = 0, listening = false, queued;
    const post = (action, extra = {}) => {
      if (!listening) {queued = {action,extra};return;}
      frame?.contentWindow.postMessage({type:"vp.ready.ui", token, action, ...extra}, frameOrigin);
    };
    for (const [id, name] of Object.entries(names)) {
      const row = document.createElement("button"); row.type = "button"; row.className = "row checking";
      const dot = document.createElement("span"), label = document.createElement("span"), detail = document.createElement("small"), status = document.createElement("span");
      dot.className = "dot"; label.className = "label"; status.className = "status"; status.textContent = "CHECKING";
      label.textContent = name; detail.textContent = "正在连接助手…"; label.append(detail); row.append(dot,label,status);
      row.addEventListener("click", () => { if (frame) {frame.hidden = false; post("open", {section:id});} });
      rows[id] = {row,detail,status}; root.append(row);
    }
    const footer = document.createElement("footer"), note = document.createElement("span"), retry = document.createElement("button");
    note.textContent = "开始前确认准备状态"; retry.type = "button"; retry.textContent = "↻ 重新检查";
    retry.addEventListener("click", () => frame ? post("check") : connect()); footer.append(note,retry); root.append(footer);
    form.before(panel);
    function update(value) {
      states = value; checkedAt = Date.now();
      for (const [id, ui] of Object.entries(rows)) {
        const result = value[id] || {state:"attention",detail:"点击重新检查"};
        ui.row.className = "row " + result.state; ui.detail.textContent = result.detail;
        ui.status.textContent = {ready:"READY",attention:"NOT READY",checking:"CHECKING"}[result.state] || "NOT READY";
      }
      count.textContent = Object.values(value).filter(item => item.state === "ready").length + " / 3 Ready";
    }
    window.addEventListener("message", event => {
      if (!frame || event.source !== frame.contentWindow || event.origin !== frameOrigin || event.data?.token !== token || event.data?.type !== "vp.ready.host") return;
      if (event.data.action === "state") {
        listening = true; update(event.data.states);
        if (queued) {const next=queued;queued=null;post(next.action,next.extra);}
      }
      if (event.data.action === "close") {frame.hidden = true;pending = false;}
      if (event.data.action === "continue" && pending) {
        pending = false; frame.hidden = true; allowed = true;
        try {form.querySelector("#button-submit-register_vp").click();} finally {allowed = false;}
      }
    });
    function guard(event) {
      if (event.type === "click" && !event.target.closest?.("#button-submit-register_vp")) return;
      if (event.type === "submit" && event.target !== form) return;
      if (allowed || Object.keys(names).every(id => states[id]?.state === "ready") && Date.now() - checkedAt < 300000) {
        send("vp.qoj.startIntent").catch(() => {}); return;
      }
      event.preventDefault(); event.stopImmediatePropagation();
      pending = true;
      if (frame) {frame.hidden = false; post("warning");}
      else if (window.confirm("比赛准备检查需要处理。仍然开始？")) {
        pending = false; allowed = true;
        try {form.querySelector("#button-submit-register_vp").click();} finally {allowed = false;}
      }
    }
    document.addEventListener("click", guard, true); form.addEventListener("submit", guard, true);
    let connecting;
    function connect() {
      if (connecting) return connecting;
      connecting = (async () => {
        try {
          const result = await send("vp.ready.open"); token = result.token; frameOrigin = new URL(result.url).origin;
          frame = document.createElement("iframe"); frame.title = "QOJ VP 准备设置"; frame.src = result.url; frame.hidden = true;
          Object.assign(frame.style, {position:"fixed",inset:"0",width:"100%",height:"100%",border:"0",zIndex:"2147483647",background:"transparent"});
          document.body.append(frame);
        } catch (error) {update(Object.fromEntries(Object.keys(names).map(id => [id,{state:"attention",detail:error.message}])));}
      })().finally(() => {connecting = null;});
      return connecting;
    }
    connect(); return panel;
  }
  return {mount};
})();
