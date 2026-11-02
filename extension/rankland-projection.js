"use strict";
// Reconcile a complete desired QOJ projection with the last records proven to
// belong to this extension. This module deliberately does not write storage or
// change the original application's clock, playback state, or team details.
(() => {
  const LIMIT = 10000;
  const RESULTS = new Set(["AC", "WA", "TLE", "MLE", "RTE", "CE", "PE", "OLE", "IDLE", "NOUT", "RJ", "UKE"]);
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const text = (value, max) => typeof value === "string" && value.length > 0 && value.length <= max && !/[\x00-\x1f\x7f]/.test(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const same = (a, b) => a.problemIndex === b.problemIndex && a.timeMs === b.timeMs && a.result === b.result;
  const copy = record => ({problemIndex: record.problemIndex, timeMs: record.timeMs, result: record.result});
  const signature = record => `${record.problemIndex}:${record.timeMs}:${record.result}`;
  function fail(code, message) {
    throw Object.assign(new Error(message), {code});
  }
  function validRecord(record) {
    return object(record) && Object.keys(record).length === 3 &&
      integer(record.problemIndex) && Number.isFinite(record.timeMs) &&
      record.timeMs >= 0 && record.timeMs <= Number.MAX_SAFE_INTEGER && RESULTS.has(record.result);
  }
  function validSource(entry) {
    return object(entry) && text(entry.sourceId, 300) &&
      Number.isSafeInteger(entry.revision) && entry.revision > 0 && validRecord(entry.record);
  }

  function reconcile({targetKey, archive, desired, ownership = null, legacy = []} = {}) {
    if (!text(targetKey, 4096)) fail("RANKLAND_INVALID_PLAN", "Missing RankLand target identity.");
    if (!object(archive) || archive.version !== 2 || !Array.isArray(archive.manual) ||
        archive.manual.length > LIMIT || !archive.manual.every(validRecord)) {
      fail("RANKLAND_SCHEMA_CHANGED", "Unsupported RankLand archive or manual submission schema.");
    }
    if (!Array.isArray(desired) || desired.length > LIMIT || !desired.every(validSource)) {
      fail("RANKLAND_INVALID_PLAN", "Invalid desired source submission records.");
    }
    const desiredSources = new Set();
    for (const entry of desired) {
      if (desiredSources.has(entry.sourceId)) fail("RANKLAND_INVALID_PLAN", "Duplicate source submission identity.");
      desiredSources.add(entry.sourceId);
    }

    let previous;
    if (ownership !== null) {
      if (!object(ownership) || ownership.version !== 1 || !Array.isArray(ownership.entries) || ownership.entries.length > LIMIT) {
        fail("RANKLAND_OWNERSHIP_CONFLICT", "Unsupported source ownership metadata.");
      }
      if (ownership.targetKey !== targetKey) fail("RANKLAND_TARGET_MISMATCH", "Ownership belongs to a different RankLand replay.");
      previous = ownership.entries;
      // Legacy receipts are consulted only before the first migration. After
      // withdrawing a rejudged AC, its old receipt must not claim a new slot.
    } else {
      if (!Array.isArray(legacy) || legacy.length > LIMIT) fail("RANKLAND_OWNERSHIP_CONFLICT", "Invalid legacy source receipts.");
      for (const receipt of legacy) {
        if (!object(receipt) || receipt.targetKey !== targetKey) {
          fail("RANKLAND_TARGET_MISMATCH", "Legacy receipt belongs to a different RankLand replay.");
        }
        if (!["sending", "observed"].includes(receipt.phase)) {
          fail("RANKLAND_OWNERSHIP_CONFLICT", "Unknown legacy source receipt phase.");
        }
      }
      previous = legacy;
    }

    const ownedSources = new Map(), ownedSlots = new Set();
    for (const entry of previous) {
      if (!validSource(entry) || !integer(entry.index) || entry.index >= archive.manual.length ||
          ownedSources.has(entry.sourceId) || ownedSlots.has(entry.index) ||
          !same(archive.manual[entry.index], entry.record)) {
        fail("RANKLAND_OWNERSHIP_CONFLICT", "An owned submission was changed, removed, moved, or cannot be uniquely identified.");
      }
      ownedSources.set(entry.sourceId, entry);
      ownedSlots.add(entry.index);
    }

    // The caller can have added real manual attempts between syncs. Keep every
    // such record (including identical tuples), without claiming or deleting it.
    const manual = archive.manual.filter((_, index) => !ownedSlots.has(index)).map(copy);
    const unowned = new Set(manual.map(signature));
    if (manual.length + desired.length > LIMIT) fail("RANKLAND_INVALID_PLAN", "RankLand's manual submission limit would be exceeded.");
    let updatedCount = [...ownedSources.keys()].filter(sourceId => !desiredSources.has(sourceId)).length;
    const entries = [];
    for (const entry of desired) {
      const old = ownedSources.get(entry.sourceId);
      if (old && entry.revision < old.revision) fail("RANKLAND_STALE_PLAN", "A newer source revision has already been synchronized.");
      if (!old && unowned.has(signature(entry.record))) {
        fail("RANKLAND_UNOWNED_CONFLICT", "A matching manual submission exists without proof that it belongs to this source.");
      }
      if (!old || entry.revision !== old.revision || !same(entry.record, old.record)) updatedCount++;
      entries.push({sourceId: entry.sourceId, revision: entry.revision, index: manual.length, record: copy(entry.record)});
      manual.push(copy(entry.record));
    }
    const changed = manual.length !== archive.manual.length || manual.some((record, index) => !same(record, archive.manual[index]));
    return {manual, ownership: {version: 1, targetKey, entries}, changed, updatedCount};
  }

  const api = Object.freeze({reconcile});
  globalThis.VpRanklandProjection = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
