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
  Only when configured, RankLand URL normalization also permits a fixture at
  `http(s)://localhost:<port>/` or `http(s)://127.0.0.1:<port>/`. An explicit
  nonzero port is required; credentials, other hosts, paths and fragments are
  rejected. Normal installations accept only `https://vp.xcpc.link/`.

Methods and common fields follow `docs/MVP_CONTRACT.md`. Additional methods:

- `update_session {sessionId, title?, durationMs?, ranklandUrl?}` changes only those fields.
  Title and duration can only change while the local session is prepared. Title
  must be nonempty, at most 200 characters, with no control characters; duration
  must be an integer from 1 ms through 14 days. RankLand settings remain editable
  for other session states.
  The saved URL preserves contest/rule/count/ratio, forces unique run, unit
  speed, and anchors `at` to the immutable local start time. A prepared replay's
  exact URL is retained when the user saves the same target configuration.
- `finish_session {sessionId}` ends a started local session without any QOJ or
  RankLand request. It persists `state:'finished'` and `finishedAt`, freezes
  elapsed time, and caps the current submission/outbox window at that time.
  Repeating it does not move the finish time. It cannot start, finish or alter
  an official QOJ VP; prepared and future-start sessions are rejected.
- `delete_session {sessionId, confirmed:true}` deletes only a prepared, archived
  or effectively finished local session. A running session must finish first.
  Any preparing/submitting/unknown source intent prevents deletion until it is
  reconciled. Session operations, history links and outbox items are removed in
  one transaction; provider facts still linked to another session survive.
  Account/contest-scoped resource caches and verified contest snapshots remain.
  No original-site record or file is deleted.
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
- `rankland_plan {sessionId}` returns the complete desired RankLand projection,
  not merely a batch of appended records. `items` contains eligible final
  verdicts in original submission-time / numeric QOJ ID order; each retains its
  stable `sourceId`, `queueId`, current `revision` and exact `elapsedMs`.
  Pending verdicts and unknown local receipts hold back only later submissions
  of the same problem. `waiting` describes those unresolved/held records;
  `pendingCount` counts unresolved records and `blockedCount` counts held final
  verdicts. Other problems can synchronize immediately. Confirmed final
  rejudgements appear even if their legacy queue state is `needs-review`.
  `allItems` retains prior queue records so a projection adapter can withdraw
  previously delivered results now pending or outside the session window.
  A local send-intent timestamp never substitutes for QOJ's confirmed acceptance
  time: records with only that timestamp remain `time-unverified` until a
  verified history/detail response supplies `provider-absolute` time.
  It must preserve unrelated original-site records and reconcile owned source
  IDs instead of interpreting this plan as repeated form submissions.
  `planToken` identifies the exact desired membership, ordering, unresolved
  barriers, source revisions/times and target URL. It excludes delivery attempts
  and polling times, remaining stable across retries and helper restarts.
- `refresh_sessions {}` returns started, non-archived sessions requiring
  `refreshRequired` (QOJ history) and/or `syncRequired` (RankLand reconciliation).
  It includes finished sessions with unresolved records and sessions lacking
  one verified complete history pass begun at/after their fixed end time.
  Failures do not mark that catch-up complete; metadata survives helper and
  Firefox restarts. A successful QOJ refresh should still reconcile its new
  plan even when the earlier scheduling snapshot had `syncRequired:false`.
  A finished session with only undelivered final records needs RankLand retry,
  without another QOJ fetch on every alarm. Archiving opts out of automatic
  polling. Manual refresh/sync remains available for later rejudgements.
  `inspect_session` exposes `lastHistoryRefreshAt`, `lastHistoryCompleteAt`
  and `lastHistoryRefreshComplete`. A failed explicit refresh reopens source
  polling even after a previously settled contest, including cached fallbacks
  with zero fetched pages and failures before authentication/history completes.
  An older request finishing later cannot hide a newer incomplete refresh;
  a subsequent complete pass clears the retry requirement.
- `rankland_ack {sessionId,queueId,revision,state,receipt?,error?}` accepts synced,
  ambiguous or failed. A stale revision cannot acknowledge a newer verdict.
  Receipt metadata is limited to targetKey/problemIndex/timeMs/result/observedAt.
- `rankland_ack_batch {sessionId,acknowledgements,planToken?}` applies the same acknowledgements
  in one transaction and one helper task. Accepts at most 10,000 distinct queue
  IDs. Any stale revision rejects the whole batch (`accepted:false`); unknown
  IDs and malformed items reject without mutating other entries. On success it
  returns `accepted:true` and per-item `results`. A projection adapter can
  acknowledge removed or intentionally held `allItems` as evaluated/applied;
  pending source facts remain eligible for history polling independently.
  The projection adapter supplies `planToken` and every `allItems` queue ID,
  including an empty batch for an empty plan. A changed plan rejects the whole
  acknowledgement with `reason:'stale-plan'`. A successful all-synced batch
  persists that token; `refresh_sessions.syncRequired` also compares it with
  the current plan, detecting receipt resolution that changes membership
  without a newer provider verdict. Missing-token calls retain the legacy
  per-record acknowledgement semantics and cannot settle a projection token.

HTTP requests include `method,url,logicalUrl,headers,timeoutMs,allowRedirects`.
POST additionally includes `data` as a field dictionary, and `files` as
`[{field,filename,contentType,contentsBase64}]`. Only a qoj_submit task authorizes
POST; the actual upstream `QojClient.submit` constructs its fields and validates
the observed status/Location. Cookies and User-Agent are never exported to Python.

An operation is recorded before its POST. A reused operation ID returns the
saved receipt/unknown state. Identical unresolved source intents also block new
operation IDs. A crash in `submitting` is conservatively shown as unknown, never
automatically sent again. The ledger stores hashes and metadata, not source,
CSRF values or cookies. Source and legacy inline ZIP limits are each 512 KiB;
the prepared resource cache uses bounded chunks for ZIPs up to 64 MiB.

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

Since 0.2.1, ready resource entries expose `downloads`, an ordered list of
independent descriptors: samples first, attachments second, with only nonempty
downloads present. Each descriptor has `problemId`, `problemLabel`, `status`,
`kind`, `filename`, `resourceId`, `totalBytes`, `sha256`, `sampleSource`,
`preparedAt`, `interactiveHint`, `sampleCount`, `pairCount`, `files` and
`extraFiles`. The UI passes the chosen descriptor's ID to `resource_chunk`.
The entry's top-level fields and combined object remain for legacy callers;
they do not describe the two new buttons separately.

`samples-X.zip` contains complete same-stem `.in` / `.ans` pairs from
`samples-X/`. `attachments-X.zip` keeps the entire original
`attachment-extras/problem-X/` tree, including original sample files that tools
may use, plus incomplete generated sample items. It excludes the complete
generated sample copies already in the samples ZIP. A single-kind entry reuses
its original object; a mixed entry retains the legacy combined object and stores
two independent ZIPs. Explicit interactive hints still block inline statement
fallback, but do not block complete sample pairs supplied in official attachments.

`resource_manifest` validates cached ZIPs and lazily migrates old schema-1 entries
without `downloads` entirely offline. It verifies the original size, SHA,
member metadata, paths and extraction limits before atomically publishing child
objects and their manifest under a per-problem lock. Failed refreshes retain
previous downloads only when they still verify. `resource_chunk` accepts only
IDs bound by the current account/contest/problem manifest, including its legacy
top-level ID. It verifies the selected ZIP's size and SHA on each chunk, without
decompressing its members again; legacy entries are validated and migrated first.

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

Since 0.3.0, `import_samples {sessionId,problemId,zipBase64?,files?,confirmedReplace?}`
accepts exactly one of a ZIP or `files:[{name,base64}]`. It uses no HTTP bridge.
The problem must be in an account/contest snapshot previously verified by QOJ
GETs, or an older scoped resource entry with its verified problem label. A caller
cannot supply its own mapping. A missing snapshot/resource requires reading the
contest before importing; that requirement does not add a request to the import.

Imports allow at most 1000 files (ZIP directory entries count), 4 MiB per file,
8 MiB total decoded data, and an 8 MiB ZIP upload. ZIP paths, duplicate members,
symlinks, encryption, member types and extraction limits are checked without
extracting files. Only stored/deflated ZIPs are accepted. Every input must have
exactly one same-stem `.ans` or `.out`; unrelated files, incomplete pairs and
ambiguous answer suffixes are rejected. Pairs are naturally sorted and normalized
under `samples-X/` to numbered `.in`/`.ans` files, preserving content bytes.

Replacing already prepared samples requires `confirmedReplace:true`. The helper
preserves the original attachment descriptor, object and all its member bytes;
new sample numbering skips names occupied by incomplete old attachment inputs.
It publishes a new combined object and download manifest atomically under the
existing resource lock. The result has `manualSamples:true`, `sampleSource:'manual'`,
and the ordinary `downloads` descriptors. The samples descriptor identifies the
manual source; the attachment descriptor retains its original source metadata.
Automatic preparation/refresh returns a verified manual cache without network
access, and a concurrent provider store cannot overwrite it. Only another
explicitly confirmed import replaces prepared samples.

The native host accepts up to 96 MiB per incoming JSON frame; 8 MiB of sample data
requires about 10.7 MiB after base64, plus bounded filenames/JSON. An integration
test sends the full 8 MiB through `serve_once` and receives one metadata-only
result below the 1 MiB outgoing limit. Downloads retain the existing 256 KiB
chunk protocol. This proves the host framing seam, not a whole-page offline
bootstrap or a maximum-size real Firefox acceptance run.

The HTML/history selectors are compatibility code observed from QOJ-shaped
fixtures and the primary implementation
[vp-helper QOJ adapter](https://github.com/thedyingkai/vp-helper/blob/main/vp_helper/qoj.py)
(read 2026-10-31). They are not a stable public QOJ API. Actual upstream submit
and samples logic are imported from the pinned LittleDrinks/qoj-submitter Git
submodule. Passing synthetic tests does not establish real account/network
compatibility; that acceptance is performed separately in VMware Firefox.
