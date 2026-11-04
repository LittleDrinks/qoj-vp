"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const {reconcile} = require("../../src/firefox/rankland-projection.js");

const key = "RanklandVP2:fixture:local-run:ICPC:50:20:null:0";
const row = (problemIndex, timeMs, result) => ({problemIndex, timeMs, result});
const item = (id, record, revision = 1) => ({sourceId: `qoj:tester:${id}`, revision, record});
const archive = (manual = [], extra = {}) => ({version: 2, elapsed: 5100000,
  savedAt: 1800000000000, running: true, speed: 1, ownName: "Tester",
  ownOrganization: "", manual, ...extra});
const project = (state, desired, ownership = null, extra = {}) =>
  reconcile({targetKey: key, archive: state, desired, ownership, ...extra});
const code = expected => error => error.code === expected;

test("a verdict received five minutes late keeps the original submit time", () => {
  const original = archive([], {elapsed: 85 * 60000});
  const frozen = JSON.stringify(original);
  const result = project(original, [item("101", row(0, 80 * 60000 + 12345, "AC"))]);
  assert.deepEqual(result.manual, [row(0, 80 * 60000 + 12345, "AC")]);
  assert.equal(result.ownership.entries[0].sourceId, "qoj:tester:101");
  assert.equal(result.changed, true);
  assert.equal(result.updatedCount, 1);
  assert.equal(JSON.stringify(original), frozen, "No caller-owned archive state is mutated");
});

test("post-contest backfill preserves ended playback and its clock", () => {
  const original = archive([], {elapsed: 18000000, running: false});
  const frozen = JSON.stringify(original);
  const result = project(original, [item("102", row(0, 17999000, "AC"))]);
  assert.deepEqual(result.manual, [row(0, 17999000, "AC")]);
  assert.equal(JSON.stringify(original), frozen);
});

test("repeated synchronization produces one record with the same source ownership", () => {
  const desired = [item("101", row(0, 4800000, "AC"))];
  const first = project(archive(), desired);
  const second = project(archive(first.manual), desired, first.ownership);
  assert.deepEqual(second.manual, first.manual);
  assert.deepEqual(second.ownership, first.ownership);
  assert.equal(second.changed, false);
  assert.equal(second.updatedCount, 0);
});

test("an AC rejudged to TL replaces its owned record rather than adding a submission", () => {
  const first = project(archive(), [item("101", row(0, 4800000, "AC"))]);
  const next = project(archive(first.manual), [item("101", row(0, 4800000, "TLE"), 3)], first.ownership);
  assert.deepEqual(next.manual, [row(0, 4800000, "TLE")]);
  assert.equal(next.updatedCount, 1);
  assert.equal(next.ownership.entries[0].revision, 3);
});

test("a pending rejudge withdraws only its owned verdict and a later final is reinserted", () => {
  const manual = row(1, 123456, "WA");
  const first = project(archive([manual]), [item("101", row(0, 4800000, "AC"))]);
  const pending = project(archive(first.manual), [], first.ownership);
  assert.deepEqual(pending.manual, [manual]);
  assert.equal(pending.updatedCount, 1);
  const next = project(archive(pending.manual), [item("101", row(0, 4800000, "WA"), 3)], pending.ownership);
  assert.deepEqual(next.manual, [manual, row(0, 4800000, "WA")]);
});

test("distinct submissions in the same second remain distinct attempts", () => {
  const desired = [item("101", row(0, 4800123, "WA")), item("102", row(0, 4800123, "WA")),
    item("103", row(0, 4800999, "AC"))];
  const first = project(archive(), desired);
  assert.equal(first.manual.length, 3);
  assert.deepEqual(first.manual, desired.map(value => value.record));
  assert.deepEqual(first.ownership.entries.map(value => value.index), [0, 1, 2]);
  const again = project(archive(first.manual), desired, first.ownership);
  assert.equal(again.changed, false);
});

test("unowned manually added records, including equal tuples, survive corrections", () => {
  const manual = row(2, 2400000, "WA");
  const first = project(archive([manual, {...manual}]), [item("101", row(0, 4800000, "AC"))]);
  const laterManual = row(3, 4900000, "AC");
  const changed = project(archive([...first.manual, laterManual]),
    [item("101", row(0, 4800000, "TLE"), 2)], first.ownership);
  assert.deepEqual(changed.manual, [manual, manual, laterManual, row(0, 4800000, "TLE")]);
  assert.equal(changed.ownership.entries[0].index, 3);
});

test("an unowned existing matching record is not silently claimed or duplicated", () => {
  assert.throws(() => project(archive([row(0, 4800000, "AC")]),
    [item("101", row(0, 4800000, "AC"))]), code("RANKLAND_UNOWNED_CONFLICT"));
});

test("external deletion, modification, reset, or reordering stops reconciliation", () => {
  const first = project(archive([row(2, 1000, "WA")]), [item("101", row(0, 4800000, "AC"))]);
  for (const manual of [[], [row(2, 1000, "WA")], [row(2, 1000, "WA"), row(0, 4800000, "WA")],
    [first.manual[1], first.manual[0]]]) {
    assert.throws(() => project(archive(manual), [], first.ownership), code("RANKLAND_OWNERSHIP_CONFLICT"));
  }
});

test("legacy exact-index receipts migrate and recover a verified interrupted click", () => {
  for (const phase of ["observed", "sending"]) {
    const record = row(0, 4800000, "AC");
    const legacy = [{sourceId: "qoj:tester:101", targetKey: key, record, index: 1, revision: 1, phase}];
    const result = project(archive([row(2, 1000, "WA"), record]),
      [item("101", row(0, 4812345, "AC"))], null, {legacy});
    assert.deepEqual(result.manual, [row(2, 1000, "WA"), row(0, 4812345, "AC")]);
    assert.equal(result.ownership.entries[0].index, 1);
    assert.equal(result.updatedCount, 1);
  }
});

test("an unconfirmed legacy click cannot authorize adding a second copy", () => {
  const record = row(0, 4800000, "AC");
  const legacy = [{sourceId: "qoj:tester:101", targetKey: key, record, index: 0, revision: 1, phase: "sending"}];
  assert.throws(() => project(archive(), [item("101", record)], null, {legacy}),
    code("RANKLAND_OWNERSHIP_CONFLICT"));
});

test("once migrated, stale legacy receipts cannot resurrect withdrawn records", () => {
  const record = row(0, 4800000, "AC");
  const legacy = [{sourceId: "qoj:tester:101", targetKey: key, record, index: 0, revision: 1, phase: "observed"}];
  const migrated = project(archive([record]), [], null, {legacy});
  const next = project(archive(migrated.manual), [item("101", row(0, 4800000, "WA"), 3)],
    migrated.ownership, {legacy});
  assert.deepEqual(next.manual, [row(0, 4800000, "WA")]);
});

test("another target, duplicate sources and duplicate owned slots are rejected", () => {
  const desired = item("101", row(0, 1000, "AC"));
  const first = project(archive(), [desired]);
  assert.throws(() => project(archive(first.manual), [desired], {...first.ownership, targetKey: "other"}),
    code("RANKLAND_TARGET_MISMATCH"));
  assert.throws(() => project(archive(), [desired, desired]), code("RANKLAND_INVALID_PLAN"));
  const duplicate = {...first.ownership, entries: [first.ownership.entries[0],
    {...first.ownership.entries[0], sourceId: "qoj:tester:102"}]};
  assert.throws(() => project(archive(first.manual), [desired], duplicate), code("RANKLAND_OWNERSHIP_CONFLICT"));
});

test("unknown archive/schema, unsupported results, and invalid clock/revision values fail closed", () => {
  const valid = item("101", row(0, 1000, "AC"));
  assert.throws(() => project(archive([], {version: 3}), [valid]), code("RANKLAND_SCHEMA_CHANGED"));
  for (const bad of [null, row(-1, 1000, "AC"), row(0, -1, "AC"), row(0, Infinity, "AC"),
    row(0, 1000, "ACCEPTED"), {...row(0, 1000, "AC"), unknown: true}]) {
    assert.throws(() => project(archive([bad]), []), code("RANKLAND_SCHEMA_CHANGED"));
    assert.throws(() => project(archive(), [item("101", bad)]), code("RANKLAND_INVALID_PLAN"));
  }
  for (const revision of [0, -1, 1.5, "1", Infinity]) {
    assert.throws(() => project(archive(), [item("101", valid.record, revision)]), code("RANKLAND_INVALID_PLAN"));
  }
});

test("a stale source revision cannot overwrite a newer synchronized verdict", () => {
  const first = project(archive(), [item("101", row(0, 1000, "TLE"), 3)]);
  assert.throws(() => project(archive(first.manual), [item("101", row(0, 1000, "AC"), 2)], first.ownership),
    code("RANKLAND_STALE_PLAN"));
});

test("the pure module is available in a browser content-script global", () => {
  const fs = require("node:fs"), vm = require("node:vm");
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve("../../src/firefox/rankland-projection.js"), "utf8"), context);
  assert.equal(typeof context.VpRanklandProjection.reconcile, "function");
});
