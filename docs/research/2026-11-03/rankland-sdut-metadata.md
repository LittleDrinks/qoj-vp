# RankLand SDUT archive metadata and E2E scope

Checked on 2026-11-03 using unauthenticated public GET requests. No QOJ VP was
started and no source code was submitted.

## Reproduced compatibility gap

The production `VpScoreboardSources.describeReplay()` originally rejected
`sdutpc14` with `MALFORMED_DETAIL`. Its real public contest response has
`problems: null` and `sorter: null`, despite having a valid `srkFileID`.
`sdutpc18_warmup` has the same shape.

The original RankLand bundle, retained at
`preflight/rankland-fixtures/assets/index-ad07c00e.js`, resolves these through
`getPublicContest({uk})`, then `getPublicFile({id: srkFileID})`, then fetches the
file record's `url` as SRK JSON. The CDN path should not be guessed from the
contest key or from an older `srk-storage` base URL.

| Replay | Public file ID | Original SRK facts |
| --- | --- | --- |
| `sdutpc14` | `70792767114055680` | Version 0.3.9, ICPC, 4 hours, 10 problems A–J |
| `sdutpc18_warmup` | `70792799791878144` | Version 0.3.9, ICPC, 2 hours, 13 problems A–M |

Primary endpoints:

- [SDUT 14 public contest](https://rl.algoux.cn/api/v2/public/contests/sdutpc14)
  and [file record](https://rl.algoux.cn/api/v2/public/files/70792767114055680).
- [SDUT 18 warmup public contest](https://rl.algoux.cn/api/v2/public/contests/sdutpc18_warmup)
  and [file record](https://rl.algoux.cn/api/v2/public/files/70792799791878144).
- [SDUT 14 original SRK](https://cdn.algoux.cn/rankland/file/70792767114055680/sdutpc14.srk.json).
- [SDUT 18 warmup original SRK](https://cdn.algoux.cn/rankland/file/70792799791878144/sdutpc18th_warmup.srk.json).

The downloaded SDUT 14 file is 199410 bytes, SHA-256
`d97eb083ea1f63217a39c2a1c7cc939a702e3b03ab94d38edd20302d7d1d0629`.
The SDUT 18 warmup file is 222380 bytes, SHA-256
`9458292c8a7f8c4b838faa77f91a8463d42c9f7011bb44f53fe3b67d6f08189a`.
Both match the corresponding public file records.

## Implemented behavior

When either public problem metadata or scoring metadata is null/missing, the
resolver reads the original SRK through the public file endpoint. It verifies
the file ID, contest ID, `RankMain` category, observed CDN path, size and SHA-256
before reading metadata. It accepts the general SRK 0.3 schema, checks contest
duration and any already-present public problem metadata for consistency, and
rejects duplicate aliases. Only small problem/scoring metadata is cached;
participant rows remain owned by the original RankLand replay.

Already-complete public contest responses keep their existing request path.
All requests omit credentials and reject redirects. The extension requires
`https://cdn.algoux.cn/*` in its host permissions for the archive fallback.

## What this does and does not verify

The live production resolver now describes both SDUT replays successfully,
using exactly three public GET requests per replay. This enables their original
RankLand pages to be used as replay-side E2E targets.

Neither captured SRK contains QOJ problem links or problem titles. Problem
aliases alone cannot establish correspondence with a QOJ contest. Automatic
matching therefore still returns `PROBLEM_LINKS_MISSING` rather than inventing
a mapping. No corresponding QOJ SDUT contest has been verified in this work.
In particular, the user-selected QOJ 2644 is the Zhengzhou warmup and must not
be paired with either SDUT replay merely for convenience.

Real QOJ submission/preparation testing and SDUT RankLand replay testing must
remain separate until the same problem set is established. A synthetic local
submission event can exercise the SDUT replay adapter without starting an
unrelated real QOJ VP; such a test is not evidence of QOJ-to-SDUT problem mapping.

## Evidence and regression checks

- `artifacts/sdut-rankland-20261103/red-tests.txt`: tests run before the fix.
- `artifacts/sdut-rankland-20261103/live-production-resolver.json`: fresh live
  public requests and production resolver outputs for both SDUT replays.
- The same artifact directory contains the downloaded public file records and
  original SRK files for byte/hash verification. They are local artifacts, not
  checked-in participant fixtures.
- `preflight/test_scoreboard_sources.cjs`: original resolver coverage plus
  archive fallback, exact problem-link matching, foreign-file rejection,
  integrity failures, metadata conflicts and malformed schema cases. Archive
  test fixtures contain no real participant rows.

This verification covers metadata retrieval and matching behavior. It does not
claim that a browser replay has been launched, QOJ submissions have been sent,
or a complete cross-site VP session has been exercised.
