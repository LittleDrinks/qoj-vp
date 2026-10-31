"use strict";

(() => {
  if (globalThis.__qojVpPreflightHttpV2) return;
  globalThis.__qojVpPreflightHttpV2 = true;
  const MAX_FETCH_BYTES = 64 * 1024 * 1024;
  function bytesToBase64(bytes) {
    let binary = "";
    // Use indexed reads: a typed-array iterator obtained through Firefox's
    // content-script Xray is not guaranteed to be iterable in this realm.
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  function safeException(error) {
    const known = new Set(["TypeError", "NetworkError", "AbortError", "SecurityError", "InvalidStateError", "InvalidCharacterError", "RangeError"]);
    const exceptionName = String(error?.name || "Error");
    const raw = typeof error === "string" ? error : typeof error?.message === "string" ? error.message : "";
    const knownWrapperFailure = /^(?:Permission denied to access (?:property|object)|[^\r\n<>]{0,100}(?:is not iterable|iterator is not))/i.test(raw);
    let message = known.has(exceptionName) || knownWrapperFailure ? raw : "Builtin detail unavailable";
    if (/[<>]|cookie|token|password|authorization|csrf|payload|source code/i.test(message)) message = "Builtin detail omitted";
    message = message.replace(/(?:https?|moz-extension|file):\/\/[^\s"'<>]+/gi, "[URL]")
      .replace(/[A-Za-z0-9+/=]{80,}/g, "[LONG_VALUE]").slice(0, 200);
    return {exceptionName, sanitizedBuiltinMessage: message};
  }

  async function runHttp(request, probeOnly) {
    let stage = "request-validation", timer = null;
    const observed = {stage, responseStatus: null, responseType: null,
      declaredBytes: null, headerCount: null, bodyBytes: null, encodedLength: null};
    try {
      if (request.method !== "GET" || new URL(request.url).origin !== location.origin) return {error: {code: "CONTENT_HTTP_ORIGIN_DENIED", stage, message: "Only same-origin GET is enabled"}};
      const headers = {};
      for (const [name, value] of Object.entries(request.headers || {})) {
        const lower = name.toLowerCase();
        if (["user-agent", "cookie", "cookie2", "host", "origin", "referer", "content-length", "connection", "accept-encoding"].includes(lower) || /^(sec-|proxy-|access-control-request-)/.test(lower)) continue;
        headers[name] = value;
      }
      stage = "abort-controller";
      const controller = new AbortController();
      timer = setTimeout(() => controller.abort(), Math.min(30000, Math.max(1000, request.timeoutMs || 20000)));
      stage = "fetch";
      const response = await fetch(request.url, {method: "GET", headers, credentials: "include", redirect: "follow", cache: "no-store", signal: controller.signal});
      observed.responseStatus = response.status;
      observed.responseType = response.type;
      stage = "headers";
      observed.declaredBytes = Number(response.headers.get("content-length") || 0);
      if (observed.declaredBytes > MAX_FETCH_BYTES) return {error: {code: "CONTENT_RESPONSE_TOO_LARGE", stage, message: "Attachment exceeds preflight limit"}};
      const safeHeaders = {};
      let headerCount = 0;
      // Firefox content-script Xray wrappers do not guarantee iterable
      // Headers iterators. Read only the transport contract's explicit fields.
      for (const name of ["content-type", "content-length", "content-disposition", "location", "retry-after", "date", "last-modified"]) {
        const value = response.headers.get(name);
        if (value !== null) {
          headerCount++;
          safeHeaders[name] = value;
        }
      }
      observed.headerCount = headerCount;
      stage = "body-read";
      const bytes = new Uint8Array(await response.arrayBuffer());
      observed.bodyBytes = bytes.length;
      if (bytes.length > MAX_FETCH_BYTES) return {error: {code: "CONTENT_RESPONSE_TOO_LARGE", stage, message: "Attachment exceeds preflight limit"}};
      stage = "body-encode";
      const encoded = bytesToBase64(bytes);
      observed.encodedLength = encoded.length;
      observed.stage = "done";
      if (probeOnly) return {probe: observed, transport: "content-script-same-origin", pageOrigin: location.origin};
      return {status: response.status, url: response.url, headers: safeHeaders, bodyBase64: encoded,
        transport: "content-script-same-origin", pageOrigin: location.origin};
    } catch (error) {
      observed.stage = stage;
      return {error: {code: error.name === "AbortError" ? "CONTENT_FETCH_ABORTED" : "CONTENT_FETCH_FAILED",
        stage, message: "Same-origin browser fetch failed", ...safeException(error)}, probe: observed};
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
  }

  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id) return undefined;
    if (message?.type === "preflight.http.ready") return Promise.resolve({ready: true, pageOrigin: location.origin, version: 2});
    if (!["preflight.http", "preflight.http.probe"].includes(message?.type)) return undefined;
    return runHttp(message.request, message.type === "preflight.http.probe");
  });
})();
