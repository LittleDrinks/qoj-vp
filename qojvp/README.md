# QOJ VP native application

`Application(state_dir=None, qoj_path=None, fixture_origin=None, clock=now_ms)` owns
one SQLite connection. Call `dispatch(method, args, exchange)` and close it, or
use its context manager. The extension and tests cross this same interface.

`python -m qojvp.native_host` reads one Firefox length-framed task, exchanges
`http.request` / `http.response` frames as necessary, returns one result and
exits. Every JSON stdout byte belongs to a native frame. Dependencies are the
actual pinned qoj-submitter dependencies (requests, beautifulsoup4, pycurl).

The application keeps the pinned client's status GET but verifies the account
within QOJ's observed right-hand navigation (`ul.nav.nav-pills.float-right`,
`li.nav-item.dropdown` profile links plus same-navigation same-origin logout).
This handles the actual Chinese menu and protocol-relative profile links while
excluding body/footer profiles. Logout is compared by origin/path only; its
query is never returned or stored. Unrecognized or ambiguous navigation returns
no account from qoj_contest and ACCOUNT_UNKNOWN before any code POST. This
compatibility layer does not alter the upstream submodule or its pin.

Environment:

- `QOJ_VP_STATE_DIR`: durable state, default `~/.local/share/qoj-vp`; use a local filesystem.
- `QOJ_VP_QOJ_PATH`: upstream checkout, default `<project>/vendor/qoj-submitter`.
- `QOJ_VP_FIXTURE_ORIGIN`: installation-only optional loopback test routing.
  A UI task cannot choose or change it.

Methods and common fields follow `docs/MVP_CONTRACT.md`. Additional methods:

- `update_session {sessionId, title?, ranklandUrl?}` changes only those fields.
  The saved URL preserves contest/rule/count/ratio, forces unique run, unit
  speed, and anchors `at` to the immutable local start time. A prepared replay's
  exact URL is retained when the user saves the same target configuration.
- `prepare_rankland {sessionId}` must run immediately before first opening the
  original scoreboard. RankLand's autoplay path does not automatically catch up
  from a past `at`, so this method freezes `from=elapsedMs/60000` once and persists
  `ranklandPrepared` / `ranklandPreparedAt`. Every later reopen returns that exact
  URL and storage slot. Changing the target contest/configuration resets the
  marker, allowing a new first-open offset; ordinary reopen/settings-save does
  not reset progress. Unstarted/future-start sessions cannot freeze an offset.
- `qoj_reconcile {sessionId,operationId,submissionId}` requires an unknown intent
  and a freshly verified same-account/contest/problem/language submission with
  an absolute time within the intent's bounded window. This is an explicit user
  association, never an automatic same-problem guess.
- `rankland_queue {sessionId}` returns items with `queueId`, `revision`,
  `submissionId`, `sourceId`, `problemId`, `problemLabel`, `elapsedMs`, `verdict`,
  `rawVerdict`, `state`, `attempts`. Items are independently persisted from the
  QOJ submission; failure to deliver cannot cause a repeated code POST.
- `rankland_ack {sessionId,queueId,revision,state,receipt?,error?}` accepts synced,
  ambiguous or failed. A stale revision cannot acknowledge a newer verdict.
  Receipt metadata is limited to targetKey/problemIndex/timeMs/result/observedAt.

HTTP requests include `method,url,logicalUrl,headers,timeoutMs,allowRedirects`.
POST additionally includes `data` as a field dictionary, and `files` as
`[{field,filename,contentType,contentsBase64}]`. Only a qoj_submit task authorizes
POST; the actual upstream `QojClient.submit` constructs its fields and validates
the observed status/Location. Cookies and User-Agent are never exported to Python.

An operation is recorded before its POST. A reused operation ID returns the
saved receipt/unknown state. Identical unresolved source intents also block new
operation IDs. A crash in `submitting` is conservatively shown as unknown, never
automatically sent again. The ledger stores hashes and metadata, not source,
CSRF values or cookies. Source and inline ZIP limits are each 512 KiB.

Sample downloads first use the unmodified upstream attachment downloader.
Only an actual attachment HTTP 404 with no attachment output enables the local
statement fallback: one active QOJ article, its labelled H2/H3 sample section and
matching numbered H4 input/output plain-text PRE pairs (observed on 1051/C).
The extracted pairs still pass through upstream organize/zip_bytes. Arbitrary
code PREs, inactive tabs and incomplete/ambiguous pairs are rejected; no empty
ZIP is fabricated. Unsafe/corrupt attachment errors propagate and cannot be
hidden by an inline fallback. Existing incomplete attachment pairs and special
extra files retain the upstream behavior. `sampleSource` distinguishes actual
attachments from verified inline statement samples.

History results preserve original verdicts and provider IDs; a numeric zero is
not WA. Details inspect the latest Details section and do not let an early AC
test override a later failing test. Unknown detail results remain unconfirmed.
Pagination, malformed rows and timestamps are reflected in coverage warnings.
Plain dates without a zone and native-VP HH:MM:SS are intentionally not converted
using an unverified local timezone/native start; known local submission intents
retain their local observed time when a history page cannot improve it.
Running-session refresh can instead backfill an absolute time from one detail
table row matching SID, owner, contest/problem and zoned Submit time. Verified
facts persist; failed probes wait 60 seconds, with at most three historical-time
probes per refresh and fair rotation. Prepared sessions do not probe; explicit
reconciliation prioritizes its SID but does not automatically link intents.
The real old native submission 1511772 was verified this way; unverified times
still cannot put a record into the current session/RankLand queue. See
[the evidence and boundaries](../docs/research/2026-11-01/native-vp-submit-time.md).

The HTML/history selectors are compatibility code observed from QOJ-shaped
fixtures and the primary implementation
[vp-helper QOJ adapter](https://github.com/thedyingkai/vp-helper/blob/main/vp_helper/qoj.py)
(read 2026-10-31). They are not a stable public QOJ API. Actual upstream submit
and samples logic are imported from the pinned LittleDrinks/qoj-submitter Git
submodule. Passing synthetic tests does not establish real account/network
compatibility; that acceptance is performed separately in VMware Firefox.
