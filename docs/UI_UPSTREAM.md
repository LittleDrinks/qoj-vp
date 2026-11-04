# DOMjudge team and Jury UI adaptation

The workbench uses DOMjudge 9.0.1's team-page structure and its actual stylesheet. It is a Firefox extension adapting QOJ, not a DOMjudge server. The team view includes Home/Submissions, Problemset, the submit interaction, one local team's progress row and a link to original RankLand. A separate Jury view owns local contest configuration and sample management. Both views belong to the same local extension; this is a workflow distinction, not an authentication or permission boundary.

## Fixed upstream source

DOMjudge repository: <https://github.com/DOMjudge/domjudge>

Fixed commit: `90bbb727906efb438ac2ec7512c09f17824cfc41` (9.0.1).

Source byte/Git-blob verification is in `preflight/domjudge-reference/source-manifest.json`. The full downloaded reference files remain under its `upstream/` directory.

| Upstream file under webapp/ | Extension use |
| --- | --- |
| `templates/base.html.twig` | Local CSS/script ordering and container structure in `ui.html`; dynamic server routes become extension actions. |
| `templates/team/menu.html.twig` | Dark fixed navbar, Home/Problemset/Scoreboard navigation, literal `a.nav-link > span.btn.btn-success.btn-sm` Submit control and countdown. Out-of-scope menu items omitted. |
| `templates/partials/menu_change_contest.html.twig` | Original trophy `a.nav-link.dropdown-toggle`, `dropdown-menu scrollable-menu`, and Change Contest row. The current session appears in the toggle; other saved sessions, including archived ones, appear as links. The trophy menu switches existing sessions only. New contest belongs to the Jury contest list. Long QOJ titles truncate in the navbar, retaining the full title and accessible name. |
| `templates/team/partials/index_content.html.twig` | Top team's progress and the original two-column row: Submissions on the left, Clarifications and Clarification Requests on the right. QOJ discussions are linked, not synchronized; unavailable data is stated explicitly. Contest management stays in Jury. |
| `templates/jury/contests.html.twig` | `Contests` / `All available contests` headings, table presentation, and the bottom `btn btn-primary` Add new contest action. Server-wide administration columns and current-contest cards are omitted; local session rows link to their details. |
| `templates/jury/contest.html.twig` | Contest heading, responsive row/column property table, and `table table-sm table-striped` presentation. The editable local title/duration, RankLand URL, resource import, local finish/archive/delete controls are extension-specific. |
| `templates/jury/menu.html.twig` | Contests and Team navigation use upstream navbar link classes and icons. The reciprocal Jury link is an extension view switch. |
| `templates/team/partials/submission_list.html.twig` | `data-table table table-hover table-striped table-sm` and time/problem/lang/result columns. Added QOJ receipt link and explicit unknown-outcome reconciliation. |
| `templates/partials/problem_list.html.twig` | Actual responsive card grid, badge/title/card-subtitle and ordinary-flow layout. Submit retains literal `a.justify-content-center > span.btn.btn-success`; statement/samples retain the upstream secondary-anchor styles and icons. The statement control is an ordinary QOJ problem link, opening a new tab without a native-helper or printing operation. Its inherited `file-pdf` icon preserves the original control appearance; the linked statement may be HTML. Unknown time/memory/type metadata is omitted instead of invented. |
| `templates/team/submit_modal.html.twig` | Original `h5.modal-title`, single source-file input, form row classes, file size/mtime `alert` without a gray background, Cancel/Submit. Per-problem modal hides the selected Problem row and uses the actual problem name in its title. QOJ does not expose entry-point input, which remains hidden. |
| `templates/team/partials/submit_scripts.html.twig` | File-basename problem detection only while autodetect is selected, selectable language, file/problem/language confirmation. No QOJ Java/Kotlin entry-point field is invented. |
| `public/js/domjudge.js` | `humanReadableTimeDiff` and `humanReadableBytes` adapted with the same interval thresholds. The rest of the server AJAX code is not loaded. |
| `src/Twig/TwigExtension.php`, `printResult` | Same `sol`, `sol_correct`, `sol_incorrect`, `sol_queued` styles. UI keeps QOJ's unknown state separate from a rejected verdict. |
| `public/style_domjudge.css` | Copied byte-for-byte into `extension/assets/domjudge/style_domjudge.css`. |

Jury templates were inspected at the same fixed commit: [contest list](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/templates/jury/contests.html.twig), [contest detail](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/templates/jury/contest.html.twig), and [Jury menu](https://github.com/DOMjudge/domjudge/blob/90bbb727906efb438ac2ec7512c09f17824cfc41/webapp/templates/jury/menu.html.twig). These adaptations reuse structure and packaged styles; they do not claim whole-page pixel identity or implement DOMjudge server administration.

Twig is a server template language. `ui.html` and `ui.js` retain the listed DOM structure and classes but replace Twig loops/routes/filters with DOM updates and native-helper requests. No PHP/Twig runtime is packaged. `ui.css` contains the small VP-specific additions; the upstream stylesheet remains unchanged.

The Home row reads the original RankLand team's primary rank, score and penalty
every ten seconds while the workbench is visible. Per-problem cells retain QOJ's
confirmed submissions. A closed or unavailable scoreboard can supply a saved
snapshot, clearly labeled with its original observation time; unknown rank or
penalty remains a dash. Session changes and replay URL changes invalidate the
previous snapshot. The read-only score request does not refresh or submit to QOJ.

Language preferences match `qoj-submitter`'s `choose_language` aliases at pinned commit `807ce1be13d67916b2716f8221a10a12731977fe`, including C++20, Python3 and Java21. Only exact normalized available options are inferred; missing/ambiguous variants require a manual selection. The actual selected language is still validated by the backend before submission.

## Packaged third-party assets

These are local byte-for-byte copies of the actual files, not the symlink text found in DOMjudge's `public/` Git paths. There are no CDN script, stylesheet or font dependencies at runtime. `extension/assets/UPSTREAM.json` records each packaged file's SHA-256 and source-reference path.

| Package | Version / fixed source | License copy |
| --- | --- | --- |
| DOMjudge | 9.0.1 / `90bbb727906efb438ac2ec7512c09f17824cfc41` | `assets/licenses/DOMjudge-COPYING` (GPL-2.0-or-later as declared by upstream README) |
| Bootstrap | 5.3.7 / `e0032ae6a5a628a51a8552091816cec09b6434df` | `assets/licenses/Bootstrap-LICENSE` (MIT) |
| Font Awesome Free | 6.5.2 CSS/license at `c0f460dca7f7688761120415ff3c9cf7f73119be`; WOFF2 from the official DOMjudge image below | `assets/licenses/FontAwesome-LICENSE.txt` (CSS/code MIT, fonts SIL OFL 1.1, icons CC BY 4.0) |

Bootstrap and Font Awesome versions match the fixed DOMjudge `webapp/composer.lock`. Reference manifests are `third-party-manifest.json`, `fontawesome-manifest.json`, and `composer-frontend-lock-extract.json` in `preflight/domjudge-reference/`.

The three packaged Font Awesome WOFF2 files are copied from the actual official `domjudge/domserver:9.0.1` image at immutable digest `sha256:e9704bdae8e08440eb0042c9817116dc9767a511f577e9318c4f0710ad5b5727`, not the previously downloaded Git-tag font binaries. The declared Font Awesome version is the same, but these font bytes differ. `assets/UPSTREAM.json` records their new hashes, official image digest, extraction paths and local reference copies; the license is unchanged. CSS/Bootstrap assets are unchanged and have been independently compared byte-for-byte with the official image.

`preflight/visual-reference/rendered/` contains sanitized literal HTML from that real server. The current Navbar/card/submit markup follows those captures, with the original reference configured to `sourcefiles_limit=1` to match QOJ's single-source capability. Disabled Submit retains the original inner `.disabled` class and attribute; the outer anchor additionally has `aria-disabled`, is removed from the tab order, and its handler refuses activation. These structural/source checks do not by themselves establish screenshot or computed-style equivalence.

The derived UI files carry `GPL-2.0-or-later` notices. The per-package licenses remain separate. The root project must retain these files when building an XPI/source distribution.

## Verification

Use the Hydro Firefox fixtures in [CI.md](CI.md) to compare the fixed upstream
reference with the extension at the same viewport. Source reuse alone does not
establish pixel equivalence. Architecture and state ownership are described in
[ARCHITECTURE.md](ARCHITECTURE.md).
