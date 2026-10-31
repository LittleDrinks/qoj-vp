"use strict";

const NATIVE_HOST = "org.littledrinks.qoj_preflight";
const activeTasks = new Set();

function bridgeError(code, stage, message) {
  const error = new Error(message);
  error.code = code;
  error.details = {code, stage};
  return error;
}

function errorCategory(error) {
  const text = typeof error === "string" ? error : String(error?.message || "");
  if (/permission|cannot access contents|not allowed/i.test(text)) return "HOST_PERMISSION_DENIED";
  if (/Unable to load script|load.*script/i.test(text)) return "EXTENSION_SCRIPT_LOAD_FAILED";
  if (/Receiving end|Could not establish connection/i.test(text)) return "NO_CONTENT_LISTENER";
  if (/tab|frame.*not|document.*unload/i.test(text)) return "TARGET_TAB_UNAVAILABLE";
  return error?.code || "EXTENSION_OPERATION_FAILED";
}

function allowedUrl(raw) {
  const url = new URL(raw);
  if (url.username || url.password) return false;
  return (url.protocol === "https:" && url.hostname === "qoj.ac") ||
    (["http:", "https:"].includes(url.protocol) && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname));
}

async function browserHttp(request, task) {
  if (request.method !== "GET" || !allowedUrl(request.url)) throw bridgeError("HTTP_ORIGIN_DENIED", "request-validation", "Only approved read-only HTTP requests are enabled");
  const origin = new URL(request.url).origin;
  let tab;
  if (task.httpTabId !== undefined) {
    tab = await browser.tabs.get(task.httpTabId);
    if (!tab.url || new URL(tab.url).origin !== origin) throw bridgeError("HTTP_TAB_ORIGIN_MISMATCH", "tab-selection", "httpTabId does not belong to the requested origin");
  } else {
    const tabs = await browser.tabs.query({});
    tab = tabs.find(candidate => {
      try { return new URL(candidate.url).origin === origin; } catch (_) { return false; }
    });
    if (!tab) tab = await browser.tabs.create({url: request.url, active: false});
    task.httpTabId = tab.id;
  }
  // Static content scripts install at document_start. A newly created tab can
  // still be navigating; retry only the connection handshake, never a POST.
  let lastError;
  for (let attempt = 0; attempt < 60; attempt++) {
    if (task.finished) throw new Error("Task was cancelled");
    try {
      const ready = await browser.tabs.sendMessage(tab.id, {type: "preflight.http.ready"});
      if (!ready?.ready) throw bridgeError("CONTENT_READY_INVALID", "ready", "Origin content script is not ready");
      if (ready.pageOrigin !== origin) throw bridgeError("CONTENT_READY_ORIGIN_MISMATCH", "ready", "Content script belongs to a different origin");
      const response = await browser.tabs.sendMessage(tab.id, {type: "preflight.http", request});
      if (!response) throw bridgeError("CONTENT_RESPONSE_EMPTY", "fetch-response", "Origin HTTP response was empty");
      if (response.error) {
        const code = response.error.code || "CONTENT_FETCH_FAILED";
        const error = bridgeError(code, response.error.stage || "content-fetch", response.error.message || "Origin HTTP request failed");
        for (const key of ["exceptionName", "sanitizedBuiltinMessage"]) {
          if (typeof response.error[key] === "string") error.details[key] = response.error[key];
        }
        throw error;
      }
      return {...response, tabId: tab.id};
    } catch (error) {
      lastError = error;
      // Once a content script accepted an HTTP request, its failure is final;
      // do not retry the actual network request behind the caller's back.
      if (!/Receiving end|Could not establish connection|not ready/i.test(error.message)) throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const error = bridgeError("CONTENT_SCRIPT_UNAVAILABLE", "ready", "No listening content script in the original-site tab");
  error.details.causeCode = errorCategory(lastError);
  throw error;
}

async function contentReady(tabId) {
  if (!Number.isInteger(tabId)) return {ok: false, code: "NO_TARGET_TAB"};
  try {
    const value = await browser.tabs.sendMessage(tabId, {type: "preflight.http.ready"});
    return value?.ready ? {ok: true, code: "CONTENT_READY", ...value} : {ok: false, code: "CONTENT_READY_INVALID"};
  } catch (error) {
    return {ok: false, code: errorCategory(error)};
  }
}

async function resourceMetadata(name) {
  try {
    const response = await fetch(browser.runtime.getURL(name), {cache: "no-store"});
    const bytes = await response.arrayBuffer();
    const hash = await crypto.subtle.digest("SHA-256", bytes);
    return {ok: response.ok, status: response.status, bytes: bytes.byteLength,
      sha256: [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, "0")).join("")};
  } catch (error) {
    return {ok: false, status: null, bytes: null, sha256: null, errorCode: errorCategory(error)};
  }
}

async function extensionDiagnostics(args = {}) {
  const manifest = browser.runtime.getManifest();
  const result = {
    schema: "qoj-extension-diag-v1",
    extension: {id: browser.runtime.id, version: manifest.version, manifestVersion: manifest.manifest_version,
      runtimeOrigin: new URL(browser.runtime.getURL("test.html")).origin},
    resources: {}, permissions: await browser.permissions.getAll(), targetTab: null,
  };
  for (const name of ["http-content.js", "background.js", "manifest.json"]) result.resources[name] = await resourceMetadata(name);
  let tab;
  try {
    if (Number.isInteger(args.httpTabId)) tab = await browser.tabs.get(args.httpTabId);
    else if (args.fixtureOrigin) {
      const origin = new URL(args.fixtureOrigin).origin;
      tab = (await browser.tabs.query({})).find(candidate => {
        try { return new URL(candidate.url).origin === origin; } catch (_) { return false; }
      });
    }
    if (tab) result.targetTab = {id: tab.id, origin: new URL(tab.url).origin, status: tab.status, discarded: Boolean(tab.discarded)};
  } catch (error) {
    result.targetError = {code: errorCategory(error)};
  }
  result.readyBefore = await contentReady(tab?.id);
  if (args.probeInjection === true && tab) {
    result.injectionProbes = {};
    // Preserve Firefox's per-frame errors: a fulfilled
    // executeScript Promise alone does not prove that the file ran.
    for (const kind of ["file", "function"]) {
      try {
        let injection;
        if (kind === "file") injection = {target: {tabId: tab.id}, files: ["http-content.js"]};
        else injection = {target: {tabId: tab.id}, args: [browser.runtime.id], func: expectedId => {
          const runtimeId = browser.runtime.id;
          return {probe: "qoj-preflight-function-v4", pageOrigin: location.origin,
            runtimeId, expectedId, runtimeMatchesExpected: runtimeId === expectedId};
        }};
        const values = await browser.scripting.executeScript(injection);
        const frameResults = values.map(value => ({frameId: value.frameId, result: value.result ?? null,
          error: value.error ? {name: value.error.name || "Error", code: errorCategory(value.error)} : null}));
        result.injectionProbes[kind] = {attempted: true, ok: frameResults.every(value => !value.error),
          code: frameResults.some(value => value.error) ? "INJECTION_FRAME_ERROR" : "INJECTION_SUCCEEDED",
          results: frameResults};
      } catch (error) {
        result.injectionProbes[kind] = {attempted: true, ok: false, code: errorCategory(error)};
      }
    }
  }
  result.readyAfter = await contentReady(tab?.id);
  if (args.probeFetch === true && tab) {
    const target = new URL(tab.url);
    if (!["127.0.0.1", "localhost"].includes(target.hostname) || target.protocol !== "http:") {
      throw new Error("Fetch diagnostics are restricted to the explicit loopback fixture");
    }
    result.injectionProbes ||= {};
    try {
      result.injectionProbes.fetch = await browser.tabs.sendMessage(tab.id, {
        type: "preflight.http.probe",
        request: {method: "GET", url: target.origin + "/contest/3387", headers: {}, timeoutMs: 10000},
      });
    } catch (error) {
      result.injectionProbes.fetch = {error: {code: errorCategory(error), stage: "content-message"}};
    }
  }
  return result;
}

function runNative(method, args = {}) {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    let port;
    try { port = browser.runtime.connectNative(NATIVE_HOST); }
    catch (error) { reject(new Error(`Native helper unavailable: ${error.message}`)); return; }
    const task = {id, port, controllers: new Set(), finished: false, httpTabId: Number.isInteger(args.httpTabId) ? args.httpTabId : undefined};
    activeTasks.add(task);
    const finish = (error, result) => {
      if (task.finished) return;
      task.finished = true;
      clearTimeout(deadline);
      for (const controller of task.controllers) controller.abort();
      activeTasks.delete(task);
      try { port.disconnect(); } catch (_) { /* Already closed by native exit. */ }
      if (error) reject(error); else resolve(result);
    };
    const deadline = setTimeout(() => finish(new Error("Preflight task timed out; native port closed")), 90000);
    port.onMessage.addListener(async message => {
      if (task.finished || message.id !== id) return;
      if (message.type === "http.request") {
        let envelope;
        try { envelope = {response: await browserHttp(message.request, task)}; }
        catch (error) {
          const details = error.details || {code: errorCategory(error), stage: "browser-http"};
          envelope = {error: {code: details.code, message: "Browser HTTP bridge failed", details}};
        }
        if (!task.finished) {
          try { port.postMessage({type: "http.response", id, requestId: message.requestId, ...envelope}); }
          catch (error) { finish(new Error("Native helper disconnected during browser HTTP")); }
        }
      } else if (message.type === "result") {
        if (!message.ok) {
          const code = message.error?.details?.code || message.error?.code || "NativeError";
          const error = new Error(`[${code}] ${message.error?.message || "Task failed"}`);
          error.code = code;
          error.details = message.error?.details || null;
          finish(error);
        }
        else finish(null, {...message.result, helperPid: message.pid, taskId: id, nativePortClosed: true});
      }
    });
    port.onDisconnect.addListener(() => {
      if (!task.finished) finish(new Error(port.error?.message || "Native helper exited before returning a result"));
    });
    try { port.postMessage({type: "task", id, method, args}); }
    catch (error) { finish(error); }
  });
}

async function openTestPage() {
  const url = browser.runtime.getURL("test.html");
  const tabs = await browser.tabs.query({url});
  if (tabs.length) await browser.tabs.update(tabs[0].id, {active: true});
  else await browser.tabs.create({url});
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== browser.runtime.id) return undefined;
  if (message?.type === "preflight.diagnostics") return extensionDiagnostics(message.args || {});
  if (message?.type !== "preflight.run") return undefined;
  return runNative(message.method, message.args || {});
});
browser.runtime.onInstalled.addListener(() => openTestPage().catch(() => {}));
browser.action.onClicked.addListener(() => openTestPage().catch(() => {}));
