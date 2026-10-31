"use strict";
(() => {
  if (globalThis.__qojVpResourcePreparation) return;
  const match = location.pathname.match(/^\/contest\/(\d+)\/?$/);
  if (location.origin !== "https://qoj.ac" || !match || window.top !== window) return;
  globalThis.__qojVpResourcePreparation = true;
  const cid = match[1], panelId = "qoj-vp-resource-preparation";
  let panel, prepareButton, openButton, status, mountedForm;
  let busy = false, jobId = null, sessionId = null, statusText = "";
  function render() {
    if (!panel?.isConnected) return;
    prepareButton.disabled = busy; openButton.disabled = busy;
    status.textContent = statusText;
    panel.setAttribute("aria-busy", String(busy));
  }
  async function send(type) {
    const response = await browser.runtime.sendMessage({type, cid, ...(sessionId ? {sessionId} : {})});
    if (!response?.ok) throw new Error(response?.error?.message || "题目文件准备未完成，请稍后重试。");
    return response.result;
  }
  async function prepare(event) {
    event.preventDefault(); event.stopPropagation();
    if (busy) return;
    busy = true; jobId = null; statusText = "正在读取题目文件…"; render();
    try {
      const result = await send("vp.resources.prepareContest");
      sessionId = result.sessionId; jobId = result.jobId;
      statusText = `已检查 ${result.done}/${result.total} · 可用 ${result.ready} · 未确认 ${result.unknown}`;
    } catch (error) { statusText = error.message; }
    finally { busy = false; render(); }
  }
  async function open(event) {
    event.preventDefault(); event.stopPropagation();
    if (busy) return;
    openButton.disabled = true;
    try { await send("vp.resources.openContest"); }
    catch (error) { statusText = error.message; }
    finally { render(); }
  }
  function mount() {
    const form = document.querySelector("form#form-regvir");
    if (!form) {
      if (panel?.isConnected) panel.remove();
      mountedForm = null;
      return;
    }
    let action;
    try { action = new URL(form.getAttribute("action") || location.href, location.href); } catch (_) { return; }
    // Only the exact original form observed on current QOJ is supported.
    // Never guess, click, submit, wrap, disable or rewrite the native form.
    if ((form.getAttribute("method") || "get").toUpperCase() !== "POST" || action.origin !== "https://qoj.ac" ||
        !new RegExp("^/contest/" + cid + "/?$").test(action.pathname) ||
        !form.querySelector('input[type="hidden"][name="_token"]') ||
        !form.querySelector('button#button-submit-regvir[type="submit"][name="submit-regvir"]')) return;
    if (mountedForm === form && panel?.isConnected) return;
    document.getElementById(panelId)?.remove();
    mountedForm = form;
    panel = document.createElement("div"); panel.id = panelId; panel.className = "mt-3";
    prepareButton = document.createElement("button"); prepareButton.type = "button"; prepareButton.className = "btn btn-secondary btn-sm";
    prepareButton.textContent = "准备题目文件"; prepareButton.style.marginRight = ".5rem"; prepareButton.addEventListener("click", prepare);
    openButton = document.createElement("button"); openButton.type = "button"; openButton.className = "btn btn-outline-secondary btn-sm";
    openButton.textContent = "打开题目文件"; openButton.addEventListener("click", open);
    status = document.createElement("p"); status.className = "small text-muted mt-2 mb-0";
    status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    panel.append(prepareButton, openButton, status);
    form.after(panel);
    render();
  }
  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id || message?.type !== "vp.resources.progress" || message.cid !== cid || !busy ||
        typeof message.jobId !== "string" || jobId && jobId !== message.jobId) return undefined;
    jobId = message.jobId;
    if (typeof message.sessionId === "string") sessionId = message.sessionId;
    if ([message.done, message.total, message.ready, message.unknown].every(value => Number.isSafeInteger(value) && value >= 0)) {
      statusText = `已检查 ${message.done}/${message.total} · 可用 ${message.ready} · 未确认 ${message.unknown}`;
      render();
    }
    return undefined;
  });
  mount();
  if (document.body) new MutationObserver(mount).observe(document.body, {subtree: true, childList: true});
})();
