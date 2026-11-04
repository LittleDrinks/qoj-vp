"""Conservative QOJ history/detail parsing, independent of VP and browser state."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

FINAL_VERDICTS = {"CORRECT", "WRONG-ANSWER", "TIMELIMIT", "RUN-ERROR", "COMPILER-ERROR",
                  "NO-OUTPUT", "OUTPUT-LIMIT", "MEMORY-LIMIT", "PRESENTATION-ERROR"}
VERDICT_ALIASES = (
    ("COMPILER-ERROR", ("compile error", "compilation error", "compiler error", "ce")),
    ("TIMELIMIT", ("time limit exceeded", "time limit", "timelimit", "tle", "tl")),
    ("MEMORY-LIMIT", ("memory limit exceeded", "memory limit", "memorylimit", "mle", "ml")),
    ("OUTPUT-LIMIT", ("output limit exceeded", "output limit", "ole")),
    ("RUN-ERROR", ("runtime error", "run time error", "run-error", "re")),
    ("NO-OUTPUT", ("no output", "no-output")),
    ("WRONG-ANSWER", ("wrong answer", "wrong-answer", "wa")),
    ("PRESENTATION-ERROR", ("presentation error", "pe")),
    ("CORRECT", ("accepted", "correct", "ac")),
    ("JUDGING", ("judging", "waiting", "pending", "running", "compiling", "queued", "unjudged")),
)


def verdict(text, score=None):
    text = re.sub(r"\s+", " ", str(text or "").strip().lower()).replace("_", " ")
    # An accepted contest run may later fail an added test. This exact wrapper
    # is present on QOJ's detail page after the earlier Accepted test rows.
    extra = re.fullmatch(r'extra test failed\s*:\s*(.+?)\s+on\s+\d+', text)
    if extra:
        current = verdict(extra.group(1))
        return current if current in FINAL_VERDICTS - {'CORRECT'} else 'UNKNOWN'
    # QOJ can retain the contest result before the current result ("AC, TL").
    # Only accept an exact pair of known results; a historic AC must not hide
    # a later failure, pending rejudge or unrecognized result.
    parts = text.split(',')
    if len(parts) > 1:
        if len(parts) != 2 or any(verdict(part) == 'UNKNOWN' for part in parts):
            return 'UNKNOWN'
        return verdict(parts[1], score)
    # QOJ's verified accepted marker has this exact suffix. Do not strip
    # other punctuation/letters: an unrecognized value must remain unknown.
    if text == 'ac ✓':
        text = 'ac'
    for result, aliases in VERDICT_ALIASES:
        if text in aliases:
            if result == 'CORRECT' and score is not None and score != 100:
                return 'UNKNOWN'
            return result
    # A score is meaningful only when the list explicitly exposes the score;
    # partial/zero scores need the detail's actual failing verdict.
    if score is not None and score == 100 and (not text or re.fullmatch(r'\d+(?:\.\d+)?', text)):
        return "CORRECT"
    return "UNKNOWN"


def detail_verdict(html, score=None):
    page = BeautifulSoup(html, "html.parser")
    headers = [node for node in page.select(".card-header, .panel-heading")
               if node.get_text(" ", strip=True).lower() == "details"]
    scope = headers[-1].parent if headers else page
    if scope.select_one('[id^="status_details_"]'):
        return {"verdict": "JUDGING", "rawVerdict": "Judging", "pending": True,
                "verdictSource": "submission-detail"}
    observed, unverified_extra = [], []
    for node in scope.select(".uoj-status, .col-sm-2, .panel-title, .card-header, table td"):
        text = node.get_text(" ", strip=True)
        parsed = verdict(text)
        if parsed != "UNKNOWN":
            observed.append((parsed, text))
        elif re.match(r'^Extra\s+Test\s+Failed\b', text, re.IGNORECASE):
            # The failure is explicit even when its subtype is new/hidden.
            # Earlier AC test rows cannot establish acceptance in this case.
            unverified_extra.append(text)
    failures = [item for item in observed if item[0] in FINAL_VERDICTS - {"CORRECT"}]
    if failures:
        result, raw = failures[0]
    elif any(item[0] == "JUDGING" for item in observed):
        result, raw = "JUDGING", "Judging"
    elif unverified_extra:
        result, raw = 'UNKNOWN', unverified_extra[0]
    elif score == 100 and any(item[0] == "CORRECT" for item in observed):
        result, raw = "CORRECT", "Accepted"
    else:
        # Passing an earlier test can never erase a later zero/partial score.
        result, raw = "UNKNOWN", "Detailed verdict unavailable"
    return {"verdict": result, "rawVerdict": raw, "pending": result == "JUDGING",
            "verdictSource": "submission-detail"}


def timestamp(value):
    """Only accept an absolute timestamp with an explicit zone.

    Plain display dates and native-VP HH:MM:SS need additional verified clock
    metadata. The adapter preserves them without inventing a timezone/start.
    """
    value = str(value).strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.timestamp() * 1000)


def submission_time_metadata(html, cid, account, sid, pid, *, language=None):
    """Verify one detail-table Submit time against its SID, owner and problem.

    A submission detail also has an execution 'Time' column. Only the exact
    'Submit time' header and its own zoned time.uoj-time metadata count; page
    clocks, footer dates and timestamps in unrelated rows cannot supply it.
    """
    page = BeautifulSoup(html, 'html.parser')
    candidates = []
    expected_sid = re.compile(rf'/submission/{re.escape(str(sid))}/?')
    expected_pid = re.compile(rf'/contest/{re.escape(str(cid))}/problem/{re.escape(str(pid))}/?')

    def matches_link(cell, pattern):
        links = []
        for link in cell.select('a[href]'):
            parsed = urlparse(link['href'])
            if parsed.scheme in ('', 'https') and parsed.netloc in ('', 'qoj.ac') and pattern.fullmatch(parsed.path):
                links.append(link)
        return len(links) == 1

    for table in page.select('table'):
        rows = [row for row in table.find_all('tr') if row.find_parent('table') is table]
        if not rows:
            continue
        headers = [cell.get_text(' ', strip=True).casefold() for cell in rows[0].find_all('th', recursive=False)]
        required = ('id', 'problem', 'submitter', 'submit time') + (('language',) if language is not None else ())
        if any(headers.count(name) != 1 for name in required):
            continue
        indexes = {name: headers.index(name) for name in required}
        for row in rows[1:]:
            cells = row.find_all('td', recursive=False)
            if len(cells) != len(headers):
                continue
            if not matches_link(cells[indexes['id']], expected_sid) or not matches_link(cells[indexes['problem']], expected_pid):
                continue
            owners = cells[indexes['submitter']].select('span.uoj-username')
            if len(owners) != 1 or owners[0].get_text(' ', strip=True).casefold() != account.casefold():
                continue
            if language is not None and cells[indexes['language']].get_text(' ', strip=True) != language:
                continue
            times = cells[indexes['submit time']].select('time.uoj-time[datetime]')
            if len(times) != 1:
                continue
            raw = times[0].get('datetime', '')
            at = timestamp(raw)
            if at is not None:
                candidates.append({'submittedAt': at, 'timeSource': 'provider-absolute',
                                   'timeEvidence': {'source': 'submission-detail', 'datetime': raw}})
    return candidates[0] if len(candidates) == 1 else None


def submission_source_hashes(html, cid, account, sid, pid, language):
    """Hash only QOJ's complete `answer` source card, never judge-output pre's.

    Browser HTML parsing normalizes line endings. Compare the complete LF and
    CRLF byte sequences; do not strip spaces or append/remove a final newline.
    Source text lives only in this call and is never returned to the ledger.
    """
    metadata = submission_time_metadata(html, cid, account, sid, pid, language=language)
    if not metadata:
        return None
    page = BeautifulSoup(html, 'html.parser')
    cards = []
    for card in page.select('.card'):
        header = card.find(class_='card-header', recursive=False)
        if header is not None and header.get_text(' ', strip=True) == 'answer':
            cards.append(card)
    if len(cards) != 1:
        return None
    bodies = cards[0].find_all(class_='card-body', recursive=False)
    if len(bodies) != 1:
        return None
    code = [node for pre in bodies[0].find_all('pre', recursive=False)
            for node in pre.find_all('code', recursive=False)]
    if len(code) != 1 or not any(re.fullmatch(r'sh_[A-Za-z0-9_-]+', value) for value in code[0].get('class', [])):
        return None
    text = code[0].get_text('', strip=False).replace('\r\n', '\n').replace('\r', '\n')
    variants = {}
    for ending, source in (('lf', text), ('crlf', text.replace('\n', '\r\n'))):
        try:
            data = source.encode('utf-8')
        except UnicodeEncodeError:
            return None
        if not 0 < len(data) <= 512 * 1024:
            continue
        variants[ending] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    return {'account': account.casefold(), 'contestId': str(cid), 'submissionId': str(sid),
            'problemId': str(pid), 'language': language, 'submittedAt': metadata['submittedAt'],
            'variants': variants} if variants else None


def parse_history(html, cid, account, problems):
    page = BeautifulSoup(html, "html.parser")
    result, warnings = {}, []
    malformed = 0
    saw_table = False
    pid_to_label = {str(p["id"]): label for label, p in problems.items()}
    for table in page.select("table"):
        headers = [node.get_text(" ", strip=True).lower() for node in table.select("thead th")]
        if not headers:
            headers = [node.get_text(" ", strip=True).lower() for node in table.select("tr th")]
        has_columns = any(x in headers for x in ("result", "score", "status"))
        if not has_columns:
            continue
        saw_table = True
        result_index = next(i for i, h in enumerate(headers) if h in ("result", "score", "status"))
        language_index = next((i for i, h in enumerate(headers) if h in ("language", "lang")), None)
        owner_index = next((i for i, h in enumerate(headers) if h in ('submitter', 'username', 'user')), None)
        time_index = next((i for i, h in enumerate(headers) if h in ('time', 'submit time', 'submission time', 'submitted at')), None)
        for row in table.select("tr"):
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            sid_link = next((a for a in row.select("a[href]")
                             if re.fullmatch(r"/submission/\d+/?", urlparse(a['href']).path)), None)
            if not sid_link:
                continue
            if owner_index is None or owner_index >= len(cells):
                malformed += 1
                continue
            # Raw QOJ GETs expose span.uoj-username; frontend JavaScript turns
            # that span into a profile link. Both are authoritative only in
            # the table's owner column, never arbitrary links in other cells.
            owners = {}
            for node in cells[owner_index].select('span.uoj-username, a[href]'):
                if node.name == 'span':
                    name = node.get_text(' ', strip=True)
                else:
                    parsed_owner = urlparse(node['href'])
                    match = re.fullmatch(r'/user/profile/([^/]+)/?', parsed_owner.path)
                    if (not match or parsed_owner.netloc not in ('', 'qoj.ac')
                            or parsed_owner.scheme not in ('', 'https')):
                        continue
                    name = match.group(1)
                if name and not any(ord(char) < 32 for char in name):
                    owners.setdefault(name.casefold(), name)
            if len(owners) != 1:
                malformed += 1
                continue
            actual_account = next(iter(owners.values()))
            if actual_account.casefold() != account.casefold():
                continue
            problem = next((a for a in row.select("a[href]")
                            if re.fullmatch(rf"/contest/{re.escape(cid)}/problem/\d+/?", urlparse(a['href']).path)), None)
            if problem is None or result_index >= len(cells):
                malformed += 1
                continue
            pid = urlparse(problem['href']).path.rstrip('/').rsplit('/', 1)[-1]
            if pid not in pid_to_label:
                continue
            sid = urlparse(sid_link['href']).path.rstrip('/').rsplit('/', 1)[-1]
            raw = cells[result_index].get_text(" ", strip=True)
            score = float(raw) if re.fullmatch(r"\d+(?:\.\d+)?", raw) else None
            score_nodes = cells[result_index].select('a.uoj-score[data-score]')
            invalid_score = False
            if score_nodes:
                value = score_nodes[0].get('data-score', '')
                if len(score_nodes) == 1 and re.fullmatch(r'\d+(?:\.\d+)?', value) and 0 <= float(value) <= 100:
                    score = float(value)
                else:
                    score, invalid_score = None, True
                    warnings.append(f'#{sid}: numeric submission score is not verified')
            pending = bool(row.select_one('[id^="status_details_"]') or
                           re.search(r"update_judgement_status_details\s*\(", str(row)))
            time_cell = cells[time_index] if time_index is not None and time_index < len(cells) else cells[-1]
            time_nodes = time_cell.select('time[datetime]')
            display = time_cell.get_text(" ", strip=True)
            dates = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?", display)
            raw_time = time_nodes[0].get('datetime') if len(time_nodes) == 1 else dates[0] if not time_nodes and len(dates) == 1 else display
            if len(time_nodes) > 1:
                raw_time = ''
            at = timestamp(raw_time)
            if at is None:
                warnings.append(f"#{sid}: absolute submission time is not verified")
            parsed = "JUDGING" if pending else "UNKNOWN" if invalid_score else verdict(raw, score)
            pending = pending or parsed == 'JUDGING'
            result[sid] = {"id": sid, "account": actual_account, "problemId": pid,
                           "problemLabel": pid_to_label[pid], "language": cells[language_index].get_text(" ", strip=True)
                           if language_index is not None and language_index < len(cells) else "",
                           "submittedAt": at, "rawTime": str(raw_time)[:100],
                           "timeSource": "provider-absolute" if at is not None else "unverified-display",
                           "verdict": parsed, "rawVerdict": raw, "score": score, "pending": pending,
                           "verdictSource": "history-result",
                           "historyResult": {"rawVerdict": raw, "score": score, "verdict": parsed},
                           "url": f"https://qoj.ac/submission/{sid}", "state": "confirmed"}
    pages = []
    for link in page.select('a[href]'):
        query = parse_qs(urlparse(link['href']).query)
        for value in query.get('page', []):
            if value.isdigit():
                pages.append(int(value))
    # An empty explicitly rendered tbody is an acceptable empty history page.
    if not saw_table and page.select_one('table tbody') is None:
        raise ValueError("QOJ did not expose a recognizable submissions table")
    return {"submissions": list(result.values()), "lastPage": max(pages, default=1),
            "warnings": warnings, "malformedRows": malformed}
