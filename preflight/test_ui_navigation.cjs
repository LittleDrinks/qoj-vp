"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const root = path.join(__dirname, "..");
const source = fs.readFileSync(path.join(root, "extension/ui.js"), "utf8");
const html = fs.readFileSync(path.join(root, "extension/ui.html"), "utf8");

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this.attributes = {}; this.listeners = {}; this.textContent = ""; this.className = "";
    this.classList = {
      toggle: (name, enabled) => {
        const names = this.className.split(/\s+/).filter(value => value && value !== name);
        if (enabled) names.push(name);
        this.className = names.join(" ");
      },
    };
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}

function environment() {
  const sessions = [
    {sessionId: "current", contestId: "1051", title: "Xi'an current", state: "running"},
    {sessionId: "next", contestId: "4582", title: "Changchun prepared", state: "prepared"},
    {sessionId: "archived", contestId: "99", title: "Archived practice", state: "archived"},
  ];
  const state = {sessions, session: sessions[0], connected: true, submitting: false, contest: {id: "1051"}};
  const elements = new Map(), selected = [];
  let hidden = 0;
  const context = {
    URL, state, location: {hash: "#problems"},
    document: {createElement: tag => new Element(tag)},
    $: id => {
      if (!elements.has(id)) elements.set(id, new Element("div"));
      return elements.get(id);
    },
    Option: function (label, value) { const option = new Element("option"); option.textContent = label; option.value = value; return option; },
    renderClock: () => {},
    selectSession: async id => selected.push(id), fail: error => { throw error; },
    bootstrap: {Dropdown: {getInstance: () => ({hide: () => hidden++})}},
    browser: {runtime: {getURL: resource => "moz-extension://workbench/" + resource}},
  };
  vm.createContext(context);
  for (const [begin, end] of [["  function node(", "  function showMessage("],
    ["  function regularClick(", "  function safeQojUrl("], ["  function renderNavigation(", "  function renderClock("]]) {
    vm.runInContext(source.slice(source.indexOf(begin), source.indexOf(end)), context);
  }
  return {context, state, elements, selected, get hidden() { return hidden; }};
}

test("navbar uses the original compact trophy dropdown and moves New contest into the page", () => {
  const nav = html.slice(html.indexOf("<nav "), html.indexOf("</nav>"));
  assert.match(nav, /id="navbarDropdownContests"/);
  assert.match(nav, /class="nav-link dropdown-toggle/);
  assert.match(nav, /fas fa-trophy/);
  assert.match(nav, /dropdown-menu scrollable-menu/);
  assert.doesNotMatch(nav, /<select|id="new-session"/);
  assert.match(html.slice(html.indexOf("<main ")), /id="new-session"/);
});

test("the real navigation renderer preserves current selection and archived choices deterministically", () => {
  const view = environment(), before = JSON.stringify(view.state.sessions);
  view.context.renderNavigation();
  const menu = view.elements.get("session-select");
  assert.equal(menu.dataset.currentContest, "current");
  assert.equal(view.elements.get("session-label").textContent, "Xi'an current");
  const choices = menu.children.filter(item => item.dataset.sessionId);
  assert.deepEqual(choices.map(item => item.dataset.sessionId), ["next", "archived"]);
  assert.ok(choices.every(item => item.tagName === "A" && item.className.includes("dropdown-item")));
  assert.match(choices[1].textContent, /已归档/);
  assert.equal(new URL(choices[0].href).searchParams.get("session"), "next");
  assert.equal(new URL(choices[0].href).hash, "#problems");
  view.context.renderNavigation();
  assert.deepEqual(menu.children.filter(item => item.dataset.sessionId).map(item => item.dataset.sessionId), ["next", "archived"]);
  assert.equal(JSON.stringify(view.state.sessions), before);
});

test("ordinary activation switches once and closes the Bootstrap menu; modifier clicks remain links", async () => {
  const view = environment(); view.context.renderNavigation();
  const choice = view.elements.get("session-select").children.find(item => item.dataset.sessionId === "next");
  assert.ok(choice, "the current native select does not provide a Bootstrap contest link");
  let prevented = 0;
  const event = {button: 0, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, preventDefault: () => prevented++};
  choice.listeners.click(event);
  await new Promise(setImmediate);
  assert.deepEqual(view.selected, ["next"]); assert.equal(prevented, 1); assert.equal(view.hidden, 1);
  choice.listeners.click({...event, ctrlKey: true});
  assert.deepEqual(view.selected, ["next"]); assert.equal(prevented, 1);
});

test("submitting prevents contest switching and no-session state disables the menu", () => {
  const view = environment(); view.state.submitting = true; view.context.renderNavigation();
  const toggle = view.elements.get("navbarDropdownContests");
  assert.ok(toggle);
  assert.equal(toggle.getAttribute("aria-disabled"), "true");
  assert.equal(toggle.getAttribute("tabindex"), "-1");
  const choice = view.elements.get("session-select").children.find(item => item.dataset.sessionId === "next");
  choice.listeners.click({button: 0, preventDefault() {}});
  assert.equal(view.selected.length, 0);
  assert.equal(view.elements.get("new-session").disabled, true);
  view.state.sessions = []; view.state.session = null; view.state.submitting = false;
  view.context.renderNavigation();
  assert.equal(toggle.getAttribute("aria-disabled"), "true");
  assert.equal(view.elements.get("session-label").textContent, "no contest");
  assert.equal(view.elements.get("empty-new-session").disabled, false);
});
