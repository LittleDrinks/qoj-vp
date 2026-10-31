# Isolated native/Firefox preflight contract

This is a read-only preflight prototype. It does not implement code submission,
VP registration, account login, cookie import, or a complete DOMjudge UI.

## Installation values

- Extension ID: `qoj-vp-preflight@littledrinks.local`
- Native host name: `org.littledrinks.qoj_preflight`
- Native entry: `native_host.py` (launch with the intended Python environment).
- Required packages: requests, beautifulsoup4, pycurl. pycurl is needed by the
  actual QOJ package's top-level imports, even with an injected BrowserSession.
- `QOJ_PREFLIGHT_QOJ_PATH`: directory containing the real `qoj_submitter` package;
  the coordinator has pinned this to commit `807ce1be13d67916b2716f8221a10a12731977fe`.
- `QOJ_PREFLIGHT_STATE_DIR`: a dedicated local directory for `preflight.sqlite3`.
- Do not point state at the shared folder. No state or credentials are loaded
  from the existing qoj CLI installation.

The MV3 extension uses a Firefox background event page. Installing it opens its
own `test.html` tab; that page immediately runs hello and records its exact
`moz-extension://.../test.html` URL in SQLite table `trace` (kind=`hello`, JSON in
`data_json`). The row also records PID. This trace contains no authentication
data. The action button reopens or focuses that extension page.

## Page calls

Call from the extension test page's ordinary content context:

```javascript
await window.preflight.run("hello", {pageUrl: location.href});
await window.preflight.run("create_session", {
  sessionId: "controlled-two-hour-session",
  contestId: "7001",
  startAt: Date.now() - 2 * 60 * 60 * 1000,
  ranklandUrl: "https://vp.xcpc.link/vp?contest=EXAMPLE&run=controlled-two-hour-session"
});
await window.preflight.run("inspect_session", {sessionId: "controlled-two-hour-session"});
await window.preflight.run("list_sessions");
await window.preflight.run("qoj_contest_and_sample", {
  contestId: "7001", problemLabel: "A",
  fixtureOrigin: "http://127.0.0.1:8765", includeZip: true,
  httpTabId: 123 // Optional: tab in THIS Firefox, at the same fixture origin.
});
await window.preflight.run("qoj_problem_form", {
  contestId: "7001", problemId: "777", fixtureOrigin: "http://127.0.0.1:8765"
});
```

Omit fixtureOrigin to perform the same read-only operations on `https://qoj.ac`.
The `source` field explicitly distinguishes `fixture` from `real-qoj-browser`.
Neither source value alone asserts a successful real QOJ submission.

Each call creates a new native port and process. The result includes helperPid,
taskId, and nativePortClosed. The helper sends its terminal result and exits;
the extension also disconnects its port. The coordinator should poll the actual
guest process table to verify each returned PID has exited, allowing a short
process shutdown interval.

create_session persists a start timestamp, not a ticking process. inspect_session
derives elapsedMs from the current time, so closing/reopening the work page or
Firefox does not depend on a surviving Python process. It also accepts nowMs for
controlled pure tests. This preflight does not automatically modify RankLand's
storage or claim to restore the original OJ's native VP registration.

## HTTP path

The real imported QojClient receives BrowserSession. It asks Python for a GET;
the native host sends an http.request envelope. The background event page routes
it to a static content script in a QOJ/fixture tab. That content script performs
`fetch` with credentials included and with an exact same-origin check.

httpTabId can select an existing original-site tab. If omitted, the extension
finds a matching-origin tab or creates an inactive tab within the VM Firefox.
The background page never performs the network fetch itself. Responses report
transport=`content-script-same-origin`, pageOrigin, and tabId. No cookie or
User-Agent value is imported into Python or overwritten in Firefox.

fixtureOrigin rewrites the actual network URL while keeping the logical client
origin `https://qoj.ac`. On return, fixture redirects are mapped back to the
logical QOJ URL, preserving the real client's origin and login-redirect checks.
Only GET is enabled; even an accidental QojClient.submit call fails before any
network POST. CSRF token values and raw HTML are not returned or stored.

## Native frames and envelopes

Every frame is a 4-byte little-endian unsigned UTF-8 JSON byte length followed
by that many bytes. Native stdout contains frames only. The imported samples
module's human progress output is redirected to stderr.

```text
extension → native: {type:"task", id, method, args}
native → extension: {type:"http.request", id, requestId, request:{url,logicalUrl,method,headers,timeoutMs,fixture}}
extension → native: {type:"http.response", id, requestId, response:{status,url,headers,bodyBase64,transport,pageOrigin,tabId}}
extension → native: {type:"http.response", id, requestId, error:{code,message}}
native → extension: {type:"result", id, ok:true, pid, result}
native → extension: {type:"result", id, ok:false, pid, error:{code,message}}
```

qoj_contest_and_sample returns all problem metadata, one selected problem's
normalized samples file hashes, retained special-file names, warnings, and ZIP
hash/size. includeZip returns a base64 archive only when it fits the prototype's
512 KiB archive limit; the page exposes a download link. Large real attachments
need a later chunked transfer design, and are not silently claimed downloaded.
qoj_problem_form returns language options, csrfPresent, actionPath and discovered
PDF candidates, without exposing the token.

## Local checks

```sh
python3 test_native_core.py
node --check extension/background.js
node --check extension/http-content.js
node --check extension/test.js
```

The Python suite imports the real pinned QOJ code and real dependencies, using a
local HTTP fixture and a Python protocol driver in place of Firefox. Its HTTP
responses deliberately say `transport=python-test-driver`; passing these tests
does not establish Firefox ESR, cookie/session reuse, real QOJ reachability, or
real submission correctness. Those are separate VM acceptance checks.
