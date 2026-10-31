#!/usr/bin/env python3
"""Mirror resources referenced by the actual DOMjudge HTML for offline replay."""
from __future__ import annotations

from collections import deque
import hashlib
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
import tarfile
from urllib.parse import unquote, urljoin, urlsplit

import requests

from reference import BASE, CONTAINER, HERE, docker_bytes

RENDERED = HERE / "rendered"
OUTPUT = RENDERED / "site-assets"


class Resources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attributes) -> None:
        attrs = dict(attributes)
        if tag in ("script", "img") and attrs.get("src"):
            self.paths.add(attrs["src"])
        if tag == "link" and attrs.get("rel") in ("stylesheet", "icon", "shortcut icon") and attrs.get("href"):
            self.paths.add(attrs["href"])


def main() -> None:
    found = Resources()
    for name in ("home", "problemset", "submit-page", "submit-modal-generic", "submit-modal-a"):
        found.feed((RENDERED / (name + ".html")).read_text())
    queue = deque(sorted(found.paths))
    records = {}
    session = requests.Session()
    session.trust_env = False
    origin = urlsplit(BASE)
    while queue:
        url = urljoin(BASE + "/", queue.popleft())
        parts = urlsplit(url)
        if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc):
            raise RuntimeError("Unexpected external reference asset; mirror is restricted to the actual local DOMjudge service")
        path = unquote(parts.path)
        if path in records:
            continue
        relative = Path(path.lstrip("/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Unexpected reference asset path")
        response = session.get(url, timeout=15)
        response.raise_for_status()
        content = response.content
        destination = OUTPUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        dynamic = path == "/public/scoreboard-category-color.css"
        image_path = None if dynamic else "/opt/domjudge/domserver/webapp/public" + path
        if image_path:
            original = docker_bytes("exec", CONTAINER, "cat", image_path)
            if content != original:
                raise RuntimeError("A static HTTP resource differs from the running image file")
        record = {
            "requestPath": parts.path + (("?" + parts.query) if parts.query else ""),
            "mirrorPath": "site-assets/" + relative.as_posix(),
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "contentType": response.headers.get("Content-Type", mimetypes.guess_type(path)[0]),
            "sourceKind": "Actual DOMjudge dynamic CSS GET" if dynamic else "Actual DOMjudge HTTP GET, byte-verified against running official image file",
            "imagePath": image_path,
        }
        records[path] = record
        if path.endswith(".css"):
            for match in re.finditer(r'url\(\s*[\"\']?([^\"\')]+)[\"\']?\s*\)', content.decode()):
                reference = match[1].strip()
                if reference.startswith(("data:", "#")):
                    continue
                queue.append(urljoin(url, reference))
    manifest = {
        "providerVersion": "9.0.1", "sourceBaseUrl": BASE,
        "replayKind": "Original service response snapshots and original complete assets; replay is not a running DOMjudge backend.",
        "credentialsOrRequestHeadersSaved": False,
        "resources": {path: records[path] for path in sorted(records)},
    }
    (RENDERED / "site-assets-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = RENDERED / "site-assets.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(OUTPUT, arcname="site-assets")
        tar.add(RENDERED / "site-assets-manifest.json", arcname="site-assets-manifest.json")
    rendered_manifest_path = RENDERED / "manifest.json"
    rendered_manifest = json.loads(rendered_manifest_path.read_text())
    rendered_manifest["offlineResources"] = {"manifest": "site-assets-manifest.json", "directory": "site-assets", "archive": "site-assets.tar.gz", "resourceCount": len(records), "replayKind": manifest["replayKind"]}
    rendered_manifest_path.write_text(json.dumps(rendered_manifest, indent=2) + "\n")
    print(json.dumps({"providerVersion": "9.0.1", "resourceCount": len(records), "totalBytes": sum(r["bytes"] for r in records.values()), "paths": sorted(records), "archiveBytes": archive.stat().st_size}))


if __name__ == "__main__":
    main()
