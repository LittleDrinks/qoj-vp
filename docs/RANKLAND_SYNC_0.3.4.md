# RankLand delayed-result synchronization — 0.3.4

The participant Submissions toolbar now has **同步到 RankLand** for configured
contests. One click refreshes QOJ and synchronizes confirmed results. While
Firefox is running, the same action enables later automatic delivery and
reopening of the exact scoreboard in an inactive tab. Closing Firefox stops
polling; reopening resumes from the persistent ledger and transfer journal.

## Time and ordering

The score uses QOJ's verified submission time relative to the local contest
start. A result received five minutes later keeps its original submission time.
The local click timestamp is not a substitute for server acceptance time.

Within each problem, a pending/unknown submission holds later results until its
outcome is known. Other problems proceed. Numeric QOJ submission IDs distinguish
two genuine attempts made at the same instant. Rejudging replaces the owned
record; rejudging to pending withdraws the old final result until resolved.

Ending the local contest stops new submissions, but not settlement. The helper
selects sessions with pending receipts/results, incomplete source refreshes,
unacknowledged projections, or no complete post-deadline history pass. A source
outage leaves a retryable status instead of reporting a fresh successful fetch.

## Original RankLand compatibility

RankLand's current record form ignores an already accepted problem and stops
accepting records when playback finishes. The new adapter reconciles the
original version-2 archive, then lets the unmodified original application
render and calculate the scoreboard.

The adapter is pinned to `/assets/index-ad07c00e.js`, as used in the checked-in
fixture. Its SHA-256 is
`9121b4ca71c23a3edf48c5b3e858f7e5d62117a011837dc4ec3bc6c6b9b2916e`.
Runtime compatibility checks the bundle path, archive schema, public contest
duration/problem indices, and displayed problem headers. An upstream change
stops the import and preserves the QOJ ledger for a compatibility update.

The import has these invariants:

- Only one page may write a given replay. The page first navigates to the
  original site's setup document so its previous timers and pagehide save have
  finished. The adapter never races a live Vue writer by editing its storage.
- A write-ahead journal and pre-import backup live in extension storage. The
  archive write compares the exact old value before replacement. Lost replies
  are recovered by inspecting the planned records, without appending them again.
- Source ownership is kept separately, with source ID, revision, record and
  index. Old per-submission receipts migrate only when the actual records match.
- Unowned manual records remain intact. Conflicting edits, reset archives or
  matching records without ownership stop the operation for review.
- Team name, organization, clock, pause state and playback speed are retained.
  Only changed record content causes navigation/reload; an unchanged projection
  does not reload the page.
- The native helper atomically acknowledges the entire plan token. A newer
  verdict, membership or target cannot be acknowledged by an older transfer.

This is compatibility with the original local archive, not a public RankLand
server submission API. RankLand may briefly reload when records change. No QOJ
source submission is retried by this synchronization mechanism.

## Verification

- Python: 165 tests passed, including delayed acceptance versus local click time,
  late judgments, per-problem barriers, restart/settlement and stale batch ACKs.
- Node: 193 tests passed, including actual injected archive-write code under a
  fake document, write/readback interruption, compare-and-set conflicts, manual
  data preservation, caller races and participant button behavior.
- Mozilla lint: zero errors and the same three pre-existing warnings.
- Hydro Firefox ESR: isolated run `a52c08f7aa314619b4eaa4807532b12c`, **7 checks
  passed**, using the unmodified original RankLand bundle and a GET-only QOJ
  fixture. No real QOJ VP was opened and the judge fixture received **0 POSTs**.

The Firefox run verified actual rendered scores:

| Scenario | Original RankLand result |
| --- | --- |
| Earlier A waits while later A is AC | A is held; B continues |
| Late A WA at 20:15, A AC at 22:05 | 1 solved, 42 minutes penalty |
| Two separate B WAs at the same second, then B AC at 30:00 | 2 solved, 112 total penalty |
| A AC becomes TL; B AC temporarily rejudges | A is corrected; pending B is withdrawn and later restored |
| CE entered through the original manual form | Preserved exactly once across synchronization |
| Close and reopen the same scoreboard | Records and 1 solved / 70 penalty retained |
| Close an ended scoreboard, then fire the normal refresh alarm | Automatically reopens inactive; late AC at 4:59:40.200 gives 299 penalty; clock remains ended |

All tested extension and Python executable hashes match the release working
tree; the later README explanation is the only documentation-only difference.
The test browser exited, its profile was removed, alias native registration was
cleaned, and the production native host manifest was unchanged. Results and
screenshots are retained locally under `artifacts/rankland-sync-0.3.4/`.

`scripts/run_hydro_ci.py` now includes this offline original-application
regression. The existing optional online RankLand check remains separate.

Both the Firefox extension and the on-demand Python helper must be updated to
0.3.4; the new helper methods are needed for this synchronization path.

## Signed release

The [0.3.4 release](https://github.com/LittleDrinks/qoj-vp/releases/tag/v0.3.4)
is published from `db6bfcc6bda8abc9164ce88147a85fc8e2020b99`.
The [signing workflow](https://github.com/LittleDrinks/qoj-vp/actions/runs/41429095357)
passed its Python/Node tests, Mozilla lint, AMO unlisted signing and payload
verification. The downloaded release checksums and Python source match the
tested files. The signed XPI hash is
`29a470deab68ac76b00cfb5159554395af1c469a2bbe3a61629a0c1b940a3bcd`.

All release assets were copied to
`E:\shared\qoj-vp-mvp-release\0.3.4-signed` and read back for checksum verification.
The normal VMware Firefox profile and its helper were not replaced. This release
does not claim a new permanent-install/restart test; the prior signing-flow
installation evidence remains in [0.3.3 release verification](RELEASE_0.3.3.md).

The live `https://vp.xcpc.link/` script was fetched on 2026-11-02 and matched both
the pinned path and SHA-256 above. This is a script compatibility check, not a
real-account VP or source-submission test.
Local delivery proof: `artifacts/release-0.3.4-delivery.json`.
