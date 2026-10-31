"use strict";
globalThis.VpTransport = (() => {
  const pending = new Map();
  const requests = new Map();
  const observations = [];
  const filters = {urls: ["https://qoj.ac/*", "http://127.0.0.1/*", "http://localhost/*"]};
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  function approved(raw) {
    const url = new URL(raw);
    return !url.username && !url.password && ((url.protocol === "https:" && url.hostname === "qoj.ac") ||
      (url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname)));
  }
  // An observational hook supplies the actual HTTP status/Location hidden by
  // Fetch's opaque manual redirect. It never changes a header or a response.
  browser.webRequest.onBeforeSendHeaders.addListener(details => {
    const header = (details.requestHeaders || []).find(item => item.name.toLowerCase() === "x-qoj-vp-request");
    const item = header && pending.get(header.value);
    if (item && item.tabId === details.tabId && item.url === details.url && details.method === "POST") requests.set(details.requestId, item);
  }, filters, ["requestHeaders"]);
  browser.webRequest.onHeadersReceived.addListener(details => {
    const item = requests.get(details.requestId);
    if (!item) return;
    const headers = {};
    for (const header of details.responseHeaders || []) if (/^(location|content-type)$/i.test(header.name)) headers[header.name] = header.value;
    item.observed = {status: details.statusCode, url: details.url, headers};
    const location = Object.entries(headers).find(([name]) => name.toLowerCase() === "location")?.[1];
    observations.push({method: "POST", requestPath: new URL(details.url).pathname, status: details.statusCode,
      locationPath: location ? new URL(location, details.url).pathname : null,
      source: "webRequest-onHeadersReceived", observedAt: Date.now()});
    if (observations.length > 30) observations.shift();
  }, filters, ["responseHeaders"]);
  function clearObservation(item, nonce) {
    pending.delete(nonce);
    for (const [id, found] of requests) if (found === item) requests.delete(id);
  }
  async function ready(tab, origin) {
    let injected = false;
    for (let attempt = 0; attempt < 80; attempt++) {
      try {
        const response = await browser.tabs.sendMessage(tab.id, {type: "vp.http.ready"});
        if (response?.ready && response.pageOrigin === origin) return;
      } catch (_) { /* A newly navigating document may not have a listener yet. */ }
      if (!injected && attempt === 15) {
        const current = await browser.tabs.get(tab.id);
        if (current.status === "complete" && current.url && new URL(current.url).origin === origin) {
          const result = await browser.scripting.executeScript({target: {tabId: tab.id}, files: ["qoj-content.js"]});
          if (result.some(frame => frame.error)) throw new Error("CONTENT_SCRIPT_LOAD_FAILED");
          injected = true;
        }
      }
      await pause(100);
    }
    throw new Error("CONTENT_SCRIPT_UNAVAILABLE");
  }
  async function http(request, task) {
    if (!approved(request.url) || !["GET", "POST"].includes(request.method)) throw new Error("HTTP_ORIGIN_DENIED");
    if (request.method === "POST" && task.method !== "qoj_submit") throw new Error("POST_REQUIRES_EXPLICIT_SUBMIT");
    const origin = new URL(request.url).origin;
    let tab;
    if (task.httpTabId !== undefined) {
      tab = await browser.tabs.get(task.httpTabId);
      if (new URL(tab.url).origin !== origin) throw new Error("HTTP_TAB_ORIGIN_MISMATCH");
    } else {
      tab = (await browser.tabs.query({})).find(item => { try { return new URL(item.url).origin === origin; } catch (_) { return false; } });
      if (!tab) tab = await browser.tabs.create({url: request.url, active: false});
      task.httpTabId = tab.id;
    }
    await ready(tab, origin);
    if (task.finished) throw new Error("TASK_CANCELLED");
    const nonce = crypto.randomUUID();
    const observation = {url: request.url, tabId: tab.id};
    if (request.method === "POST") pending.set(nonce, observation);
    try {
      const outgoing = {...request, headers: {...request.headers}};
      if (request.method === "POST") outgoing.headers["X-Qoj-Vp-Request"] = nonce;
      const response = await browser.tabs.sendMessage(tab.id, {type: "vp.http", request: outgoing});
      if (response?.opaqueRedirect) {
        for (let n = 0; n < 10 && !observation.observed; n++) await pause(100);
        const observed = observation.observed;
        const location = observed && Object.entries(observed.headers).find(([key]) => key.toLowerCase() === "location")?.[1];
        if (!observed || observed.status < 300 || observed.status >= 400 || !location) throw new Error("UNCONFIRMED_REDIRECT");
        return {...observed, bodyBase64: "", transport: "content-script-same-origin", pageOrigin: origin, tabId: tab.id, receiptTransport: "webRequest-observed-headers"};
      }
      if (!response || response.error || !Number.isInteger(response.status)) throw new Error("CONTENT_FETCH_FAILED");
      return {...response, tabId: tab.id};
    } finally { clearObservation(observation, nonce); }
  }
  return Object.freeze({http, pause, diagnostics: () => ({postObservations: observations.map(item => ({...item}))})});
})();
