#!/usr/bin/env python3
"""Export literal original DOMjudge HTML; redact only session token values."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import requests

from reference import BASE, HERE, PRIVATE, docker_bytes, redact_html

OUTPUT = HERE / "rendered"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class LiteralSpans(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.offsets = [0]
        self.offsets += [m.end() for m in re.finditer("\n", html)]
        self.stack = []
        self.spans = []
        self.feed(html)

    def position(self) -> int:
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, dict(attrs), self.position()))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                item = self.stack[i]
                del self.stack[i:]
                end = self.html.index(">", self.position()) + 1
                self.spans.append((*item, end))
                break

    def first(self, tag: str, attr: str, value: str) -> str:
        candidates = [s for s in self.spans if s[0] == tag and (s[1].get(attr) == value if attr != "class" else value in s[1].get("class", "").split())]
        if not candidates:
            raise RuntimeError(f"Original rendered element missing: {tag}.{attr}={value}")
        start, end = min(candidates, key=lambda s: s[2])[2:]
        return self.html[start:end]


def main() -> None:
    credentials = json.loads((PRIVATE / "team-credentials.json").read_text())
    session = requests.Session()
    session.trust_env = False
    response = session.get(BASE + "/login", timeout=10)
    response.raise_for_status()
    token = re.search(r'name="_csrf_token"[^>]*value="([^"]+)"', response.text)
    assert token
    response = session.post(BASE + "/login", data={"_username": credentials["username"], "_password": credentials["password"], "_csrf_token": token[1]}, timeout=10)
    response.raise_for_status()
    if "/login" in response.url:
        raise RuntimeError("Reference team login failed")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    captures = {}
    for name, path, xhr in [
        ("home", "/team", False),
        ("problemset", "/team/problems", False),
        ("submit-page", "/team/submit", False),
        ("submit-modal-generic", "/team/submit", True),
        ("submit-modal-a", "/team/submit/4", True),
    ]:
        response = session.get(BASE + path, headers={"X-Requested-With": "XMLHttpRequest"} if xhr else {}, timeout=10)
        response.raise_for_status()
        html = response.text
        if response.headers.get("Content-Type", "").startswith("application/json"):
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("html"), str):
                raise RuntimeError("Unexpected original DOMjudge AJAX response shape")
            html = payload["html"]
        redacted = redact_html(html)
        if name.startswith("submit-"):
            assert 'Source file</label>' in redacted
            assert 'Source files</label>' not in redacted
            assert not re.search(r'<input\b(?=[^>]*type="file")(?=[^>]*\bmultiple\b)', redacted)
        (OUTPUT / (name + ".html")).write_text(redacted)
        captures[name] = {"requestPath": path, "xhr": xhr, "status": response.status_code, "bytes": len(redacted.encode()), "sha256": hashlib.sha256(redacted.encode()).hexdigest()}
    home = (OUTPUT / "home.html").read_text()
    problemset = (OUTPUT / "problemset.html").read_text()
    assert 'problem-stats-item' not in problemset
    assert 'Limits:' not in problemset
    assert 'Type: pass-fail' in problemset
    nav = LiteralSpans(home).first("nav", "class", "navbar")
    card = LiteralSpans(problemset).first("div", "class", "card")
    for name, content in {
        "navbar": nav,
        "navbar-submit": LiteralSpans(nav).first("a", "href", "/team/submit"),
        "card-a": card,
        "card-submit": LiteralSpans(card).first("a", "href", "/team/submit/4"),
    }.items():
        (OUTPUT / (name + ".html")).write_text(content + "\n")
        captures[name] = {"bytes": len((content + "\n").encode()), "sha256": hashlib.sha256((content + "\n").encode()).hexdigest()}
    image = json.loads(docker_bytes("image", "inspect", "domjudge/domserver:9.0.1"))[0]
    metadata = {"providerVersion": "9.0.1", "sourceBaseUrl": BASE, "sourceImage": "domjudge/domserver:9.0.1", "sourceImageId": image["Id"], "sourceRepoDigests": image["RepoDigests"], "contestId": "qoj-vp-xian-reference", "teamId": "exteam", "firstProblemId": 4, "configuration": {"sourcefiles_limit": 1, "show_public_stats": False, "show_limits_on_team_page": False}, "problemMetadata": {"count": 12, "color": None, "colorRendering": "Original DOMjudge NULL-color fallback: white #ffffff / border #bfbfbf / text #000000"}, "tokenRedaction": "Only token values replaced by CSRF_TOKEN_REDACTED; literal element classes, styles, whitespace preserved.", "captures": captures}
    (OUTPUT / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"directory": str(OUTPUT), "version": "9.0.1", "captures": list(captures), "tokenRedacted": True}))


if __name__ == "__main__":
    main()
