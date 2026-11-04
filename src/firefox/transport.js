"use strict";
globalThis.VpTransport = (() => {
  const pending = new Map();
  const requests = new Map();
  const observations = [];
  const diagnosticKey = "http-post-diagnostics-v1";
  const postAttempts = [];
  const phases = new Set(["created", "tabSelected", "contentReady", "messageDispatched", "beforeObserved",
    "beforeRejected", "beforeBound", "headersObserved", "opaqueReturned", "receiptMissing", "receiptReturned", "httpReturned", "failed"]);
  const codes = new Set(["OBSERVED_REDIRECT", "HTTP_RESPONSE", "HTTP_ORIGIN_DENIED", "POST_REQUIRES_EXPLICIT_SUBMIT",
    "HTTP_TAB_ORIGIN_MISMATCH", "CONTENT_SCRIPT_LOAD_FAILED", "CONTENT_SCRIPT_UNAVAILABLE", "TASK_CANCELLED",
    "UNCONFIRMED_REDIRECT", "CONTENT_FETCH_FAILED", "SUBMIT_PATH_DENIED", "SOURCE_TOO_LARGE", "RESPONSE_TOO_LARGE",
    "CONTENT_FETCH_ABORTED", "BROWSER_BRIDGE_FAILED"]);
  let persistenceLoaded = false, persistenceError = false, pendingWrites = 0;
  let persistenceWrites = Promise.resolve();
  const filters = {urls: ["https://qoj.ac/*", "http://127.0.0.1/*", "http://localhost/*"]};
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const pathOf = raw => { try { return new URL(raw).pathname; } catch (_) { return null; } };
  function locationSummary(headers, url) {
    const location = Object.entries(headers || {}).find(([name]) => name.toLowerCase() === "location")?.[1];
    let target, sameOrigin = false;
    try {
      if (location) { target = new URL(location, url); sameOrigin = target.origin === new URL(url).origin; }
    } catch (_) { /* Invalid Location remains unconfirmed. */ }
    return {locationPresent: Boolean(location), locationPath: target?.pathname || null,
      locationSameOrigin: sameOrigin};
  }
  function diagnosticCopy(row) {
    if (!row || !/^[a-f0-9-]{36}$/i.test(row.diagnosticId || "") || !Array.isArray(row.events) ||
        typeof row.requestPath !== "string" || row.requestPath.length > 1024 || !row.requestPath.startsWith("/") ||
        /[?#\x00-\x1f]/.test(row.requestPath)) return null;
    const result = {diagnosticId: row.diagnosticId, requestPath: row.requestPath, createdAt: row.createdAt,
      phase: phases.has(row.phase) ? row.phase : "created", events: []};
    if (Number.isInteger(row.expectedTabId)) result.expectedTabId = row.expectedTabId;
    if (codes.has(row.finalCode)) result.finalCode = row.finalCode;
    for (const event of row.events.slice(-16)) {
      if (!event || !phases.has(event.phase) || !Number.isFinite(event.at)) continue;
      const safe = {phase: event.phase, at: event.at};
      for (const key of ["observedTabId", "status"]) if (Number.isInteger(event[key])) safe[key] = event[key];
      for (const key of ["tabMatches", "urlMatches", "methodMatches", "locationPresent", "locationSameOrigin", "headersObserved"]) {
        if (typeof event[key] === "boolean") safe[key] = event[key];
      }
      if (event.locationPath === null || (typeof event.locationPath === "string" && event.locationPath.length <= 1024 &&
          event.locationPath.startsWith("/") && !/[?#\x00-\x1f]/.test(event.locationPath))) safe.locationPath = event.locationPath;
      if (codes.has(event.errorCode)) safe.errorCode = event.errorCode;
      result.events.push(safe);
    }
    return result;
  }
  // Safe phase records survive an event-page restart. In-flight network state
  // and nonce bindings stay in memory only and are never restored or retried.
  const persistenceReady = Promise.resolve().then(() => browser.storage.local.get(diagnosticKey)).then(stored => {
    const previous = stored[diagnosticKey];
    const merged = new Map();
    if (previous?.version === 1 && Array.isArray(previous.attempts)) {
      for (const raw of previous.attempts.slice(-30)) {
        const row = diagnosticCopy(raw);
        if (row && Number.isFinite(row.createdAt)) merged.set(row.diagnosticId, row);
      }
    }
    for (const row of postAttempts) merged.set(row.diagnosticId, row);
    postAttempts.splice(0, postAttempts.length, ...[...merged.values()].sort((a, b) => a.createdAt - b.createdAt).slice(-30));
  }).catch(() => { persistenceError = true; }).finally(() => { persistenceLoaded = true; });
  function persistDiagnostics() {
    pendingWrites++;
    persistenceWrites = persistenceWrites.then(() => persistenceReady).then(() => browser.storage.local.set({
      [diagnosticKey]: {version: 1, attempts: postAttempts.map(diagnosticCopy).filter(Boolean)}
    })).catch(() => { persistenceError = true; }).finally(() => { pendingWrites--; });
  }
  function record(diagnostic, phase, details = {}) {
    if (!diagnostic) return;
    diagnostic.phase = phase;
    diagnostic.events.push({phase, at: Date.now(), ...details});
    if (diagnostic.events.length > 16) diagnostic.events.shift();
    persistDiagnostics(); // Storage failure must never change submission behavior.
  }
  function safeErrorCode(error) {
    if (codes.has(error?.message) && !["OBSERVED_REDIRECT", "HTTP_RESPONSE"].includes(error.message)) return error.message;
    return error?.name === "AbortError" ? "CONTENT_FETCH_ABORTED" : "BROWSER_BRIDGE_FAILED";
  }
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
    if (item) {
      const matches = {observedTabId: details.tabId, tabMatches: item.tabId === details.tabId,
        urlMatches: item.url === details.url, methodMatches: details.method === "POST"};
      record(item.diagnostic, "beforeObserved", matches);
      if (matches.tabMatches && matches.urlMatches && matches.methodMatches) {
        requests.set(details.requestId, item);
        record(item.diagnostic, "beforeBound", matches);
      } else record(item.diagnostic, "beforeRejected", matches);
    }
  }, filters, ["requestHeaders"]);
  browser.webRequest.onHeadersReceived.addListener(details => {
    const item = requests.get(details.requestId);
    if (!item) return;
    const headers = {};
    for (const header of details.responseHeaders || []) if (/^(location|content-type)$/i.test(header.name)) headers[header.name] = header.value;
    item.observed = {status: details.statusCode, url: details.url, headers};
    const location = locationSummary(headers, details.url);
    record(item.diagnostic, "headersObserved", {status: details.statusCode, observedTabId: details.tabId,
      tabMatches: details.tabId === item.tabId, urlMatches: details.url === item.url,
      methodMatches: details.method === "POST", ...location});
    observations.push({method: "POST", requestPath: pathOf(details.url), status: details.statusCode,
      locationPath: location.locationPath,
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
  async function performHttp(request, task, diagnostic) {
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
    if (diagnostic) diagnostic.expectedTabId = tab.id;
    record(diagnostic, "tabSelected");
    await ready(tab, origin);
    record(diagnostic, "contentReady");
    if (task.finished) throw new Error("TASK_CANCELLED");
    const nonce = crypto.randomUUID();
    const observation = {url: request.url, tabId: tab.id, diagnostic};
    if (request.method === "POST") pending.set(nonce, observation);
    try {
      const outgoing = {...request, headers: {...request.headers}};
      if (request.method === "POST") outgoing.headers["X-Qoj-Vp-Request"] = nonce;
      record(diagnostic, "messageDispatched");
      const response = await browser.tabs.sendMessage(tab.id, {type: "vp.http", request: outgoing});
      if (response?.opaqueRedirect) {
        record(diagnostic, "opaqueReturned");
        for (let n = 0; n < 10 && !observation.observed; n++) await pause(100);
        const observed = observation.observed;
        const location = observed && Object.entries(observed.headers).find(([key]) => key.toLowerCase() === "location")?.[1];
        if (!observed || observed.status < 300 || observed.status >= 400 || !location) {
          record(diagnostic, "receiptMissing", {headersObserved: Boolean(observed),
            ...(observed ? {status: observed.status, ...locationSummary(observed.headers, observed.url)} : {})});
          throw new Error("UNCONFIRMED_REDIRECT");
        }
        return {...observed, bodyBase64: "", transport: "content-script-same-origin", pageOrigin: origin, tabId: tab.id, receiptTransport: "webRequest-observed-headers"};
      }
      if (!response || response.error || !Number.isInteger(response.status)) throw new Error("CONTENT_FETCH_FAILED");
      return {...response, tabId: tab.id};
    } finally { clearObservation(observation, nonce); }
  }
  async function http(request, task) {
    if (!approved(request.url) || !["GET", "POST"].includes(request.method)) throw new Error("HTTP_ORIGIN_DENIED");
    if (request.method === "POST" && task.method !== "qoj_submit") throw new Error("POST_REQUIRES_EXPLICIT_SUBMIT");
    const diagnostic = request.method === "POST" ? {diagnosticId: crypto.randomUUID(), requestPath: pathOf(request.url),
      createdAt: Date.now(), phase: "created", events: []} : null;
    if (diagnostic) {
      postAttempts.push(diagnostic);
      if (postAttempts.length > 30) postAttempts.shift();
      record(diagnostic, "created");
    }
    try {
      const response = await performHttp(request, task, diagnostic);
      if (diagnostic) {
        diagnostic.finalCode = response.receiptTransport ? "OBSERVED_REDIRECT" : "HTTP_RESPONSE";
        record(diagnostic, response.receiptTransport ? "receiptReturned" : "httpReturned",
          {status: response.status, urlMatches: response.url === request.url,
            ...locationSummary(response.headers, response.url || request.url)});
      }
      return response;
    } catch (error) {
      const errorCode = safeErrorCode(error);
      if (diagnostic) diagnostic.finalCode = errorCode;
      record(diagnostic, "failed", {errorCode});
      throw error;
    }
  }
  return Object.freeze({http, pause, diagnostics: () => ({postObservations: observations.map(item => ({...item})),
    postAttempts: postAttempts.map(diagnosticCopy).filter(Boolean),
    persistence: {loaded: persistenceLoaded, error: persistenceError, pendingWrites}})});
})();
