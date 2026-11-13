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
  let mountedForm, panel, registrationPage;
  async function send(type) {
    const response = await browser.runtime.sendMessage({type, cid, ...(registrationPage ? {registrationPage} : {})});
    if (!response?.ok) throw new Error(response?.error?.message || "未能连接工作台，请检查按需助手。");
    return response.result;
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
    panel = VpReadyPanel.mount({form, panelId, send});
  }
  mount();
  if (document.body) new MutationObserver(mount).observe(document.body, {subtree:true, childList:true});
})();
