"""Isolated QOJ/Firefox preflight core. It never submits code or reads cookies."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
import uuid

import requests
from requests.structures import CaseInsensitiveDict


PROTOCOL_VERSION = 1
QOJ_BASE = "https://qoj.ac"
NATIVE_NAME = "org.littledrinks.qoj_preflight"
MAX_RETURN_ZIP = 512 * 1024


class ProtocolError(Exception):
    pass


def now_ms():
    return int(time.time() * 1000)


def timestamp_ms(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("startAt must be an ISO timestamp or nonnegative epoch milliseconds")
    return int(value)


class StateStore:
    def __init__(self, state_dir=None):
        setting = state_dir or os.environ.get("QOJ_PREFLIGHT_STATE_DIR")
        if not setting:
            raise ValueError("QOJ_PREFLIGHT_STATE_DIR is required for this isolated preflight")
        self.directory = Path(setting).expanduser().resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / "preflight.sqlite3"
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at_ms INTEGER NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER NOT NULL,
                kind TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
        """)
        self.db.commit()
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def trace(self, kind, data):
        self.db.execute("INSERT INTO trace(created_at_ms,kind,data_json) VALUES(?,?,?)", (now_ms(), kind, json.dumps(data)))
        self.db.commit()

    def create_session(self, args):
        session_id = str(args.get("sessionId") or uuid.uuid4())
        if not session_id or len(session_id) > 120 or any(ord(c) < 32 for c in session_id):
            raise ValueError("Invalid sessionId")
        start = args.get("startAt", args.get("startedAt"))
        start = timestamp_ms(start) if start is not None else None
        duration = int(args.get("durationMs", 5 * 60 * 60 * 1000))
        if duration <= 0 or duration > 14 * 24 * 60 * 60 * 1000:
            raise ValueError("Invalid durationMs")
        state = args.get("state", "running" if start is not None else "prepared")
        if state not in {"draft", "prepared", "running", "finished", "archived"}:
            raise ValueError("Invalid session state")
        record = {
            "version": 1,
            "sessionId": session_id,
            "platform": "qoj",
            "contestId": str(args.get("contestId", "")),
            "title": str(args.get("title", "Preflight VP"))[:200],
            "createdAt": now_ms(),
            "startAt": start,
            "durationMs": duration,
            "state": state,
        }
        if args.get("ranklandUrl"):
            url = str(args["ranklandUrl"])
            parsed = urlparse(url)
            allowed = (parsed.scheme == "https" and parsed.hostname == "vp.xcpc.link") or (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            )
            if not allowed or parsed.username or parsed.password:
                raise ValueError("RankLand resume URL must use RankLand or the local fixture origin")
            record["ranklandUrl"] = url
        try:
            self.db.execute("INSERT INTO sessions VALUES(?,?,?)", (session_id, record["createdAt"], json.dumps(record)))
            self.db.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Session already exists; preflight does not overwrite it") from exc
        self.trace("session.created", {"sessionId": session_id})
        return self.inspect_session({"sessionId": session_id})

    def inspect_session(self, args):
        session_id = str(args.get("sessionId", ""))
        row = self.db.execute("SELECT record_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("Unknown sessionId")
        record = json.loads(row[0])
        current = timestamp_ms(args["nowMs"]) if "nowMs" in args else now_ms()
        elapsed = max(0, current - record["startAt"]) if record["startAt"] is not None else 0
        record["elapsedMs"] = min(elapsed, record["durationMs"])
        record["observedAt"] = current
        record["effectiveState"] = "finished" if record["state"] == "running" and elapsed >= record["durationMs"] else record["state"]
        return record

    def list_sessions(self, args=None):
        rows = self.db.execute("SELECT session_id FROM sessions ORDER BY created_at_ms,session_id").fetchall()
        return {"sessions": [self.inspect_session({"sessionId": r[0]}) for r in rows]}


class BrowserSession:
    """The requests-shaped transport used by the real imported QojClient.

    The callback exchanges HTTP envelopes with Firefox. The browser owns all
    authentication and network requests; this object has no cookie import path.
    """

    def __init__(self, exchange, fixture_origin=None):
        self.exchange = exchange
        self.headers = CaseInsensitiveDict()
        self.cookies = requests.cookies.RequestsCookieJar()
        self.fixture_origin = None
        self.last_response = None
        self.request_count = 0
        self.transports = []
        if fixture_origin:
            parsed = urlparse(str(fixture_origin))
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("fixtureOrigin must be a loopback HTTP(S) origin")
            self.fixture_origin = str(fixture_origin).rstrip("/")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        raise requests.RequestException("POST is disabled in this read-only preflight")

    def request(self, method, url, **kwargs):
        if method != "GET":
            raise requests.RequestException("Only GET is allowed in this preflight")
        logical = urlparse(str(url))
        if logical.scheme != "https" or logical.netloc != "qoj.ac" or logical.username or logical.password:
            raise requests.RequestException("Only the logical https://qoj.ac origin is allowed")
        target = str(url)
        if self.fixture_origin:
            target = self.fixture_origin + urlunparse(("", "", logical.path, logical.params, logical.query, ""))
        outgoing_headers = {
            k: v for k, v in {**self.headers, **kwargs.get("headers", {})}.items()
            if k.lower() not in {"user-agent", "cookie", "cookie2", "host", "origin", "referer", "content-length", "connection", "accept-encoding"}
            and not k.lower().startswith(("sec-", "proxy-", "access-control-request-"))
        }
        self.request_count += 1
        request = {
            "url": target,
            "logicalUrl": str(url),
            "method": "GET",
            "headers": outgoing_headers,
            "timeoutMs": int(float(kwargs.get("timeout", 20)) * 1000),
            "fixture": bool(self.fixture_origin),
        }
        reply = self.exchange(request)
        if reply.get("error"):
            error = requests.ConnectionError("Browser HTTP request failed")
            details = reply["error"].get("details", {}) if isinstance(reply["error"], dict) else {}
            error.preflight_error = {key: details[key] for key in ("code", "stage", "causeCode", "exceptionName", "sanitizedBuiltinMessage") if isinstance(details.get(key), str)}
            if not error.preflight_error:
                error.preflight_error = {"code": "BROWSER_HTTP_BRIDGE_FAILED", "stage": "browser-http"}
            raise error
        payload = reply.get("response", reply)
        if "status" not in payload or "bodyBase64" not in payload:
            raise ProtocolError("Incomplete HTTP response envelope")
        actual_url = str(payload.get("url") or target)
        if self.fixture_origin and actual_url.startswith(self.fixture_origin + "/"):
            actual_url = QOJ_BASE + actual_url[len(self.fixture_origin):]
        response = requests.Response()
        response.status_code = int(payload["status"])
        response.url = actual_url
        response.headers = CaseInsensitiveDict(payload.get("headers", {}))
        try:
            response._content = base64.b64decode(payload["bodyBase64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ProtocolError("Invalid browser response encoding") from exc
        response.encoding = requests.utils.get_encoding_from_headers(response.headers) or "utf-8"
        response.request = requests.Request("GET", str(url)).prepare()
        self.last_response = response
        self.transports.append({"transport": payload.get("transport"), "pageOrigin": payload.get("pageOrigin"), "tabId": payload.get("tabId")})
        return response

    def close(self):
        return None


def load_qoj_modules():
    setting = os.environ.get("QOJ_PREFLIGHT_QOJ_PATH")
    if not setting:
        raise ValueError("QOJ_PREFLIGHT_QOJ_PATH is required for QOJ operations")
    root = Path(setting).expanduser().resolve()
    if not (root / "qoj_submitter" / "client.py").is_file():
        raise ValueError("QOJ_PREFLIGHT_QOJ_PATH must contain qoj_submitter/client.py")
    sys.path.insert(0, str(root))
    client = importlib.import_module("qoj_submitter.client")
    samples = importlib.import_module("qoj_submitter.samples")
    for module in (client, samples):
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise ValueError("Imported QOJ module does not come from the configured source path")
    metadata = {
        "clientModule": client.QojClient.__module__,
        "samplesModule": samples.__name__,
        "sourcePath": str(root),
        "clientSha256": hashlib.sha256(Path(client.__file__).read_bytes()).hexdigest(),
        "samplesSha256": hashlib.sha256(Path(samples.__file__).read_bytes()).hexdigest(),
    }
    return client, samples, metadata


def qoj_client(args, exchange):
    module, samples, metadata = load_qoj_modules()
    session = BrowserSession(exchange, args.get("fixtureOrigin"))
    client = module.QojClient(QOJ_BASE, session=session)
    return client, session, samples, metadata


def valid_id(value, label):
    value = str(value or "")
    if not value.isdigit():
        raise ValueError(f"{label} must contain only digits")
    return value


def qoj_contest_and_sample(args, exchange):
    cid = valid_id(args.get("contestId"), "contestId")
    client, session, samples_module, metadata = qoj_client(args, exchange)
    contest = client.contest(cid)
    label = str(args.get("problemLabel") or next(iter(contest["problems"]))).upper()
    if label not in contest["problems"]:
        raise ValueError("Requested problem label is not in this contest")
    single = {**contest, "problems": {label: contest["problems"][label]}}
    # The imported samples function prints human progress. Never allow that on
    # the native messaging stdout byte stream.
    with contextlib.redirect_stdout(sys.stderr):
        sample_files, extras, warnings = samples_module.download(client, single)
    zip_data = samples_module.zip_bytes(sample_files) if sample_files else b""
    result = {
        "source": "fixture" if args.get("fixtureOrigin") else "real-qoj-browser",
        "qojLibrary": metadata,
        "contest": {"id": contest["id"], "name": contest["name"]},
        "problems": [{"label": k, **v, "url": f"{QOJ_BASE}/contest/{cid}/problem/{v['id']}"} for k, v in contest["problems"].items()],
        "selectedProblem": label,
        "samples": {
            "files": [{"name": k, "bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()} for k, v in sample_files.items()],
            "extraFiles": [{"name": k, "bytes": len(v)} for k, v in extras.items()],
            "warnings": warnings,
            "zipBytes": len(zip_data),
            "zipSha256": hashlib.sha256(zip_data).hexdigest() if zip_data else None,
            "zipFilename": f"samples-{label}.zip",
        },
        "browserRequests": session.request_count,
        "browserTransport": session.transports,
    }
    if args.get("includeZip") and zip_data:
        if len(zip_data) <= MAX_RETURN_ZIP:
            result["samples"]["zipBase64"] = base64.b64encode(zip_data).decode("ascii")
        else:
            result["samples"]["zipOmittedReason"] = "Archive is larger than the preflight single-message transfer limit"
    return result


def qoj_problem_form(args, exchange):
    cid = valid_id(args.get("contestId"), "contestId")
    client, session, _samples, metadata = qoj_client(args, exchange)
    pid = args.get("problemId")
    if pid is None:
        contest = client.contest(cid)
        label = str(args.get("problemLabel") or next(iter(contest["problems"]))).upper()
        if label not in contest["problems"]:
            raise ValueError("Unknown problem label")
        pid = contest["problems"][label]["id"]
    pid = valid_id(pid, "problemId")
    form = client.form(cid, pid)
    # No token or raw HTML is returned, logged, or persisted.
    pdf_candidates = []
    soup = importlib.import_module("qoj_submitter.client").soup(session.last_response.text)
    for element in soup.select("a[href], iframe[src], embed[src], object[data]"):
        href = element.get("href") or element.get("src") or element.get("data")
        candidate = urljoin(session.last_response.url, href)
        parsed = urlparse(candidate)
        text = element.get_text(" ", strip=True)
        if parsed.scheme != "https" or parsed.netloc != "qoj.ac" or any(k in parsed.query.lower() for k in ("token", "secret", "password", "apikey")):
            continue
        if parsed.path.lower().endswith(".pdf") or "pdf" in text.lower() or element.get("type") == "application/pdf":
            if candidate not in [item["url"] for item in pdf_candidates]:
                pdf_candidates.append({"url": candidate, "label": text[:120]})
    return {
        "source": "fixture" if args.get("fixtureOrigin") else "real-qoj-browser",
        "qojLibrary": metadata,
        "contestId": cid,
        "problemId": pid,
        "languages": list(form.languages),
        "csrfPresent": bool(form.token),
        "actionPath": urlparse(form.action).path,
        "pdfCandidates": pdf_candidates,
        "browserRequests": session.request_count,
        "browserTransport": session.transports,
    }


def dispatch(method, args, exchange, store):
    if not isinstance(args, dict):
        raise ValueError("Task args must be an object")
    if method == "hello":
        page_url = args.get("pageUrl")
        if page_url:
            parsed = urlparse(str(page_url))
            if parsed.scheme != "moz-extension" or not parsed.netloc or parsed.path != "/test.html":
                raise ValueError("pageUrl must identify the extension test.html")
            page_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        store.trace("hello", {"pid": os.getpid(), "pageUrl": page_url})
        return {"protocolVersion": PROTOCOL_VERSION, "pid": os.getpid(), "stateDir": str(store.directory), "sqlitePath": str(store.path), "pageUrl": page_url, "qojPathConfigured": bool(os.environ.get("QOJ_PREFLIGHT_QOJ_PATH"))}
    if method == "create_session":
        return store.create_session(args)
    if method == "inspect_session":
        return store.inspect_session(args)
    if method == "list_sessions":
        return store.list_sessions(args)
    if method == "qoj_contest_and_sample":
        return qoj_contest_and_sample(args, exchange)
    if method == "qoj_problem_form":
        return qoj_problem_form(args, exchange)
    raise ValueError("Unknown or disabled preflight method")
