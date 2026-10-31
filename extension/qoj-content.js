"use strict";
(() => {
  if (globalThis.__qojVpHttp) return;
  globalThis.__qojVpHttp = true;
  const forbidden = /^(cookie2?|user-agent|host|origin|referer|content-length|connection|accept-encoding|sec-.*|proxy-.*|access-control-request-.*)$/i;
  const base64 = bytes => {
    let value = "";
    for (let n = 0; n < bytes.length; n++) value += String.fromCharCode(bytes[n]);
    return btoa(value);
  };
  browser.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== browser.runtime.id) return undefined;
    if (message?.type === "vp.http.ready") return Promise.resolve({ready: true, pageOrigin: location.origin});
    if (message?.type !== "vp.http") return undefined;
    return (async () => {
      const request = message.request;
      if (new URL(request.url).origin !== location.origin || !["GET", "POST"].includes(request.method)) throw new Error("HTTP_ORIGIN_DENIED");
      const headers = {};
      for (const [key, value] of Object.entries(request.headers || {})) if (!forbidden.test(key)) headers[key] = value;
      const options = {method: request.method, credentials: "include", cache: "no-store", headers,
        redirect: request.allowRedirects === false ? "manual" : "follow"};
      if (request.method === "POST") {
        if (!/^\/contest\/\d+\/problem\/\d+(?:\/.*)?$/.test(new URL(request.url).pathname)) throw new Error("SUBMIT_PATH_DENIED");
        const form = new FormData();
        for (const [key, value] of Object.entries(request.data || {})) form.append(key, String(value));
        for (const file of request.files || []) {
          const bytes = Uint8Array.from(atob(file.contentsBase64), value => value.charCodeAt(0));
          if (bytes.length > 512 * 1024) throw new Error("SOURCE_TOO_LARGE");
          form.append(file.field, new Blob([bytes], {type: file.contentType || "text/plain"}), file.filename);
        }
        options.body = form;
      }
      const controller = new AbortController();
      options.signal = controller.signal;
      const timer = setTimeout(() => controller.abort(), Math.max(1000, Math.min(45000, request.timeoutMs || 20000)));
      try {
        const response = await fetch(request.url, options);
        if (response.type === "opaqueredirect") return {opaqueRedirect: true, pageOrigin: location.origin, transport: "content-script-same-origin"};
        if (Number(response.headers.get("content-length") || 0) > 32 * 1024 * 1024) throw new Error("RESPONSE_TOO_LARGE");
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length > 32 * 1024 * 1024) throw new Error("RESPONSE_TOO_LARGE");
        const safeHeaders = {};
        // Firefox content-script Xrays can expose a Headers iterator without
        // making it iterable. Read only the fields the QOJ client needs.
        for (const key of ["content-type", "content-length", "content-disposition", "location", "retry-after", "date", "last-modified"]) {
          const value = response.headers.get(key);
          if (value !== null) safeHeaders[key] = value;
        }
        return {status: response.status, url: response.url, headers: safeHeaders, bodyBase64: base64(bytes),
          redirected: response.redirected, pageOrigin: location.origin, transport: "content-script-same-origin"};
      } finally { clearTimeout(timer); }
    })();
  });
})();
