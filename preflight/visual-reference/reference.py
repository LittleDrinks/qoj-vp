#!/usr/bin/env python3
"""Prepare and inspect the actual official DOMjudge reference (no judgehost)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from html.parser import HTMLParser

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = HERE / "private"
EVIDENCE = ROOT / "artifacts" / "visual-reference"
BASE = "http://127.0.0.1:19081"
CONTAINER = "qoj-vp-domjudge-ref-domserver"


def redact_html(html: str) -> str:
    """Preserve literal markup while removing session-specific token values."""
    def input_value(match: re.Match) -> str:
        tag = match.group(0)
        if re.search(r'\b(?:name|id)\s*=\s*[\"\'][^\"\']*(?:token|csrf)', tag, re.I):
            tag = re.sub(r'(\bvalue\s*=\s*)([\"\'])(.*?)\2', lambda value: value[1] + value[2] + "CSRF_TOKEN_REDACTED" + value[2], tag, flags=re.I | re.S)
        return tag
    html = re.sub(r'<input\b[^>]*>', input_value, html, flags=re.I)
    html = re.sub(r'((?:[\"\']?(?:csrf[_-]?token|_token)[\"\']?)\s*[:=]\s*)([\"\'])(.*?)\2', lambda m: m[1] + m[2] + "CSRF_TOKEN_REDACTED" + m[2], html, flags=re.I)
    html = re.sub(r'(data-csrf-token\s*=\s*)([\"\'])(.*?)\2', lambda m: m[1] + m[2] + "CSRF_TOKEN_REDACTED" + m[2], html, flags=re.I)
    return html


def private_write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    path.chmod(0o600)


def docker_bytes(*args: str) -> bytes:
    result = subprocess.run(["docker", *args], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Docker reference operation failed; raw output withheld")
    return result.stdout


class Page(HTMLParser):
    """Collect public UI structure without input values, scripts, or credentials."""
    def __init__(self, html: str):
        super().__init__()
        self.inputs: list[dict] = []
        self.links: list[dict] = []
        self.forms: list[dict] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if tag in {"input", "select", "textarea", "button"}:
            self.inputs.append({"tag": tag, **{k: attrs[k] for k in ("id", "name", "type", "class", "disabled") if k in attrs}})
        if tag == "a" and attrs.get("href", "").startswith(("/team", "/logout")):
            self.links.append({k: attrs[k] for k in ("href", "class") if k in attrs})
        if tag == "form":
            self.forms.append({k: attrs[k] for k in ("name", "action", "method", "id") if k in attrs})


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    admin_password = docker_bytes("exec", CONTAINER, "cat", "/opt/domjudge/domserver/etc/initial_admin_password.secret").decode().strip()
    if not admin_password or admin_password == "[unknown]":
        raise RuntimeError("Initial reference admin credential is unavailable")
    admin = requests.Session()
    admin.auth = ("admin", admin_password)
    admin.trust_env = False
    info_response = admin.get(BASE + "/api", timeout=10)
    info_response.raise_for_status()
    info = info_response.json()
    assert info["domjudge"]["version"] == "9.0.1"
    users_response = admin.get(BASE + "/api/v4/users", timeout=10)
    users_response.raise_for_status()
    credential_file = PRIVATE / "team-credentials.json"
    if credential_file.exists():
        credentials = json.loads(credential_file.read_text())
    else:
        credentials = {"baseUrl": BASE, "username": "qoj-vp-visual", "password": secrets.token_urlsafe(24), "teamId": "exteam"}
        private_write(credential_file, json.dumps(credentials, indent=2) + "\n")
    # API serialization uses snake_case. A first exploratory account without a
    # team is left unused; do not try to silently change an existing account.
    if credentials["username"] == "qoj-vp-reference":
        credentials["username"] = "qoj-vp-visual"
        private_write(credential_file, json.dumps(credentials, indent=2) + "\n")
    username = credentials["username"]
    if not any(u["username"] == username for u in users_response.json()):
        result = admin.post(BASE + "/api/v4/users", json={
            "username": username, "name": "QOJ VP visual reference", "email": None,
            "ip": None, "password": credentials["password"], "enabled": True,
            "team_id": credentials["teamId"], "roles": ["team"],
        }, timeout=10)
        if result.status_code != 201:
            raise RuntimeError(f"Reference user creation failed: HTTP {result.status_code}; response withheld")

    team = requests.Session()
    team.trust_env = False
    login = team.get(BASE + "/login", timeout=10)
    login.raise_for_status()
    # Login secrets remain only in memory and private raw HTML snapshots.
    token_match = re.search(r'name="_csrf_token"[^>]*value="([^"]+)"', login.text)
    if not token_match:
        raise RuntimeError("Original DOMjudge login CSRF field was not found")
    result = team.post(BASE + "/login", data={"_username": username, "_password": credentials["password"], "_csrf_token": token_match.group(1)}, timeout=10)
    result.raise_for_status()
    if "/login" in result.url:
        raise RuntimeError("Reference team login did not reach a team page")

    pages = {}
    for name, path in {"home": "/team/", "problemset": "/team/problems", "submit": "/team/submit"}.items():
        response = team.get(BASE + path, timeout=10)
        structure = Page(response.text)
        private_write(PRIVATE / f"{name}.raw.html", redact_html(response.text))
        pages[name] = {"url": response.url, "status": response.status_code, "bytes": len(response.content), "htmlSha256": hashlib.sha256(response.content).hexdigest(), "forms": structure.forms, "inputs": structure.inputs, "teamLinks": structure.links}

    assets = []
    for upstream, local in [
        ("public/style_domjudge.css", "extension/assets/domjudge/style_domjudge.css"),
        ("vendor/twbs/bootstrap/dist/css/bootstrap.min.css", "extension/assets/bootstrap/bootstrap.min.css"),
        ("vendor/twbs/bootstrap/dist/js/bootstrap.bundle.min.js", "extension/assets/bootstrap/bootstrap.bundle.min.js"),
        ("vendor/fortawesome/font-awesome/css/all.min.css", "extension/assets/fontawesome/css/all.min.css"),
    ]:
        contents = docker_bytes("exec", CONTAINER, "cat", "/opt/domjudge/domserver/webapp/" + upstream)
        original = (ROOT / local).read_bytes()
        assets.append({"imagePath": upstream, "localPath": local, "sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents), "matchesLocal": contents == original})
    image = json.loads(docker_bytes("image", "inspect", "domjudge/domserver:9.0.1"))[0]
    fonts = []
    for name in ("fa-solid-900.woff2", "fa-regular-400.woff2", "fa-brands-400.woff2"):
        contents = docker_bytes("exec", CONTAINER, "cat", "/opt/domjudge/domserver/webapp/vendor/fortawesome/font-awesome/webfonts/" + name)
        original = (ROOT / "extension/assets/fontawesome/webfonts" / name).read_bytes()
        fonts.append({"file": name, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest(), "matchesLocal": contents == original})
    report = {"baseUrl": BASE, "api": info, "image": "domjudge/domserver:9.0.1", "imageId": image["Id"], "repoDigests": image["RepoDigests"], "teamLogin": True, "teamCredentialFile": str(credential_file.relative_to(ROOT)), "pages": pages, "assets": assets, "fontAssets": fonts, "notes": ["Actual official PHP/Twig rendering; no mock HTML.", "No judgehost is running; submitted programs cannot execute.", "All exported HTML token values use a fixed redacted placeholder."]}
    (EVIDENCE / "service.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"baseUrl": BASE, "version": info["domjudge"]["version"], "teamLogin": True, "pages": {k: {"status": v["status"], "url": v["url"]} for k, v in pages.items()}, "assetMatches": [a["matchesLocal"] for a in assets], "evidence": str((EVIDENCE / "service.json").relative_to(ROOT))}))


if __name__ == "__main__":
    main()
