"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const root = path.join(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "src/firefox/ui.js"), "utf8");
const html = fs.readFileSync(path.join(root, "src/firefox/ui.html"), "utf8");
class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.style = {};
    this.attributes = {}; this.listeners = {}; this.textContent = ""; this.className = "";
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name, enabled) => {
        const names = this.className.split(/\s+/).filter(value => value && value !== name);
        if (enabled) names.push(name); this.className = names.join(" ");
      },
    };
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  reset() { this.resetCount = (this.resetCount || 0) + 1; }
}
const walk = element => typeof element === "string" ? [] : [element, ...element.children.flatMap(walk)];
const currentId = "00000000-0000-4000-8000-000000000001", nextId = "00000000-0000-4000-8000-000000000002", archivedId = "00000000-0000-4000-8000-000000000003";
function environment() {
  const sessions = [
    {sessionId: currentId, contestId: "1051", title: "Xi'an current", state: "running", startAt: new Date().toISOString(), durationMs: 18000000},
    {sessionId: nextId, contestId: "4582", title: "Changchun prepared", state: "prepared", durationMs: 18000000},
    {sessionId: archivedId, contestId: "99", title: "Archived practice", state: "archived", durationMs: 18000000},
  ];
  const state = {sessions, session: sessions[0], connected: true, submitting: false, contest: {id: "1051"}};
  const elements = new Map(), selected = [], actions = [];
  const context = {readinessToken:null,
    URL, state, location: {hash: "#problems"},
    document: {createElement: tag => new Element(tag)},
    $: id => {if (!elements.has(id)) elements.set(id, new Element("div")); return elements.get(id);},
    Option: function (label, value) { const option = new Element("option"); option.textContent = label; option.value = value; return option; },
    renderClock: () => {}, hideMessage: target => { target.textContent = ""; },
    modals: {session: {show: () => actions.push("setup")}},
    selectSession: async id => {selected.push(id); state.session = state.sessions.find(item => item.sessionId === id);}, fail: error => { throw error; },
    bootstrap: {Dropdown: {getInstance: () => ({hide: () => actions.push("hide")})}},
    browser: {runtime: {getURL: resource => "moz-extension://workbench/" + resource}},
  };
  vm.createContext(context);
  for (const [begin, end] of [["  function node(", "  function showMessage("], ["  function epoch(", "  function canSubmit("],
    ["  function regularClick(", "  function safeQojUrl("], ["  function renderNavigation(", "  function renderClock("],
    ["  function isProblemsRoute(", "  async function listSessions("], ["  function openSessionSetup(", "  function readContestId("]]) {
    vm.runInContext(source.slice(source.indexOf(begin), source.indexOf(end)), context);
  }
  return {context, state, elements, selected, actions};
}

test("team Home keeps Submissions and Clarifications while the Jury list owns contest creation", () => {
  const nav = html.slice(html.indexOf("<nav "), html.indexOf("</nav>"));
  const home = html.slice(html.indexOf('<section id="home-view"'), html.indexOf('<section id="problems-view"'));
  const jury = html.slice(html.indexOf('<section id="jury-view"'), html.indexOf('<div id="session-modal"'));
  assert.match(nav, /class="nav-link dropdown-toggle/); assert.match(nav, /fas fa-trophy/);
  assert.doesNotMatch(nav, /<select|id="new-session"/);
  assert.match(nav, /id="nav-jury"[^>]+href="#jury"/); assert.match(nav, /id="nav-team"[^>]+href="#home"/);
  assert.doesNotMatch(home, /id="(?:rankland-settings|open-resources|start-session|finish-session|archive-session|delete-session|new-session)"|teamoverview">Contest/);
  assert.match(home, /id="team-submissions" class="col"/);
  assert.match(home, /id="team-clarifications" class="col"/);
  assert.match(home, /teamoverview">Clarifications/); assert.match(home, /teamoverview">Clarification Requests/);
  assert.match(home, /尚未接入 QOJ 讨论同步/); assert.doesNotMatch(home, /No clarifications\.|No clarification request\./);
  assert.match(jury, /id="jury-contests-table"[\s\S]*id="new-session" class="btn btn-primary"/);
  assert.match(jury, /id="delete-session"/); assert.match(jury, /id="jury-config-form"/);
});

test("trophy renderer preserves selection and archived choices without creation actions", () => {
  const view = environment(), before = JSON.stringify(view.state.sessions);
  view.context.renderNavigation();
  const menu = view.elements.get("session-select"), choices = menu.children.filter(item => item.dataset.sessionId);
  assert.equal(menu.dataset.currentContest, currentId);
  assert.equal(view.elements.get("session-label").textContent, "Xi'an current");
  assert.deepEqual(choices.map(item => item.dataset.sessionId), [nextId, archivedId]);
  assert.ok(choices.every(item => item.tagName === "A" && item.className.includes("dropdown-item")));
  assert.match(choices[1].textContent, /已归档/);
  assert.equal(new URL(choices[0].href).searchParams.get("session"), nextId);
  assert.equal(new URL(choices[0].href).hash, "#problems");
  view.context.renderNavigation(); assert.equal(menu.children.length, 3);
  assert.ok(!walk(menu).some(item => item.id === "new-session"));
  assert.equal(JSON.stringify(view.state.sessions), before);
});

test("creation is available only in Jury with an active helper and no submission", () => {
  const view = environment(); view.state.setupContest = {id: "old"};
  view.context.openSessionSetup(); assert.equal(view.actions.length, 0);
  view.context.location.hash = "#jury"; view.context.openSessionSetup();
  assert.deepEqual(view.actions, ["setup"]); assert.equal(view.selected.length, 0);
  assert.equal(view.context.$("session-form").resetCount, 1); assert.equal(view.state.setupContest, null);
  assert.equal(view.context.$("prepare-session").disabled, true);
  view.state.submitting = true; view.context.openSessionSetup(); assert.equal(view.actions.length, 1);
  view.state.submitting = false; view.state.connected = false; view.context.openSessionSetup(); assert.equal(view.actions.length, 1);
});

test("ordinary trophy activation switches once and modifier clicks keep valid links", () => {
  const view = environment(); view.context.renderNavigation();
  const choice = view.elements.get("session-select").children.find(item => item.dataset.sessionId === nextId);
  let prevented = false;
  choice.listeners.click({button: 0, ctrlKey: true, preventDefault() {prevented = true;}});
  assert.equal(prevented, false); assert.equal(view.selected.length, 0);
  choice.listeners.click({button: 0, preventDefault() {prevented = true;}});
  assert.equal(prevented, true); assert.deepEqual(view.selected, [nextId]); assert.deepEqual(view.actions, ["hide"]);
});

test("Jury trophy links follow their target detail instead of selecting the previous hash again", () => {
  const view = environment(); view.context.location.hash = "#jury/contest/" + currentId; view.context.renderNavigation();
  const choice = view.elements.get("session-select").children.find(item => item.dataset.sessionId === nextId);
  assert.equal(new URL(choice.href).hash, "#jury/contest/" + nextId);
  choice.listeners.click({button: 0, preventDefault() {}});
  assert.equal(view.context.location.hash, "#jury/contest/" + nextId);
  view.context.route(); assert.deepEqual(view.selected, [nextId]);
});

test("routes separate team and Jury views and only valid selected contests show configuration", () => {
  const view = environment(); view.context.route();
  assert.equal(view.context.$("contest-view").hidden, false); assert.equal(view.context.$("jury-view").hidden, true);
  view.context.location.hash = "#jury"; view.context.route();
  assert.equal(view.context.$("contest-view").hidden, true); assert.equal(view.context.$("team-submit-controls").hidden, true);
  assert.equal(view.context.$("jury-view").hidden, false); assert.equal(view.context.$("jury-list-view").hidden, false);
  assert.equal(view.context.$("jury-detail-view").hidden, true);
  view.context.location.hash = "#jury/contest/" + currentId; view.context.route();
  assert.equal(view.context.$("jury-detail-view").hidden, false);
  view.context.location.hash = "#jury/contest/00000000-0000-4000-8000-000000000099"; view.context.route();
  assert.equal(view.context.location.hash, "#jury"); assert.equal(view.selected.length, 0);
});

test("a lost helper or in-flight submit locks switching and creation", () => {
  const view = environment(); view.state.submitting = true; view.context.renderNavigation();
  assert.equal(view.context.$("new-session").disabled, true);
  assert.equal(view.context.$("navbarDropdownContests").getAttribute("aria-disabled"), "true");
  const choice = view.elements.get("session-select").children.find(item => item.dataset.sessionId === nextId);
  choice.listeners.click({button: 0, preventDefault() {}}); assert.equal(view.selected.length, 0);
  view.state.submitting = false; view.state.connected = false; view.context.renderNavigation();
  assert.equal(view.context.$("new-session").disabled, true);
  view.state.connected = true; view.state.session = null; view.state.sessions = []; view.context.renderNavigation();
  assert.equal(view.context.$("empty-state").hidden, false); assert.equal(view.context.$("new-session").disabled, false);
});
