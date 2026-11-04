/* Test-only network fixture. The upstream application bundle is unmodified.
 * No localStorage writes, Vue state edits, real VP registration or OJ POSTs.
 */
(() => {
  "use strict";
  window.__qojPreflightFixture = {
    kind: "synthetic-srk-with-unmodified-upstream-renderer",
    contestKey: "qoj-preflight-fixture",
    upstreamAsset: "index-0d94beba.js",
    upstreamSha256: "47e9ac746c0d36a2aa2d472c5df529c302914c23d8a043f1889a28ea00939065"
  };
  window.__qojPreflightNetwork = [];
  function record(method, url, target) {
    window.__qojPreflightNetwork.push({method, url: String(url), target});
  }
  function fixturePath(url) {
    const path = new URL(url, location.href).pathname;
    if (/\/api\/v2\/public\/contests\/[^/]+$/.test(path)) return "/contest.json";
    if (/\/api\/v2\/public\/files\/[^/]+$/.test(path)) return "/file.json";
    if (/\/api\/v2\/public\/collections\/official$/.test(path)) return "/collection.json";
    if (/\/api\/v2\/public\/contests$/.test(path)) return "/contests.json";
    return null;
  }
  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    const u = new URL(url, location.href);
    const mapped = fixturePath(url);
    if (String(method).toUpperCase() !== "GET") {
      throw new Error("Preflight fixture blocks non-GET XMLHttpRequest: " + method);
    }
    const target = mapped || (u.origin === location.origin ? u.href : "/unexpected-fixture-request");
    record(String(method), url, target);
    return originalOpen.call(this, method, target, ...rest);
  };
  const originalFetch = window.fetch.bind(window);
  window.fetch = function(input, init = {}) {
    const raw = typeof input === "string" ? input : input.url;
    const url = new URL(raw, location.href);
    const method = String(init.method || (input && input.method) || "GET").toUpperCase();
    if (url.pathname === "/api/vp-presence") {
      record(method, raw, "synthetic-presence-response");
      return Promise.resolve(new Response(JSON.stringify({count: 0, online: 0}), {
        headers: {"Content-Type": "application/json"}
      }));
    }
    if (method !== "GET") {
      return Promise.reject(new Error("Preflight fixture blocks non-GET fetch: " + method));
    }
    if (/\/rankland\/vin\.txt$/.test(url.pathname)) {
      record(method, raw, "empty-fixture-notice");
      return Promise.resolve(new Response("", {headers: {"Content-Type": "text/plain"}}));
    }
    const mapped = fixturePath(raw);
    if (mapped) {
      record(method, raw, mapped);
      return originalFetch(mapped, init);
    }
    if (url.origin !== location.origin) {
      record(method, raw, "blocked-external-fixture-request");
      return Promise.resolve(new Response("Fixture blocks external requests", {status: 503}));
    }
    record(method, raw, url.pathname);
    return originalFetch(input, init);
  };
})();
