"use strict";
(() => {
  if (globalThis.__qojVpPdfContent) return;
  globalThis.__qojVpPdfContent = true;
  const SELECTOR = "div.tab-pane.active > article.uoj-article.top-buffer-md";
  const ATTR = {path: "data-qoj-vp-pdf-path", root: "data-qoj-vp-pdf-article",
    hide: "data-qoj-vp-pdf-hidden", title: "data-qoj-vp-pdf-title"};
  let active = null;

  function credentialKey(raw) {
    const key = raw.normalize("NFKC").toLowerCase().replace(/[^a-z0-9]/g, "");
    return /token|csrf|session|password|passwd|credential/.test(key) ||
      (key.includes("auth") && !/^author(?:id|name)?$/.test(key)) ||
      /^(?:sid|phpsessid|jsessionid|apikey|accesskey|secretkey)$/.test(key);
  }
  function credentialHref(raw) {
    try {
      const url = new URL(raw, document.baseURI);
      if (url.username || url.password) return true;
      let found = false;
      url.searchParams.forEach((_value, key) => { if (credentialKey(key)) found = true; });
      // Fragments can carry the same query-shaped access/session credentials.
      const fragment = url.hash.slice(1);
      if (fragment.includes("=")) {
        const query = fragment.includes("?") ? fragment.slice(fragment.indexOf("?") + 1) : fragment;
        new URLSearchParams(query).forEach((_value, key) => { if (credentialKey(key)) found = true; });
      }
      return found;
    } catch (_) { return false; }
  }
  function rememberAttribute(state, element, name) {
    let names = state.attributes.get(element);
    if (!names) { names = new Map(); state.attributes.set(element, names); }
    if (!names.has(name)) names.set(name, element.getAttribute(name));
  }
  function mark(state, element, name) {
    rememberAttribute(state, element, name);
    element.setAttribute(name, state.mark);
  }
  function sanitizeLinks(state) {
    for (const link of Array.from(state.article.querySelectorAll("[*|href]"))) {
      const unsafe = Array.from(link.attributes).filter(attribute => attribute.localName === "href" && credentialHref(attribute.value));
      if (!unsafe.length) continue;
      if (!state.links.has(link)) {
        // Sensitive values stay only in this isolated-world closure. They are
        // never copied into data attributes, messages, diagnostics or storage.
        state.links.set(link, new Map());
        const computed = getComputedStyle(link);
        const appearance = {};
        for (const property of ["color", "text-decoration-line", "text-decoration-style", "text-decoration-color",
          "font-family", "font-size", "font-style", "font-weight", "line-height", "cursor"]) appearance[property] = computed.getPropertyValue(property);
        rememberAttribute(state, link, "style");
        // Removing href must not change the visible link's ordinary appearance.
        for (const [property, value] of Object.entries(appearance)) if (value) link.style.setProperty(property, value, "important");
      }
      for (const attribute of unsafe) {
        const key = (attribute.namespaceURI || "") + ":" + attribute.localName;
        const saved = state.links.get(link);
        if (!saved.has(key)) saved.set(key, {name: attribute.name, localName: attribute.localName,
          namespace: attribute.namespaceURI, value: attribute.value});
        if (attribute.namespaceURI) link.removeAttributeNS(attribute.namespaceURI, attribute.localName);
        else link.removeAttribute(attribute.name);
      }
    }
  }
  function restore(state) {
    state.observer?.disconnect();
    state.title?.remove();
    for (const [link, names] of state.links) {
      for (const attribute of names.values()) {
        if (attribute.namespace) link.setAttributeNS(attribute.namespace, attribute.name, attribute.value);
        else link.setAttribute(attribute.name, attribute.value);
      }
    }
    let restoredAttributes = 0;
    for (const [element, names] of state.attributes) {
      for (const [name, value] of names) {
        if (value === null) element.removeAttribute(name); else element.setAttribute(name, value);
        restoredAttributes++;
      }
    }
    document.title = state.documentTitle;
    const result = {ok: true, restored: true, active: false, restoredLinks: state.links.size,
      restoredAttributes, titleRemoved: !state.title?.isConnected};
    if (active === state) active = null;
    return result;
  }
  function validLocation(expected) {
    try {
      const url = new URL(expected);
      const allowed = (url.protocol === "https:" && url.hostname === "qoj.ac") ||
        (url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname));
      return allowed && !url.username && !url.password && url.origin === location.origin &&
        /^\/contest\/\d+\/problem\/\d+(?:\/|$)/.test(url.pathname) &&
        location.pathname.startsWith(url.pathname);
    } catch (_) { return false; }
  }
  function prepare(message) {
    if (active) return {ok: false, code: "PDF_ALREADY_PREPARED"};
    if (message.stylesheetReady !== true) return {ok: false, code: "PDF_STYLESHEET_MISSING"};
    if (!validLocation(message.expectedUrl) || typeof message.requestId !== "string" || !message.requestId) return {ok: false, code: "PDF_LOCATION_INVALID"};
    const articles = Array.from(document.querySelectorAll(SELECTOR));
    if (articles.length !== 1) return {ok: false, code: "PDF_STATEMENT_NOT_UNIQUE", articleCount: articles.length};
    const article = articles[0];
    if (!article.getClientRects().length || !article.textContent.trim()) return {ok: false, code: "PDF_STATEMENT_NOT_READY"};
    const name = String(message.problemName || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 300);
    const label = String(message.problemLabel || "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 32);
    if (!name) return {ok: false, code: "PDF_TITLE_MISSING"};
    const state = {id: message.requestId, mark: crypto.randomUUID().replace(/-/g, ""), article,
      links: new Map(), attributes: new Map(), documentTitle: document.title, title: null, observer: null};
    active = state;
    try {
      let branch = article, ancestors = 0, siblings = 0;
      mark(state, article, ATTR.root);
      while (branch !== document.body) {
        const parent = branch.parentElement;
        if (!parent) throw new Error("PDF_STATEMENT_DETACHED");
        mark(state, parent, ATTR.path); ancestors++;
        for (const sibling of Array.from(parent.children)) if (sibling !== branch) { mark(state, sibling, ATTR.hide); siblings++; }
        branch = parent;
      }
      const titleText = (label ? label + ". " : "") + name;
      state.title = document.createElement("h1");
      state.title.setAttribute(ATTR.title, state.mark);
      state.title.style.setProperty("display", "none", "important");
      state.title.textContent = titleText;
      article.prepend(state.title);
      document.title = titleText;
      sanitizeLinks(state);
      state.observer = new MutationObserver(() => { if (active === state) sanitizeLinks(state); });
      state.observer.observe(article, {subtree: true, childList: true, attributes: true, attributeFilter: ["href"]});
      return {ok: true, prepared: true, articleCount: 1, ancestorCount: ancestors,
        hiddenSiblingCount: siblings, sanitizedLinkCount: state.links.size, titleAdded: true};
    } catch (_) {
      restore(state);
      return {ok: false, code: "PDF_PREPARE_FAILED"};
    }
  }
  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id) return undefined;
    if (message?.type === "vp.pdf.prepare") return Promise.resolve(prepare(message));
    if (message?.type === "vp.pdf.restore") {
      if (!active) return Promise.resolve({ok: true, restored: true, active: false, restoredLinks: 0, restoredAttributes: 0});
      if (active.id !== message.requestId) return Promise.resolve({ok: false, code: "PDF_REQUEST_MISMATCH"});
      return Promise.resolve(restore(active));
    }
    return undefined;
  });
})();
