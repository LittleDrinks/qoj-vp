"use strict";
globalThis.VpReadinessBridge = (() => {
  const allowed = new Set(["inspect_session", "resource_manifest", "resource_chunk", "prepare_resource", "import_samples",
    "qoj_problem_form", "update_session", "board.snapshot", "board.prepare", "scoreboard.resolve", "submitter_check", "submitter_bind"]);
  function create({lifecycle, dispatch, runtime = browser.runtime, tabs = browser.tabs, storage = browser.storage.local}) {
    const key = id => "vp-ready-page:" + id;
    function registration(url, cid) {
      const parsed = new URL(url);
      return parsed.origin === "https://qoj.ac" && /^\d{1,20}$/.test(cid) &&
        parsed.pathname.replace(/\/$/, "") === "/contest/" + cid + "/virtual/register";
    }
    async function handle(message, sender) {
      if (sender.id !== runtime.id || !Number.isInteger(sender.tab?.id)) throw new Error("准备检查页面已关闭，请重新打开 QOJ 开始页面。");
      if (message.type === "vp.ready.open") {
        const cid = String(message.cid || "");
        if (sender.frameId !== 0 || !registration(sender.url, cid)) throw new Error("请从 QOJ 开始 VP 页面检查。");
        // Validate and store only the bounded, sanitized registration evidence.
        await lifecycle.registration(message, sender);
        const token = crypto.randomUUID();
        await storage.set({[key(sender.tab.id)]: {token, cid, url: sender.url, evidence: message.registrationPage, at: Date.now()}});
        return {token, url: runtime.getURL("ui.html") + "?ready=" + token};
      }
      const saved = (await storage.get(key(sender.tab.id)))[key(sender.tab.id)];
      const url = new URL(sender.url || "about:blank");
      if (!saved || saved.token !== message.token || sender.frameId === 0 ||
          url.origin + url.pathname !== runtime.getURL("ui.html") || url.searchParams.get("ready") !== saved.token ||
          Date.now() - saved.at > 86400000 || !registration((await tabs.get(sender.tab.id)).url, saved.cid)) {
        throw new Error("准备检查已过期，请刷新 QOJ 开始页面。");
      }
      if (message.method === "connect") {
        const binding = await lifecycle.bind({cid: saved.cid, registrationPage: saved.evidence},
          {...sender, frameId: 0, url: saved.url});
        const snapshot = await dispatch("session_snapshot", {sessionId: binding.sessionId});
        await storage.set({[key(sender.tab.id)]: {...saved, sessionId: binding.sessionId}});
        return snapshot;
      }
      if (!saved.sessionId || !allowed.has(message.method) || message.args?.sessionId !== saved.sessionId) {
        throw new Error("准备操作与当前比赛不一致。");
      }
      const args = {...message.args};
      delete args.httpTabId;
      if (["qoj_problem_form", "prepare_resource"].includes(message.method)) args.httpTabId = sender.tab.id;
      return dispatch(message.method, args);
    }
    return {handle};
  }
  return {create};
})();
