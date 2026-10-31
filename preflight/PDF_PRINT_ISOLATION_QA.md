# PDF statement isolation QA

The prior whole-page `saveAsPDF` path can retain navigation link annotations containing credential query parameters. A raw PDF-byte search is insufficient because PDF streams can be compressed. No retained test input here uses real user HTML, cookies or credential values.

## Candidate boundary

- Original PDF attachments still open directly.
- HTML fallback opens its own new tab, checks the final URL and active tab, then loads the local PDF-only content handler.
- Exactly one `div.tab-pane.active > article.uoj-article.top-buffer-md` must exist. Missing or ambiguous regions reject export; there is no whole-page fallback.
- Only print media hides article-to-body siblings and resets ancestor layout. A USER-origin stylesheet prevents the site's own `!important` navigation rules from defeating isolation. An ancestor-child allowlist also hides newly added outside branches.
- A print-only native-metadata title is added. The original MathJax/MathML statement DOM remains in place.
- Credential-bearing HTML/SVG href attributes are removed for printing and retained solely in the content script's private memory, including their original namespaces. Encoded/case-varied query keys, credential fragments and URL userinfo are covered. Legitimate reference links remain.
- Save, cancel and error all restore attributes, title and href values, disconnect the observer, and remove the injected print stylesheet. Failure to confirm cleanup in a still-open statement tab is reported.

## Run in the existing isolated VM environment

Run `python3 -B preflight/guest_pdf_smoke.py` from the product root. The script creates its own disposable headless Firefox profile and loopback HTTP fixture. It neither changes native-host registration nor reads a user's browser profile. Only the file picker is controlled; the renderer is the real `browser.tabs.saveAsPDF`, not WebDriver printing.

The fixture uses only public `FAKE_*` values. The script first saves a deliberately unsafe synthetic whole-page baseline to prove the test can detect the original failure. It then packages the actual `extension/pdf-content.js` and `pdf-print.css`, prepares the fixture through the real extension messaging/scripting APIs, and checks:

1. Visible screen text, article dimensions and link appearance remain unchanged; MathML remains present.
2. Five credential-bearing HTML/SVG link forms are sanitized while a safe chapter reference remains.
3. Saved PDF, canceled picker and invalid output target all restore the observed DOM and href state. Cancel creates no file.
4. Two active article regions reject preparation before printing.
5. Exactly four picker calls occur (baseline/save/cancel/write failure), the fixture receives zero POSTs, Firefox exits, and the temporary HTTP server stops.

`results/pdf-smoke/summary.json` points to the latest run. Actual artifacts and their per-run summary live in `results/pdf-smoke/isolation-<uuid>/`. The summary records the exact product content-script SHA-256 and `artifacts.statement` / `artifacts.unsafeSyntheticBaseline` paths.

## Required decompressed-PDF verification

If Poppler exists in the guest, the script performs this verification itself. Otherwise it returns `browser_passed_host_audit_pending`; this is not a completed security-verification result. Copy the explicitly synthetic artifacts to the workspace and check them with host Poppler:

- `pdfinfo -url` must show `FAKE_NAV_TOKEN` in the whole-page baseline, proving that the original leak is observable.
- The isolated PDF must have no `FAKE_*`, credential query, credential fragment or userinfo link annotations. The safe `https://example.org/reference?chapter=2` link must remain.
- `pdftotext` must retain the problem title and samples, and exclude every `*_NEVER_PRINT` navigation/sidebar/tab/form/footer marker.
- Render the isolated PDF with Poppler and visually inspect the Chinese statement, mathematical fraction and sample blocks.

For a real QOJ statement rerun, inspect URL output only in memory and report counts/pass/fail. Do not print or persist credential-bearing href values if a negative result is found. The real native-form → dedicated-tab → PDF-picker path is a separate final check after this synthetic regression passes. No source-code POST is involved.

At candidate freeze, only JavaScript/Python syntax was checked by the implementation worker. VM renderer and decompressed-PDF results must be supplied by the parent before calling the issue fixed.
