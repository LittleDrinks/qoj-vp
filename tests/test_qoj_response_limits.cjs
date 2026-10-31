"use strict";
// Execute the real production content-script listener. Only HTTP payloads are
// synthetic; no request is sent to QOJ and no product source is transformed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const MiB = 1024 * 1024;
let listener, payload, bodyReads = 0;
const RealUint8Array = Uint8Array;
function PayloadArray(value) {
  // Test an oversized decoded body without allocating 64 MiB just to reject
  // it. Valid body data still uses the real typed array and base64 loop.
  return value?.virtualLength ? {length: value.virtualLength} : new RealUint8Array(value);
}
PayloadArray.from = RealUint8Array.from.bind(RealUint8Array);
const context = vm.createContext({
  browser: {runtime: {id: "qoj-limit-test", onMessage: {addListener(fn) { listener = fn; }}}},
  location: {origin: "https://qoj.ac"}, URL, Uint8Array: PayloadArray, AbortController, FormData, Blob,
  setTimeout, clearTimeout,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  btoa: value => Buffer.from(value, "binary").toString("base64"),
  async fetch() {
    return {type: "basic", status: 200, url: "https://qoj.ac/download.php", redirected: false,
      headers: {get(name) { return name === "content-length" && payload.header !== null ? String(payload.header) : null; }},
      async arrayBuffer() { bodyReads++; return payload.body || new RealUint8Array([65]).buffer; }};
  },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../extension/qoj-content.js"), "utf8"), context);
const invoke = () => listener({type: "vp.http", request: {url: "https://qoj.ac/download.php", method: "GET"}}, {id: "qoj-limit-test"});
(async () => {
  payload = {header: 33 * MiB};
  assert.equal((await invoke()).bodyBase64, "QQ==", "A declared 33 MiB resource must reach the body reader");
  payload = {header: 64 * MiB};
  assert.equal((await invoke()).status, 200, "The documented inclusive 64 MiB boundary must be accepted");
  const before = bodyReads;
  payload = {header: 64 * MiB + 1};
  await assert.rejects(invoke(), /RESPONSE_TOO_LARGE/);
  assert.equal(bodyReads, before, "Oversized declared length must be rejected before reading the body");
  payload = {header: null, body: {virtualLength: 64 * MiB + 1}};
  await assert.rejects(invoke(), /RESPONSE_TOO_LARGE/, "An oversized actual body must be rejected even without a header");
  const source = fs.readFileSync(path.join(__dirname, "../extension/qoj-content.js"), "utf8");
  assert.match(source, /bytes\.length > 512 \* 1024/, "Source upload boundary must remain 512 KiB");
  process.stdout.write(JSON.stringify({checks: 5, productionListener: true, qojRequests: 0, status: "passed"}) + "\n");
})().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
