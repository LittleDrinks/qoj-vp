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
  querySelector(selector) { if (selector === "span.btn") return walk(this).find(element => element.tagName === "SPAN" && element.classList.contains("btn")) || null; throw new Error("Unexpected selector " + selector); }
  get firstChild() { return this.children[0]; }
}
const ids = Object.fromEntries(["problems-list", "problemset-title", "problemset-status", "refresh-contest", "resources-list", "resources-summary", "resources-error", "prepare-resources", "refresh-resources", "notice", "manual-samples-error", "manual-samples-replace-group", "manual-samples-replace", "manual-samples-save"].map(id => [id, new Element("div")]));
const walk = element => typeof element === "string" ? [] : [element, ...element.children.flatMap(walk)];
const text = element => typeof element === "string" ? element : element.textContent + element.children.map(text).join("");
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const payload = Buffer.alloc(400000); for (let index = 0; index < payload.length; index++) payload[index] = index % 251;
const entry = id => ({problemId: id, status: "ready", kind: "samples", resourceId: sha(payload), filename: "samples-" + id + ".zip", totalBytes: payload.length, sha256: sha(payload), sampleCount: 1, pairCount: 1, sampleSource: "attachment", lastAttempt: {status: "ready"}});
// Deterministic ZIP fixtures: one ordinary input/answer pair and an independent
// interactor tree. Their actual bytes and filenames must never be interchanged.
const samplesZip = Buffer.from("UEsDBBQAAAAIAAAAIVzve7/PCAAAAAYAAAAOAAAAc2FtcGxlcy1BLzEuaW4z4jJUMOICAFBLAwQUAAAACAAAACFc0Z5nVQQAAAACAAAADwAAAHNhbXBsZXMtQS8xLmFuczPmAgBQSwECFAMUAAAACAAAACFc73u/zwgAAAAGAAAADgAAAAAAAAAAAAAAgAEAAAAAc2FtcGxlcy1BLzEuaW5QSwECFAMUAAAACAAAACFc0Z5nVQQAAAACAAAADwAAAAAAAAAAAAAAgAE0AAAAc2FtcGxlcy1BLzEuYW5zUEsFBgAAAAACAAIAeQAAAGUAAAAAAA==", "base64");
const attachmentZip = Buffer.from("UEsDBBQAAAAIAAAAIVzyWndTGwAAABkAAAAwAAAAYXR0YWNobWVudC1leHRyYXMvcHJvYmxlbS1BL3Rvb2xzL2ludGVyYWN0b3IuY3Bwy8wrUchNzMzT0FSoVihKLSktylMwsFao5QIAUEsBAhQDFAAAAAgAAAAhXPJad1MbAAAAGQAAADAAAAAAAAAAAAAAAIABAAAAAGF0dGFjaG1lbnQtZXh0cmFzL3Byb2JsZW0tQS90b29scy9pbnRlcmFjdG9yLmNwcFBLBQYAAAAAAQABAF4AAABpAAAAAAA=", "base64");
const descriptor = (id, kind) => {
  const bytes = kind === "samples" ? samplesZip : attachmentZip;
  return {...entry(id), kind, resourceId: sha(bytes), totalBytes: bytes.length, sha256: sha(bytes), filename: (kind === "samples" ? "samples" : "attachments") + "-A.zip"};
};
const splitEntry = id => ({...entry(id), kind: "attachment", filename: "legacy-combined-A.zip", downloads: [descriptor(id, "samples"), descriptor(id, "attachment")]});
const state = {session: {sessionId: "session-1", account: "LittleDrinks", contestId: "1051", state: "prepared", startAt: null}, generation: 1,
  contest: {name: "Xian", problems: [{id: "1", label: "A", name: "Bridge"}, {id: "2", label: "B", name: "Cells Coloring"}, {id: "3", label: "C", name: "Clone Ranran"}]},
  resources: new Map(), resourceActivity: new Map(), resourceInteractive: new Map(), resourceDownloads: new Set(), resourceJob: null,
  resourcesLoaded: false, resourceManifestError: "", resourceSummary: "", resourceReadSequence: 0, resourceMutation: 0};
let calls = [], downloads = [], openedSubmits = [], modalShows = 0, handler;
const context = {state, crypto: webcrypto, Blob, atob, URL, MAX_RESOURCE_BYTES: 67108864, RESOURCE_CHUNK_BYTES: 262144,
  document: {createElement: tag => new Element(tag), querySelectorAll: () => Object.values(ids).flatMap(walk).filter(element => element.dataset.resourceProblem)},
  $: id => ids[id] || Object.values(ids).flatMap(walk).find(element => element.id === id),
  current: (sessionId, generation) => state.session.sessionId === sessionId && state.generation === generation,
  problemById: id => state.contest.problems.find(problem => problem.id === String(id)), contestName: contest => contest.name,
  canSubmit: () => true, openSubmit: problemId => openedSubmits.push(problemId), rememberDisplay:()=>{},
  isJuryRoute: () => true, openManualSamples: () => {}, regularClick: () => true, humanReadableBytes: bytes => bytes + " B",
  showMessage: (target, message) => {target.textContent = message; target.classList.remove("d-none");},
  hideMessage: target => {target.textContent = ""; target.classList.add("d-none");}, message: error => error.message,
  modals: {resources: {show: () => modalShows++}, "manual-samples": {hide: () => {}}},
  manualSamplesPayload: async () => ({files: [{name:"1.in",base64:"MQo="},{name:"1.ans",base64:"Mgo="}]}),
  call: async (method, args) => {calls.push({method, args}); return handler(method, args);},
  saveBlob: (blob, filename) => downloads.push({blob, filename}),
};
vm.createContext(context);
for (const [begin, end] of [["  function node(", "  function showMessage("], ["  function submitAvailability(", "  function regularClick("], ["  function safeQojUrl(", "  function badge("], ["  function badge(", "  function contestName("], ["  function renderProblems(", "  function isProblemsRoute("], ["  function interactiveResource(", "  function saveBlob("], ["  async function importManualSamples(", "  // File-size/time formatting"]]) {
  vm.runInContext(source.slice(source.indexOf(begin), source.indexOf(end)), context);
}
function reset() {
  calls = []; downloads = []; openedSubmits = []; modalShows = 0; state.resources.clear(); state.resourceActivity.clear(); state.resourceInteractive.clear(); state.resourceDownloads.clear();
  state.problemCards = new Map(); state.problemCardSession = null;
  state.resourceJob = null; state.resourcesLoaded = false; state.resourceReading = false; state.resourceManifestError = ""; state.resourceSummary = "";
  state.session.sessionId = "session-1"; state.generation = 1; state.manualBusy = false; state.manualSessionId = "session-1"; state.manualProblem = "1"; ids["manual-samples-replace-group"].hidden = true; state.resourceReadSequence = 0; state.resourceMutation = 0;
}
function chunk(args, source = payload) {
  const bytes = source.subarray(args.offset, args.offset + args.maxBytes);
  return {problemId: args.problemId, resourceId: args.resourceId, offset: args.offset, bytesBase64: bytes.toString("base64"), nextOffset: args.offset + bytes.length,
    eof: args.offset + bytes.length === source.length, totalBytes: source.length, sha256: sha(source), chunkSha256: sha(bytes)};
}
const controls = target => walk(ids[target]).filter(element => element.dataset.resourceProblem);
async function download() { await context.downloadResource(state.contest.problems[0], new Element("a")); }
const results = [];
async function check(name, test) { reset(); await test(); results.push(name); }
(async () => {
  await check("manual import success re-enables every real resource-table add button for the next problem", async () => {
    context.renderResourceModal();
    handler = async (method, args) => {
      assert.equal(method, "import_samples"); assert.equal(state.manualBusy, true);
      return {...entry(args.problemId), sampleSource: "manual", downloads: [{...descriptor(args.problemId, "samples"), sampleSource: "manual"}]};
    };
    const event = {preventDefault() {}};
    await context.importManualSamples(event);
    const buttons = walk(ids["resources-list"]).filter(item => item.dataset.manualSamples);
    assert.equal(buttons.length, 3);
    assert.ok(buttons.every(item => item.disabled === false), "the actual rendered add buttons must become enabled after import");
    state.manualProblem = "2";
    await context.importManualSamples(event);
    assert.deepEqual(calls.map(item => item.args.problemId), ["1", "2"]);
    assert.equal(state.resources.get("2").sampleSource, "manual");
    assert.ok(walk(ids["resources-list"]).filter(item => item.dataset.manualSamples).every(item => item.disabled === false));
  });
  await check("failed import also restores resource-table add buttons after an overlapping render", async () => {
    state.resources.set("1", entry("1")); const old = state.resources.get("1");
    handler = async () => {
      context.renderResourceModal();
      assert.ok(walk(ids["resources-list"]).filter(item => item.dataset.manualSamples).every(item => item.disabled === true));
      throw new Error("invalid paired sample files");
    };
    await context.importManualSamples({preventDefault() {}});
    assert.equal(state.resources.get("1"), old);
    assert.equal(state.manualBusy, false);
    assert.ok(walk(ids["resources-list"]).filter(item => item.dataset.manualSamples).every(item => item.disabled === false));
    assert.match(ids["manual-samples-error"].textContent, /invalid paired/);
  });
  await check("statement links open their QOJ problem without a native task or busy handler", async () => {
    context.renderProblems();
    const links = walk(ids["problems-list"]).filter(element => element.dataset.statementProblem);
    assert.equal(links.length, 3);
    for (const link of links) {
      assert.equal(link.href, "https://qoj.ac/contest/1051/problem/" + link.dataset.statementProblem);
      assert.equal(link.target, "_blank");
      assert.equal(link.rel, "noopener noreferrer");
      assert.equal(link.listeners.click, undefined);
      assert.equal(link.getAttribute("aria-disabled"), null);
    }
    assert.equal(calls.length, 0);
  });
  await check("late resource manifests retain the real Submit and statement controls while adding samples", async () => {
    context.renderProblems();
    const card = ids["problems-list"].children[0];
    const submit = walk(card).find(element => element.dataset.submitProblem === "1");
    const visual = submit.querySelector("span.btn"), statement = walk(card).find(element => element.dataset.statementProblem === "1");
    let resolve;
    handler = () => new Promise(done => resolve = done);
    const pending = context.loadResourceManifest();
    resolve({origin:"https://qoj.ac",account:"LittleDrinks",contestId:"1051",problems:[splitEntry("1")]});
    await pending;
    assert.equal(ids["problems-list"].children[0], card);
    assert.ok(walk(card).includes(submit)); assert.ok(walk(card).includes(visual)); assert.ok(walk(card).includes(statement));
    submit.listeners.click({preventDefault() {}}); assert.deepEqual(openedSubmits,["1"]);
    const samples = controls("problems-list")[0];
    handler = () => ({origin:"https://qoj.ac",account:"LittleDrinks",contestId:"1051",problems:[{...splitEntry("1"),helperPid:9876}]});
    await context.loadResourceManifest();
    assert.equal(controls("problems-list")[0], samples,"unchanged cached packages must not detach a focused download link");
    assert.equal(ids["problems-list"].children[0], card); assert.ok(walk(card).includes(submit));
  });
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
  await check("mixed, single and unknown resources expose independent correctly labelled controls", async () => {
    const mixed = splitEntry("1"), single = {...entry("2"), downloads: [descriptor("2", "samples")]};
    handler = () => ({origin: "https://qoj.ac", account: "LittleDrinks", contestId: "1051", problems: [mixed, single, {problemId: "3", status: "unknown", downloads: [descriptor("3", "samples")]}]});
    await context.loadResourceManifest();
    for (const target of ["problems-list", "resources-list"]) {
      assert.deepEqual(controls(target).map(control => [control.dataset.resourceProblem, control.dataset.resourceKind]), [["1", "samples"], ["1", "attachment"], ["2", "samples"]]);
      const [samples, attachment] = controls(target);
      assert.equal(samples.dataset.samplesProblem, "1"); assert.equal(samples.dataset.resourceId, mixed.downloads[0].resourceId); assert.match(text(samples), /samples/);
      assert.equal(attachment.dataset.attachmentProblem, "1"); assert.equal(attachment.dataset.resourceId, mixed.downloads[1].resourceId); assert.match(text(attachment), /附件/);
      assert.equal(samples.className, target === "problems-list" ? "btn btn-secondary" : "btn btn-secondary btn-sm");
    }
    state.resources.set("2", {...entry("2"), downloads: [descriptor("2", "attachment")]});
    context.renderProblems();
    assert.deepEqual(controls("problems-list").filter(control => control.dataset.resourceProblem === "2").map(control => control.dataset.resourceKind), ["attachment"]);
    assert.equal(calls.length, 1);
  });
  await check("both mixed buttons download their own ZIP in parallel with independent busy guards", async () => {
    state.resources.set("1", splitEntry("1")); context.renderProblems();
    const [samples, attachment] = controls("problems-list"), transfers = [], releases = [];
    handler = (method, args) => {
      assert.equal(method, "resource_chunk");
      const bytes = args.resourceId === sha(samplesZip) ? samplesZip : args.resourceId === sha(attachmentZip) ? attachmentZip : null;
      assert.ok(bytes, "legacy combined resource must not be downloaded");
      return new Promise(resolve => releases.push(() => resolve(chunk(args, bytes))));
    };
    const originalDownload = context.downloadResource;
    context.downloadResource = (...args) => {const transfer = originalDownload(...args); transfers.push(transfer); return transfer;};
    try {
      samples.listeners.click({preventDefault() {}});
      assert.equal(samples.getAttribute("aria-busy"), "true");
      assert.notEqual(attachment.getAttribute("aria-disabled"), "true");
      attachment.listeners.click({preventDefault() {}});
      assert.equal(calls.length, 2); assert.equal(state.resourceDownloads.size, 2);
      for (const control of controls("resources-list")) assert.equal(control.getAttribute("aria-disabled"), "true");
      controls("resources-list")[0].listeners.keydown({key: "Enter", repeat: false, preventDefault() {}});
      assert.equal(calls.length, 2, "same descriptor remains deduplicated across card and modal");
      context.renderProblems();
      assert.ok(controls("problems-list").every(control => control.getAttribute("aria-busy") === "true"));
      releases.forEach(release => release()); await Promise.all(transfers);
      assert.equal(downloads.length, 2); assert.equal(state.resourceDownloads.size, 0);
      const bytesByName = new Map(await Promise.all(downloads.map(async download => [download.filename, Buffer.from(await download.blob.arrayBuffer())])));
      assert.deepEqual([...bytesByName.keys()].sort(), ["attachments-A.zip", "samples-A.zip"]);
      assert.deepEqual(bytesByName.get("samples-A.zip"), samplesZip); assert.deepEqual(bytesByName.get("attachments-A.zip"), attachmentZip);
      assert.equal(samples.getAttribute("aria-busy"), null); assert.equal(attachment.getAttribute("aria-busy"), null);
      assert.ok(controls("problems-list").every(control => control.getAttribute("aria-busy") === null && control.getAttribute("aria-disabled") === null), "rerendered controls must become usable after their transfer completes");
    } finally {context.downloadResource = originalDownload;}
  });
  await check("mixed descriptor rejects chunks belonging to the other package", async () => {
    const mixed = splitEntry("1"); state.resources.set("1", mixed);
    handler = (_, args) => chunk(args, attachmentZip);
    await context.downloadResource(state.contest.problems[0], new Element("a"), mixed.downloads[0]);
    assert.equal(downloads.length, 0); assert.equal(calls[0].args.resourceId, mixed.downloads[0].resourceId); assert.ok(state.resourceManifestError);
  });
  await check("declared downloads are validated without falling back to the old combined package", async () => {
    for (const downloads of [[], {}, [descriptor("2", "samples")], [descriptor("1", "samples"), descriptor("1", "samples")], [{...descriptor("1", "attachment"), filename: "../interactor.zip"}]]) {
      handler = () => ({origin: "https://qoj.ac", account: "LittleDrinks", contestId: "1051", problems: [{...entry("1"), downloads}]});
      await context.loadResourceManifest(); assert.equal(state.resources.size, 0); assert.ok(state.resourceManifestError); assert.equal(controls("problems-list").length, 0);
    }
  });
  await check("interactive hint retains verified attachment samples and hides only inline samples", async () => {
    const mixed = splitEntry("1"); state.resources.set("1", mixed); state.resourceInteractive.set("1", true);
    context.renderProblems(); assert.deepEqual(controls("problems-list").map(control => control.dataset.resourceKind), ["samples", "attachment"]);
    mixed.downloads[0].sampleSource = "inline-statement";
    context.renderProblems(); assert.deepEqual(controls("problems-list").map(control => control.dataset.resourceKind), ["attachment"]);
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
