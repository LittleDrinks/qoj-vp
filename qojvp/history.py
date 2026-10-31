"""Conservative QOJ history/detail parsing, independent of VP and browser state."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

FINAL_VERDICTS = {"CORRECT", "WRONG-ANSWER", "TIMELIMIT", "RUN-ERROR", "COMPILER-ERROR",
                  "NO-OUTPUT", "OUTPUT-LIMIT", "MEMORY-LIMIT", "PRESENTATION-ERROR"}
VERDICT_ALIASES = (
    ("COMPILER-ERROR", ("compile error", "compilation error", "compiler error", "ce")),
    ("TIMELIMIT", ("time limit exceeded", "time limit", "timelimit", "tle")),
    ("MEMORY-LIMIT", ("memory limit exceeded", "memory limit", "memorylimit", "mle")),
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
    for result, aliases in VERDICT_ALIASES:
        if text in aliases:
            return result
    # A score is meaningful only when the list explicitly exposes the score;
    # partial/zero scores need the detail's actual failing verdict.
    if score is not None and score == 100:
        return "CORRECT"
    return "UNKNOWN"


def detail_verdict(html, score=None):
    page = BeautifulSoup(html, "html.parser")
    headers = [node for node in page.select(".card-header, .panel-heading")
               if node.get_text(" ", strip=True).lower() == "details"]
    scope = headers[-1].parent if headers else page
    if scope.select_one('[id^="status_details_"]'):
        return {"verdict": "JUDGING", "rawVerdict": "Judging", "pending": True}
    observed = []
    for node in scope.select(".uoj-status, .col-sm-2, .panel-title, .card-header, table td"):
        text = node.get_text(" ", strip=True)
        parsed = verdict(text)
        if parsed != "UNKNOWN":
            observed.append((parsed, text))
    failures = [item for item in observed if item[0] in FINAL_VERDICTS - {"CORRECT"}]
    if failures:
        result, raw = failures[0]
    elif any(item[0] == "JUDGING" for item in observed):
        result, raw = "JUDGING", "Judging"
    elif score == 100 and any(item[0] == "CORRECT" for item in observed):
        result, raw = "CORRECT", "Accepted"
    else:
        # Passing an earlier test can never erase a later zero/partial score.
        result, raw = "UNKNOWN", "Detailed verdict unavailable"
    return {"verdict": result, "rawVerdict": raw, "pending": result == "JUDGING"}


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
        for row in table.select("tr"):
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            sid_link = next((a for a in row.select("a[href]")
                             if re.fullmatch(r"/submission/\d+/?", urlparse(a['href']).path)), None)
            if not sid_link:
                continue
            submitter = next((a for a in row.select("a[href]")
                              if urlparse(a['href']).path.startswith('/user/profile/')), None)
            if submitter is None:
                malformed += 1
                continue
            actual_account = urlparse(submitter['href']).path.removeprefix('/user/profile/').rstrip('/')
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
            pending = bool(row.select_one('[id^="status_details_"]') or
                           re.search(r"update_judgement_status_details\s*\(", str(row)))
            time_node = row.select_one('time[datetime]')
            display = row.get_text(" ", strip=True)
            dates = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?", display)
            raw_time = time_node.get('datetime') if time_node else dates[0] if dates else cells[-1].get_text(" ", strip=True)
            at = timestamp(raw_time)
            if at is None:
                warnings.append(f"#{sid}: absolute submission time is not verified")
            parsed = "JUDGING" if pending else verdict(raw, score)
            result[sid] = {"id": sid, "account": actual_account, "problemId": pid,
                           "problemLabel": pid_to_label[pid], "language": cells[language_index].get_text(" ", strip=True)
                           if language_index is not None and language_index < len(cells) else "",
                           "submittedAt": at, "rawTime": str(raw_time)[:100],
                           "timeSource": "provider-absolute" if at is not None else "unverified-display",
                           "verdict": parsed, "rawVerdict": raw, "score": score, "pending": pending,
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
