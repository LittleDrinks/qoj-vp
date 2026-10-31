"use strict";

let downloadUrl = null;
let lastResult = null;
const output = document.getElementById("result");
const health = document.getElementById("health");

function showResult(value) {
  lastResult = value;
  const display = JSON.parse(JSON.stringify(value));
  if (display.samples?.zipBase64) display.samples.zipBase64 = `[${display.samples.zipBase64.length} base64 characters; download link below]`;
  output.textContent = JSON.stringify(display, null, 2);
  const link = document.getElementById("download");
  if (downloadUrl) { URL.revokeObjectURL(downloadUrl); downloadUrl = null; }
  link.hidden = true;
  if (value.samples?.zipBase64) {
    const bytes = Uint8Array.from(atob(value.samples.zipBase64), char => char.charCodeAt(0));
    downloadUrl = URL.createObjectURL(new Blob([bytes], {type: "application/zip"}));
    link.href = downloadUrl;
    link.download = value.samples.zipFilename;
    link.hidden = false;
  }
}

async function run(method, args = {}) {
  try {
    const result = await browser.runtime.sendMessage({type: "preflight.run", method, args});
    showResult(result);
    if (method === "hello") {
      health.textContent = `已连接。助手 PID ${result.helperPid}，本任务原生连接已关闭。`;
      health.className = "ok";
    }
    return result;
  } catch (error) {
    output.textContent = `${error.name}: ${error.message}`;
    if (method === "hello") { health.textContent = error.message; health.className = "error"; }
    throw error;
  }
}

async function diagnostics(args = {}) {
  const result = await browser.runtime.sendMessage({type: "preflight.diagnostics", args});
  showResult(result);
  return result;
}

window.preflight = Object.freeze({run, diagnostics, get lastResult() { return lastResult; }, version: 2});

function qojArgs() {
  const args = {contestId: document.getElementById("contest").value.trim(), problemLabel: document.getElementById("problem").value.trim(), includeZip: true};
  const fixtureOrigin = document.getElementById("fixture").value.trim();
  if (fixtureOrigin) args.fixtureOrigin = fixtureOrigin;
  return args;
}

document.getElementById("hello").addEventListener("click", () => run("hello", {pageUrl: location.href}).catch(() => {}));
document.getElementById("create-session").addEventListener("click", () => run("create_session", {contestId: document.getElementById("contest").value.trim(), startAt: Date.now() - 2 * 60 * 60 * 1000}).catch(() => {}));
document.getElementById("list-sessions").addEventListener("click", () => run("list_sessions").catch(() => {}));
document.getElementById("read-samples").addEventListener("click", () => run("qoj_contest_and_sample", qojArgs()).catch(() => {}));
document.getElementById("read-form").addEventListener("click", () => run("qoj_problem_form", qojArgs()).catch(() => {}));
run("hello", {pageUrl: location.href}).catch(() => {});
