/* Exercise the actual UI resource functions against their native contract. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {webcrypto, createHash} = require("node:crypto");

const source = fs.readFileSync(path.join(__dirname, "../extension/ui.js"), "utf8");
class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.dataset = {};
    this.attributes = {}; this.listeners = {}; this.className = ""; this.textContent = "";
    this.classList = {
      add: name => this.toggleClass(name, true), remove: name => this.toggleClass(name, false),
      toggle: (name, value) => this.toggleClass(name, value), contains: name => this.className.split(/\s+/).includes(name),
    };
  }
  toggleClass(name, value) { const classes = this.className.split(/\s+/).filter(x => x && x !== name); if (value) classes.push(name); this.className = classes.join(" "); }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  get firstChild() { return this.children[0]; }
}
const ids = Object.fromEntries(["problems-list", "problemset-title", "resources-list", "resources-summary", "resources-error", "prepare-resources", "refresh-resources"].map(id => [id, new Element("div")]));
const walk = element => typeof element === "string" ? [] : [element, ...element.children.flatMap(walk)];
const text = element => typeof element === "string" ? element : element.textContent + element.children.map(text).join("");
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const payload = Buffer.alloc(400000); for (let index = 0; index < payload.length; index++) payload[index] = index % 251;
const entry = id => ({problemId: id, status: "ready", kind: "samples", resourceId: sha(payload), filename: "samples-" + id + ".zip", totalBytes: payload.length, sha256: sha(payload), sampleCount: 1, pairCount: 1, sampleSource: "attachment", lastAttempt: {status: "ready"}});
const state = {session: {sessionId: "session-1", account: "LittleDrinks", contestId: "1051", state: "prepared", startAt: null}, generation: 1,
  contest: {name: "Xian", problems: [{id: "1", label: "A", name: "Bridge"}, {id: "2", label: "B", name: "Cells Coloring"}, {id: "3", label: "C", name: "Clone Ranran"}]},
  resources: new Map(), resourceActivity: new Map(), resourceInteractive: new Map(), resourceDownloads: new Set(), resourceJob: null,
  resourcesLoaded: false, resourceManifestError: "", resourceSummary: "", resourceReadSequence: 0, resourceMutation: 0};
let calls = [], downloads = [], modalShows = 0, handler;
const context = {state, crypto: webcrypto, Blob, atob, MAX_RESOURCE_BYTES: 67108864, RESOURCE_CHUNK_BYTES: 262144,
  document: {createElement: tag => new Element(tag)},
  $: id => ids[id] || Object.values(ids).flatMap(walk).find(element => element.id === id),
  current: (sessionId, generation) => state.session.sessionId === sessionId && state.generation === generation,
  problemById: id => state.contest.problems.find(problem => problem.id === String(id)), contestName: contest => contest.name,
  cardSubmit: () => new Element("a"), problemUrl: problem => "https://qoj.ac/problem/" + problem.id,
  regularClick: () => true, downloadPdf: () => {}, humanReadableBytes: bytes => bytes + " B",
  showMessage: (target, message) => {target.textContent = message; target.classList.remove("d-none");},
  hideMessage: target => {target.textContent = ""; target.classList.add("d-none");}, message: error => error.message,
  modals: {resources: {show: () => modalShows++}},
  call: async (method, args) => {calls.push({method, args}); return handler(method, args);},
  saveBlob: (blob, filename) => downloads.push({blob, filename}),
};
vm.createContext(context);
for (const [begin, end] of [["  function node(", "  function showMessage("], ["  function actionBusy(", "  function regularClick("], ["  function badge(", "  function contestName("], ["  function renderProblems(", "  function isProblemsRoute("], ["  function interactiveResource(", "  function saveBlob("]]) {
  vm.runInContext(source.slice(source.indexOf(begin), source.indexOf(end)), context);
}
function reset() {
  calls = []; downloads = []; modalShows = 0; state.resources.clear(); state.resourceActivity.clear(); state.resourceInteractive.clear(); state.resourceDownloads.clear();
  state.resourceJob = null; state.resourcesLoaded = false; state.resourceReading = false; state.resourceManifestError = ""; state.resourceSummary = "";
  state.session.sessionId = "session-1"; state.generation = 1; state.resourceReadSequence = 0; state.resourceMutation = 0;
}
function chunk(args) {
  const bytes = payload.subarray(args.offset, args.offset + args.maxBytes);
  return {problemId: args.problemId, resourceId: args.resourceId, offset: args.offset, bytesBase64: bytes.toString("base64"), nextOffset: args.offset + bytes.length,
    eof: args.offset + bytes.length === payload.length, totalBytes: payload.length, sha256: sha(payload), chunkSha256: sha(bytes)};
}
async function download() { await context.downloadResource(state.contest.problems[0], new Element("a")); }
const results = [];
async function check(name, test) { reset(); await test(); results.push(name); }
(async () => {
  await check("pending manifest disables real preparation and clears only after read", async () => {
    let resolve;
    handler = method => { assert.equal(method, "resource_manifest"); return new Promise(done => resolve = done); };
    const loading = context.loadResourceManifest();
    assert.equal(state.resourceReading, true);
    assert.equal(ids['prepare-resources'].disabled, true);
    assert.ok(walk(ids['resources-list']).filter(element => element.tagName === 'BUTTON').every(element => element.disabled));
    await context.prepareResources(["1"]); assert.equal(calls.length, 1);
    resolve({origin:"https://qoj.ac",account:"LittleDrinks",contestId:"1051",problems:[]});
    await loading; assert.equal(state.resourceReading, false); assert.equal(ids['prepare-resources'].disabled, false);
  });
  await check("manifest is offline, scoped, and ready-only card controls", async () => {
    handler = method => { assert.equal(method, "resource_manifest"); return {origin: "https://qoj.ac", account: "LittleDrinks", contestId: "1051", problems: [entry("1"), {...entry("2"), kind: "attachment"}, {problemId: "3", status: "unknown"}]}; };
    await context.loadResourceManifest();
    const controls = walk(ids["problems-list"]).filter(element => element.dataset.resourceProblem);
    assert.equal(controls.length, 2); assert.equal(controls[0].getAttribute("href"), null); assert.equal(controls[0].tabIndex, 0);
    assert.match(text(controls[0]), /samples/); assert.match(text(controls[1]), /附件/); assert.equal(calls.length, 1);
  });
  await check("prepared session downloads two verified cached chunks without HTTP", async () => {
    state.resources.set("1", entry("1")); handler = (method, args) => {assert.equal(method, "resource_chunk"); assert.equal(args.maxBytes, 262144); return chunk(args);};
    await download(); assert.equal(calls.length, 2); assert.equal(downloads.length, 1);
    assert.deepEqual(Buffer.from(await downloads[0].blob.arrayBuffer()), payload);
  });
  for (const [name, mutate] of [["bad chunk hash", result => result.chunkSha256 = "0".repeat(64)], ["nonmonotonic offset", result => result.nextOffset--], ["early EOF", result => result.eof = true], ["identity mismatch", result => result.resourceId = "f".repeat(64)]]) {
    await check(name + " prevents every download", async () => {
      state.resources.set("1", entry("1")); handler = (_, args) => {const result = chunk(args); mutate(result); return result;};
      await download(); assert.equal(downloads.length, 0); assert.equal(modalShows, 1); assert.ok(state.resourceManifestError);
    });
  }
  await check("bad full-package hash prevents download after good chunks", async () => {
    const changed = {...entry("1"), sha256: "f".repeat(64)}; state.resources.set("1", changed);
    handler = (_, args) => ({...chunk(args), sha256: changed.sha256}); await download(); assert.equal(calls.length, 2); assert.equal(downloads.length, 0);
  });
  await check("64-MiB ceiling is checked before allocation or native read", async () => {
    state.resources.set("1", {...entry("1"), totalBytes: 67108865}); await download(); assert.equal(calls.length, 0); assert.equal(downloads.length, 0);
  });
  await check("prepare is serial and reuses ready entries until explicit refresh", async () => {
    state.resources.set("1", entry("1")); let active = 0, maximum = 0;
    handler = async (method, args) => { assert.equal(method, "prepare_resource"); active++; maximum = Math.max(active, maximum); await new Promise(setImmediate); active--; return entry(args.problemId); };
    await context.prepareResources(); assert.deepEqual(calls.map(call => call.args.problemId), ["2", "3"]); assert.equal(maximum, 1);
    calls = []; await context.prepareResources(undefined, true); assert.deepEqual(calls.map(call => call.args.problemId), ["1", "2", "3"]);
  });
  await check("failed refresh preserves old good and reports unconfirmed attempt", async () => {
    const good = entry("1"); state.resources.set("1", good); handler = () => ({...good, lastAttempt: {status: "unknown", code: "HTTP_404"}});
    await context.prepareResources(["1"], true); assert.equal(context.readyResource("1").resourceId, good.resourceId);
    assert.match(text(ids["resources-list"]), /保留旧包/); assert.match(state.resourceSummary, /新准备 0.*未确认 1/);
  });
  await check("explicit interactive hint blocks old inline cache and is sent on prepare", async () => {
    state.resources.set("1", {...entry("1"), sampleSource: "inline-statement"}); state.resourceInteractive.set("1", true);
    await download(); assert.equal(calls.length, 0); handler = (_, args) => {assert.equal(args.interactiveHint, true); return {problemId: "1", status: "unknown"};};
    await context.prepareResources(["1"]); assert.equal(context.readyResource("1"), null);
  });
  await check("wrong manifest account and stale session responses are rejected", async () => {
    handler = () => ({origin: "https://qoj.ac", account: "Other", contestId: "1051", problems: [entry("1")]});
    await context.loadResourceManifest(); assert.equal(state.resources.size, 0); assert.match(state.resourceManifestError, /不一致/);
    state.resourceManifestError = ""; handler = async () => {state.generation++; return {origin: "https://qoj.ac", account: "LittleDrinks", contestId: "1051", problems: [entry("1")]};};
    await context.loadResourceManifest(); assert.equal(state.resources.size, 0);
  });
  await check("session switch during transfer never saves a stale file", async () => {
    state.resources.set("1", entry("1")); handler = (_, args) => {state.generation++; return chunk(args);};
    await download(); assert.equal(downloads.length, 0);
  });
  await check("keyboard, modifier clicks and busy guard only invoke cache downloads", async () => {
    state.resources.set("1", entry("1")); handler = (_, args) => chunk(args); context.renderProblems();
    const control = walk(ids["problems-list"]).find(element => element.dataset.resourceProblem === "1");
    let transfer; const originalDownload = context.downloadResource;
    context.downloadResource = (...args) => (transfer = originalDownload(...args));
    for (const [type, attributes] of [["click", {ctrlKey: true}], ["auxclick", {button: 1}], ["keydown", {key: "Enter"}], ["keydown", {key: " "}]]) {
      let prevented = false; control.listeners[type]({button: 0, repeat: false, ...attributes, preventDefault: () => prevented = true});
      await transfer;
      assert.equal(prevented, true); assert.equal(state.resourceDownloads.size, 0);
    }
    assert.equal(downloads.length, 4); assert.ok(calls.every(call => call.method === "resource_chunk"));
    const before = calls.length; control.setAttribute("aria-disabled", "true"); control.listeners.click({preventDefault() {}}); assert.equal(calls.length, before);
  });
  console.log(JSON.stringify({pass: true, count: results.length, cases: results}));
})().catch(error => {console.error(error); process.exitCode = 1;});
