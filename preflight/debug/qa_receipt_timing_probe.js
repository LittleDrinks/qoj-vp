// Temporary self-module for the extension QA page. Not a production script.
// Judge traffic is GET only. Output excludes bodies, header/nonce values,
// credentials, CSRF, arbitrary query strings and user/account names.
export async function run({holdMs = 4000} = {}) {
  if (!Number.isInteger(holdMs) || holdMs < 1000 || holdMs > 8000) throw new Error('INVALID_HOLD');
  const origin = 'https://qoj.ac';
  const base = origin + '/contest/1051/problem/5115';
  const canonical = base + '/statement/zh_cn';
  const tabs = (await browser.tabs.query({})).filter(tab => {
    try { return new URL(tab.url).origin === origin; } catch (_) { return false; }
  });
  const tab = tabs.find(item => new URL(item.url).pathname === canonical) || tabs[0];
  if (!tab) throw new Error('NO_QOJ_TAB');
  const manifest = browser.runtime.getManifest();
  const permissionGranted = await browser.permissions.contains({permissions: ['webRequest'], origins: [origin + '/*']});
  const started = performance.now(), elapsed = () => Math.round((performance.now() - started) * 1000) / 1000;
  const events = [], trials = [], nonces = new Map(), tracked = new Map();
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const targets = new Set([base, canonical]);
  const safeUrl = raw => {
    try { const url = new URL(raw); return {origin: url.origin, path: url.pathname}; }
    catch (_) { return null; }
  };
  const common = (event, details) => ({event, atMs: elapsed(), requestId: details.requestId,
    method: details.method, path: safeUrl(details.url)?.path ?? null, tabId: details.tabId,
    frameId: details.frameId, parentFrameId: details.parentFrameId,
    type: details.type, status: details.statusCode ?? null, boundAtCallback: tracked.has(details.requestId)});
  const before = details => {
    const header = details.requestHeaders?.find(item => item.name.toLowerCase() === 'x-qoj-vp-probe');
    const index = header && nonces.get(header.value);
    if (!Number.isInteger(index)) return;
    tracked.set(details.requestId, index);
    events.push({...common('before', details), trial: index, nonceHeaderPresent: true, nonceMatch: true,
      urlEqual: details.url === trials[index].target, tabEqual: details.tabId === tab.id,
      origin: safeUrl(details.originUrl)?.origin ?? null,
      documentOrigin: safeUrl(details.documentUrl)?.origin ?? null});
  };
  const sent = details => {
    const header = details.requestHeaders?.find(item => item.name.toLowerCase() === 'x-qoj-vp-probe');
    if (!header || !nonces.has(header.value)) return;
    events.push({...common('sent', details), nonceHeaderPresent: true, nonceMatch: true});
  };
  const candidate = details => tracked.has(details.requestId) ||
    (details.method === 'GET' && details.tabId === tab.id && targets.has(details.url));
  const headers = details => {
    if (!candidate(details)) return;
    const location = details.responseHeaders?.find(item => item.name.toLowerCase() === 'location')?.value;
    const resolved = location ? safeUrl(new URL(location, details.url).href) : null;
    // Buffer even if before's callback has not run yet. Attribute only after
    // the complete trace, using the nonce-bound request ID, never URL alone.
    events.push({...common('headers', details), locationPresent: !!location,
      locationOrigin: resolved?.origin ?? null, locationPath: resolved?.path ?? null});
  };
  const redirect = details => {
    if (candidate(details)) events.push({...common('redirect', details),
      redirectOrigin: safeUrl(details.redirectUrl)?.origin ?? null,
      redirectPath: safeUrl(details.redirectUrl)?.path ?? null});
  };
  const completed = details => {
    if (candidate(details)) events.push(common('completed', details));
  };
  const failed = details => {
    if (candidate(details)) events.push({...common('error', details),
      errorCode: /^NS_[A-Z0-9_]+$/.test(details.error || '') ? details.error : 'NETWORK_ERROR'});
  };
  const filter = {urls: [origin + '/*']};
  const subscriptions = [
    ['onBeforeSendHeaders', before, ['requestHeaders']],
    ['onSendHeaders', sent, ['requestHeaders']],
    ['onHeadersReceived', headers, ['responseHeaders']],
    ['onBeforeRedirect', redirect], ['onCompleted', completed], ['onErrorOccurred', failed],
  ];
  for (const [name, listener, extra] of subscriptions) browser.webRequest[name].addListener(listener, filter, extra);
  try {
    for (const [name, target] of [['manual-base-first', base], ['manual-canonical-control', canonical], ['manual-base-repeat', base]]) {
      const index = trials.length, nonce = crypto.randomUUID();
      const trial = {name, target, targetPath: new URL(target).pathname, dispatchAtMs: elapsed()};
      trials.push(trial);
      nonces.set(nonce, index);
      try {
        const reply = await browser.tabs.sendMessage(tab.id, {type: 'vp.http', request: {
          method: 'GET', url: target, timeoutMs: 20000, allowRedirects: false,
          headers: {'X-Qoj-Vp-Probe': nonce},
        }});
        trial.fetchResolvedAtMs = elapsed();
        trial.reply = {status: Number.isInteger(reply?.status) ? reply.status : null,
          opaqueRedirect: reply?.opaqueRedirect === true, path: safeUrl(reply?.url)?.path ?? null};
      } catch (error) {
        trial.fetchResolvedAtMs = elapsed();
        trial.reply = {errorType: /^[A-Za-z]+Error$/.test(error?.name || '') ? error.name : 'Error'};
      }
      await pause(holdMs);
      trial.holdFinishedAtMs = elapsed();
    }
  } finally {
    for (const [name, listener] of subscriptions) browser.webRequest[name].removeListener(listener);
  }
  const boundEvents = events.filter(event => tracked.has(event.requestId)).map(event => {
    const index = tracked.get(event.requestId), trial = trials[index];
    return {...event, trial: index, relativeToFetchMs: Math.round((event.atMs - trial.fetchResolvedAtMs) * 1000) / 1000};
  });
  return {schema: 'qoj-readonly-receipt-timing-v1', expectedTabId: tab.id,
    permissionGranted, manifestVersion: manifest.manifest_version, extensionVersion: manifest.version,
    holdMs, qojPostCount: 0, trials: trials.map(({target, ...safe}) => safe), events: boundEvents,
    unboundCandidateCount: events.length - boundEvents.length,
    attribution: 'Only nonce-bound request IDs are returned; late/early header callbacks are retained until trace end.',
    summary: trials.map((trial, index) => {
      const rows = boundEvents.filter(event => event.trial === index), response = rows.find(event => event.event === 'headers');
      return {trial: index, beforeCount: rows.filter(event => event.event === 'before').length,
        headersCount: rows.filter(event => event.event === 'headers').length,
        firstHeadersRelativeToFetchMs: response?.relativeToFetchMs ?? null,
        headersOverProductionOneSecondWait: response ? response.relativeToFetchMs > 1000 : null,
        headersBeforeNonceCallback: rows.some(event => event.event === 'headers' && !event.boundAtCallback)};
    })};
}

export async function display(options = {}) {
  const result = await run(options);
  // Local collection is optional and explicit. It never sends judge traffic.
  if (options.reportUrl) {
    const url = new URL(options.reportUrl);
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) ||
        url.pathname !== '/report' || url.username || url.password || url.search || url.hash) throw new Error('REPORT_URL_DENIED');
    await fetch(url.href, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(result)});
  }
  document.getElementById('qoj-qa-timing-report')?.remove();
  const pre = document.createElement('pre');
  pre.id = 'qoj-qa-timing-report';
  pre.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:white;color:black;overflow:auto;padding:12px;font:12px/1.5 monospace;white-space:pre-wrap';
  pre.textContent = JSON.stringify(result, null, 2);
  document.body.append(pre);
  return result;
}
