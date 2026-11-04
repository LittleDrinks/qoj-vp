/* Browser-API event replay against the actual transport module. No network,
 * browser launch, credentials, source upload, or production CSP changes.
 * VM Firefox must independently verify the browser's real event metadata.
 */
'use strict';
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const productSource = fs.readFileSync(process.env.QOJ_VP_TRANSPORT_SOURCE
  ? path.resolve(process.env.QOJ_VP_TRANSPORT_SOURCE) : path.join(__dirname, '../../src/firefox/transport.js'), 'utf8');
const TARGET = 'https://qoj.ac/contest/1051/problem/5115';
const TAB_ID = 17;
const EXTENSION_ORIGIN = 'moz-extension://qoj-vp-receipt-test';

function harness(scenario, {stored = {}, failStorage = false} = {}) {
  const listeners = {}, outgoing = [];
  const storage = JSON.parse(JSON.stringify(stored));
  let serial = 0;
  const browser = {
    runtime: {id: 'qoj-vp-receipt-test@littledrinks.local', getURL: part => EXTENSION_ORIGIN + '/' + part},
    webRequest: Object.fromEntries(['onBeforeSendHeaders', 'onHeadersReceived'].map(name => [name,
      {addListener: callback => { listeners[name] = callback; }}])),
    tabs: {
      query: async () => [{id: TAB_ID, url: 'https://qoj.ac/contest/1051'}],
      get: async id => { assert.equal(id, TAB_ID); return {id, status: 'complete', url: TARGET}; },
      sendMessage: async (id, message) => {
        assert.equal(id, TAB_ID);
        if (message.type === 'vp.http.ready') return {ready: true, pageOrigin: 'https://qoj.ac'};
        assert.equal(message.type, 'vp.http');
        outgoing.push(message.request);
        const requestId = 'request-' + (++serial);
        const nonce = message.request.headers['X-Qoj-Vp-Request'];
        const before = overrides => listeners.onBeforeSendHeaders({requestId, tabId: TAB_ID,
          method: message.request.method, url: message.request.url, type: 'xmlhttprequest',
          frameId: 0, parentFrameId: -1, originUrl: 'https://qoj.ac/contest/1051',
          documentUrl: 'https://qoj.ac/contest/1051',
          requestHeaders: nonce ? [{name: 'X-Qoj-Vp-Request', value: nonce}] : [], ...overrides});
        const headers = overrides => listeners.onHeadersReceived({requestId, tabId: TAB_ID,
          method: message.request.method, url: message.request.url, statusCode: 302,
          responseHeaders: [{name: 'Location', value: '/submission/1000001'}], ...overrides});
        return scenario({request: message.request, requestId, nonce, before, headers,
          outgoing, listeners});
      },
    },
    scripting: {executeScript: async () => { throw new Error('Unexpected script injection in event replay'); }},
    storage: {local: {
      get: async key => ({[key]: storage[key]}),
      set: async values => {
        if (failStorage) throw new Error('Synthetic storage failure');
        Object.assign(storage, JSON.parse(JSON.stringify(values)));
      },
    }},
  };
  const context = vm.createContext({browser, URL, Date, crypto: {randomUUID},
    // Speed only the module's observation waits. Events remain explicitly
    // ordered by the scenario; no production source bytes are changed.
    setTimeout: callback => { const timer = {active: true}; queueMicrotask(() => { if (timer.active) callback(); }); return timer; },
    clearTimeout: timer => { timer.active = false; }});
  vm.runInContext(productSource, context, {filename: 'src/firefox/transport.js'});
  return {transport: context.VpTransport, outgoing, listeners, storage,
    post: (task = {method: 'qoj_submit', finished: false}, overrides = {}) => context.VpTransport.http({
      method: 'POST', url: TARGET, headers: {}, allowRedirects: false, ...overrides}, task)};
}

const settleStorage = () => new Promise(resolve => setImmediate(resolve));

test('nonce-bound original HTTP redirect yields its observed Location and one dispatch', async () => {
  const h = harness(({before, headers}) => { before(); headers(); return {opaqueRedirect: true}; });
  const response = await h.post();
  assert.equal(response.status, 302);
  assert.equal(response.headers.Location, '/submission/1000001');
  assert.equal(response.receiptTransport, 'webRequest-observed-headers');
  assert.equal(h.outgoing.length, 1);
  assert.equal(h.transport.diagnostics().postObservations.length, 1);
});

for (const [name, alter] of [
  ['another positive tab ID', () => ({tabId: TAB_ID + 1})],
  ['another target URL', () => ({url: TARGET + '/different'})],
  ['another origin', () => ({url: 'https://example.org/contest/1051/problem/5115'})],
  ['GET event during a POST task', () => ({method: 'GET'})],
  ['missing nonce', () => ({requestHeaders: []})],
  ['incorrect nonce', () => ({requestHeaders: [{name: 'X-Qoj-Vp-Request', value: 'not-the-current-nonce'}]})],
]) {
  test(name + ' cannot confirm a redirect or trigger a second POST', async () => {
    const h = harness(({before, headers}) => { before(alter()); headers(); return {opaqueRedirect: true}; });
    await assert.rejects(h.post(), /UNCONFIRMED_REDIRECT/);
    assert.equal(h.outgoing.length, 1);
    assert.equal(h.transport.diagnostics().postObservations.length, 0);
  });
}

test('a response for another request ID cannot confirm the current request', async () => {
  const h = harness(({before, headers}) => { before(); headers({requestId: 'unrelated'}); return {opaqueRedirect: true}; });
  await assert.rejects(h.post(), /UNCONFIRMED_REDIRECT/);
  assert.equal(h.outgoing.length, 1);
});

test('a 302 without Location remains unknown and is never resent', async () => {
  const h = harness(({before, headers}) => { before(); headers({responseHeaders: []}); return {opaqueRedirect: true}; });
  await assert.rejects(h.post(), /UNCONFIRMED_REDIRECT/);
  assert.equal(h.outgoing.length, 1);
  assert.equal(h.transport.diagnostics().postObservations[0].locationPath, null);
});

test('regular 503 is forwarded as 503, never invented as a submission redirect', async () => {
  const h = harness(({before, headers}) => {
    before(); headers({statusCode: 503, responseHeaders: []});
    return {status: 503, url: TARGET, headers: {'content-type': 'text/plain'}, bodyBase64: ''};
  });
  const response = await h.post();
  assert.equal(response.status, 503);
  assert.equal(response.receiptTransport, undefined);
  assert.equal(h.outgoing.length, 1);
  assert.equal(h.transport.diagnostics().postObservations[0].locationPath, null);
});

test('expired nonce and old request ID cannot contaminate the next operation', async () => {
  let oldNonce, oldRequestId;
  const h = harness(({nonce, requestId, before, headers}) => {
    if (oldNonce) {
      before({requestId: 'late-old-request', requestHeaders: [{name: 'X-Qoj-Vp-Request', value: oldNonce}]});
      headers({requestId: 'late-old-request', responseHeaders: [{name: 'Location', value: '/submission/9999999'}]});
      headers({requestId: oldRequestId, responseHeaders: [{name: 'Location', value: '/submission/9999999'}]});
    }
    before(); headers(); oldNonce = nonce; oldRequestId = requestId;
    return {opaqueRedirect: true};
  });
  await h.post();
  const response = await h.post();
  assert.equal(response.headers.Location, '/submission/1000001');
  assert.equal(h.outgoing.length, 2);
  assert.equal(h.transport.diagnostics().postObservations.length, 2);
});

test('POST authorization is checked before contacting any content script', async () => {
  const h = harness(() => { throw new Error('An unauthorized task reached the content script'); });
  await assert.rejects(h.post({method: 'qoj_submissions', finished: false}), /POST_REQUIRES_EXPLICIT_SUBMIT/);
  assert.equal(h.outgoing.length, 0);
});

test('diagnostics persist only safe phases, excluding nonce, credentials, query, body and exception text', async () => {
  let nonce;
  const h = harness(({nonce: value, before, headers}) => {
    nonce = value;
    before(); headers({responseHeaders: [{name: 'Location', value: '/submission/1000001?auth=FAKE_LOCATION_SECRET'}]});
    return {opaqueRedirect: true};
  });
  const response = await h.post(undefined, {url: TARGET + '?csrf=FAKE_QUERY_SECRET',
    headers: {'X-Synthetic-Credential': 'FAKE_HEADER_SECRET'},
    data: {_token: 'FAKE_CSRF_SECRET'}, files: [{contentsBase64: 'FAKE_SOURCE_SECRET'}]});
  assert.equal(response.status, 302);
  await settleStorage();
  const diagnostics = h.transport.diagnostics(), attempt = diagnostics.postAttempts[0];
  assert.equal(attempt.finalCode, 'OBSERVED_REDIRECT');
  assert.notEqual(attempt.diagnosticId, nonce);
  assert.equal(attempt.requestPath, '/contest/1051/problem/5115');
  assert.ok(attempt.events.some(event => event.phase === 'beforeBound'));
  assert.ok(attempt.events.some(event => event.phase === 'headersObserved' && event.locationPath === '/submission/1000001'));
  assert.ok(attempt.events.some(event => event.phase === 'opaqueReturned'));
  assert.equal(attempt.phase, 'receiptReturned');
  assert.equal(diagnostics.persistence.loaded, true);
  assert.equal(diagnostics.persistence.error, false);
  assert.equal(diagnostics.persistence.pendingWrites, 0);
  assert.equal(h.storage['http-post-diagnostics-v1'].attempts.length, 1);
  const persisted = JSON.stringify(h.storage);
  for (const forbidden of [nonce, 'FAKE_', 'bodyBase64', 'contentsBase64', '_token', '?csrf', '?auth']) {
    assert.ok(!persisted.includes(forbidden), 'An unsafe field escaped the diagnostic allowlist');
  }
});

test('a rejected nonce-bound tab match is recorded without weakening association', async () => {
  const h = harness(({before, headers}) => { before({tabId: TAB_ID + 1}); headers(); return {opaqueRedirect: true}; });
  await assert.rejects(h.post(), /UNCONFIRMED_REDIRECT/);
  await settleStorage();
  const attempt = h.transport.diagnostics().postAttempts[0];
  assert.equal(attempt.finalCode, 'UNCONFIRMED_REDIRECT');
  const rejected = attempt.events.find(event => event.phase === 'beforeRejected');
  assert.equal(rejected.tabMatches, false);
  assert.equal(rejected.urlMatches, true);
  assert.equal(rejected.methodMatches, true);
  assert.equal(attempt.events.find(event => event.phase === 'receiptMissing').headersObserved, false);
  assert.ok(!attempt.events.some(event => event.phase === 'headersObserved'));
  assert.equal(h.outgoing.length, 1);
});

test('503 diagnostics show a real returned status, without claiming a native receipt or native error', async () => {
  const h = harness(({before, headers}) => {
    before(); headers({statusCode: 503, responseHeaders: []});
    return {status: 503, url: TARGET, headers: {}, bodyBase64: ''};
  });
  assert.equal((await h.post()).status, 503);
  await settleStorage();
  const attempt = h.transport.diagnostics().postAttempts[0];
  assert.equal(attempt.finalCode, 'HTTP_RESPONSE');
  assert.equal(attempt.phase, 'httpReturned');
  assert.equal(attempt.events.at(-1).status, 503);
  assert.ok(!attempt.events.some(event => event.phase === 'receiptReturned'));
});

for (const observation of ['absent', 'late']) {
  test(`503 remains a direct HTTP response when observational webRequest events are ${observation}`, async () => {
    let delayed;
    const h = harness(({before, headers}) => {
      delayed = {before, headers};
      return {status: 503, url: TARGET, headers: {}, bodyBase64: ''};
    });
    const response = await h.post();
    assert.equal(response.status, 503);
    assert.equal(response.receiptTransport, undefined);
    if (observation === 'late') {
      // Production has returned the actual response and removed this nonce;
      // late observation callbacks must not invent a receipt or dispatch again.
      delayed.before();
      delayed.headers({statusCode: 503, responseHeaders: []});
    }
    await settleStorage();
    const diagnostics = h.transport.diagnostics(), attempt = diagnostics.postAttempts[0];
    assert.equal(attempt.finalCode, 'HTTP_RESPONSE');
    assert.equal(attempt.phase, 'httpReturned');
    assert.equal(attempt.events.at(-1).status, 503);
    assert.equal(attempt.events.at(-1).urlMatches, true);
    assert.ok(!attempt.events.some(event => ['beforeBound', 'headersObserved', 'receiptReturned', 'failed'].includes(event.phase)));
    assert.equal(diagnostics.postObservations.length, 0);
    assert.equal(h.storage['http-post-diagnostics-v1'].attempts[0].finalCode, 'HTTP_RESPONSE');
    assert.equal(h.outgoing.length, 1);
  });
}

test('storage failure does not change a valid redirect or repeat a dispatch', async () => {
  const h = harness(({before, headers}) => { before(); headers(); return {opaqueRedirect: true}; }, {failStorage: true});
  assert.equal((await h.post()).status, 302);
  await settleStorage();
  assert.equal(h.outgoing.length, 1);
  assert.equal(h.transport.diagnostics().postAttempts[0].finalCode, 'OBSERVED_REDIRECT');
  assert.equal(h.transport.diagnostics().persistence.error, true);
});

test('event-page recovery restores safe history, never pending nonce bindings or delivery state', async () => {
  let previousNonce;
  const h = harness(({nonce, before, headers}) => { previousNonce = nonce; before(); headers(); return {opaqueRedirect: true}; });
  await h.post();
  await settleStorage();
  const recovered = harness(() => { throw new Error('Recovery must not issue network requests'); }, {stored: h.storage});
  await settleStorage();
  const diagnostic = recovered.transport.diagnostics();
  assert.equal(diagnostic.postAttempts.length, 1);
  assert.equal(diagnostic.postAttempts[0].finalCode, 'OBSERVED_REDIRECT');
  recovered.listeners.onBeforeSendHeaders({requestId: 'request-1', tabId: TAB_ID, method: 'POST', url: TARGET,
    requestHeaders: [{name: 'X-Qoj-Vp-Request', value: previousNonce}]});
  recovered.listeners.onHeadersReceived({requestId: 'request-1', tabId: TAB_ID, method: 'POST', url: TARGET,
    statusCode: 302, responseHeaders: [{name: 'Location', value: '/submission/9999999'}]});
  assert.equal(recovered.outgoing.length, 0);
  assert.equal(recovered.transport.diagnostics().postObservations.length, 0);
  assert.equal(recovered.transport.diagnostics().postAttempts[0].events.length, diagnostic.postAttempts[0].events.length);
});

test('arbitrary error messages are reduced to a fixed code before persistence', async () => {
  const h = harness(() => { throw new Error('https://qoj.ac/FAKE_ERROR_SECRET?token=FAKE_TOKEN'); });
  await assert.rejects(h.post());
  await settleStorage();
  assert.equal(h.transport.diagnostics().postAttempts[0].finalCode, 'BROWSER_BRIDGE_FAILED');
  assert.ok(!JSON.stringify(h.storage).includes('FAKE_'));
});

test('diagnostic history is bounded and GET never creates a POST attempt', async () => {
  const h = harness(({request, before, headers}) => {
    if (request.method === 'GET') return {status: 200, url: TARGET, headers: {}, bodyBase64: ''};
    before(); headers(); return {opaqueRedirect: true};
  });
  for (let n = 0; n < 33; n++) await h.post();
  await h.transport.http({method: 'GET', url: TARGET, headers: {}}, {method: 'qoj_contest', finished: false});
  await settleStorage();
  assert.equal(h.transport.diagnostics().postAttempts.length, 30);
  assert.equal(h.storage['http-post-diagnostics-v1'].attempts.length, 30);
  assert.ok(h.transport.diagnostics().postAttempts.every(attempt => attempt.events.length <= 16));
});
