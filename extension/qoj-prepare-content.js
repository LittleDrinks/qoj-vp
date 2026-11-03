"use strict";
(() => {
  if (globalThis.__qojVpResourcePreparation) return;
  const match = location.pathname.match(/^\/contest\/(\d+)(\/virtual\/register)?\/?$/);
  if (location.origin !== "https://qoj.ac" || !match || window.top !== window) return;
  globalThis.__qojVpResourcePreparation = true;
  const cid = match[1], panelId = "qoj-vp-resource-preparation";
  if (!match[2]) {
    browser.runtime.sendMessage({type:"vp.qoj.checkStart", cid}).catch(() => {});
    return;
  }
  let mountedForm, panel, control, status, registrationPage, busy = false;
  const observed = new WeakSet();
  async function send(type) {
    const response = await browser.runtime.sendMessage({type, cid, ...(registrationPage ? {registrationPage} : {})});
    if (!response?.ok) throw new Error(response?.error?.message || "未能连接工作台，请检查按需助手。");
    return response.result;
  }
  async function prepare(event) {
    event.preventDefault(); event.stopPropagation();
    if (busy) return;
    busy = true; control.disabled = true; status.textContent = "正在关联当前账号与比赛…";
    try { await send("vp.qoj.prepare"); status.textContent = "已打开工作台，正在准备题目文件。"; }
    catch (error) { status.textContent = error.message; }
    finally { busy = false; control.disabled = false; }
  }
  function registrationSnapshot(form) {
    const navigation = document.querySelector('ul.nav.nav-pills.float-right');
    if (!navigation) return null;
    const root = document.createElement('div'), nav = navigation.cloneNode(true), rules = document.createElement('ul');
    nav.querySelectorAll('script,input,textarea').forEach(node => node.remove());
    nav.querySelectorAll('*').forEach(node => {
      for (const attribute of [...node.attributes]) {
        if (!['class','href'].includes(attribute.name)) node.removeAttribute(attribute.name);
      }
    });
    nav.querySelectorAll('a[href]').forEach(link => {
      const target = new URL(link.getAttribute('href'), location.href);
      link.setAttribute('href', target.origin === location.origin ? target.pathname : '#');
    });
    document.querySelectorAll('li').forEach(node => {
      const clean = node.cloneNode(true);
      clean.querySelectorAll('script,input,textarea,style').forEach(child => child.remove());
      const text = clean.textContent.trim().replace(/\s+/g, ' ');
      if (!/^The contest is \d+ minutes long\.$/i.test(text) &&
          !/^(?:本场)?比赛(?:的)?时长(?:为|是|：|:)\s*\d+\s*分钟[。.！!]?$/.test(text)) return;
      const item = document.createElement('li'); item.textContent = text; rules.append(item);
    });
    const copy = document.createElement('form');
    copy.id = form.id; copy.setAttribute('method', 'post'); copy.setAttribute('action', location.pathname);
    const button = document.createElement('button');
    button.id = 'button-submit-register_vp'; button.type = 'submit'; button.name = 'submit-register_vp'; copy.append(button);
    root.append(nav, rules, copy);
    return {url:location.origin + location.pathname, html:root.innerHTML};
  }
  function mount() {
    const form = document.querySelector("form#form-register_vp");
    if (!form) { if (panel?.isConnected) panel.remove(); mountedForm = null; return; }
    let action;
    try { action = new URL(form.getAttribute("action") || location.href, location.href); } catch (_) { return; }
    if ((form.getAttribute("method") || "get").toUpperCase() !== "POST" || action.origin !== "https://qoj.ac" ||
        !new RegExp("^/contest/" + cid + "/virtual/register/?$").test(action.pathname) ||
        !form.querySelector('input[type="hidden"][name="_token"]') ||
        !form.querySelector('button#button-submit-register_vp[type="submit"][name="submit-register_vp"]')) return;
    if (mountedForm === form && panel?.isConnected) return;
    document.getElementById(panelId)?.remove(); mountedForm = form;
    registrationPage = registrationSnapshot(form);
    if (registrationPage) send('vp.qoj.registration').catch(() => {});
    if (!observed.has(form)) {
      // Observe the original submit without cancelling, replacing or retrying it.
      form.addEventListener("submit", () => { send("vp.qoj.startIntent").catch(() => {}); }, true);
      observed.add(form);
    }
    panel = document.createElement("div"); panel.id = panelId; panel.className = "mt-3 mb-3";
    control = document.createElement("button"); control.type = "button"; control.className = "btn btn-primary btn-sm";
    control.textContent = "准备比赛文件并打开工作台"; control.addEventListener("click", prepare);
    status = document.createElement("p"); status.className = "small text-muted mt-2 mb-0";
    status.textContent = "点击原站 Start! 后，工作台会自动开始本场比赛。";
    status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    panel.append(control, status); form.after(panel);
  }
  mount();
  if (document.body) new MutationObserver(mount).observe(document.body, {subtree:true, childList:true});
})();
