#!/usr/bin/env python3
"""Bounded, isolated VMware Firefox preflight; never submits an OJ solution.

Run this file from its unpacked project directory. All browser/native state is
under this project's state directory. The two loopback servers exist only for
this harness invocation and are stopped before it exits.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shlex
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Keep dependencies and the unmodified upstream library inside the test bundle.
sys.path.insert(0, str(ROOT / "vendor" / "qoj-submitter"))
sys.path.insert(0, str(ROOT / "vendor_py"))

HOST_NAME = "org.littledrinks.qoj_preflight"
OWNER = "QOJ VP isolated preflight owned native host v1"
TWO_HOURS_MS = 2 * 60 * 60 * 1000


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def process_exit(pid, timeout=12):
    """Observe /proc disappearance; a closed native port alone is insufficient."""
    require(isinstance(pid, int) and pid > 0, "No valid process ID was returned")
    started = time.monotonic()
    proc = Path("/proc") / str(pid)
    initial = proc.exists()
    while proc.exists() and time.monotonic() - started < timeout:
        time.sleep(0.1)
    evidence = {"pid": pid, "presentWhenChecked": initial,
                "procEntryAbsent": not proc.exists(),
                "waitSeconds": round(time.monotonic() - started, 3)}
    require(evidence["procEntryAbsent"], f"Process {pid} still has a /proc entry after {timeout}s")
    return evidence


class StaticFixtureServer:
    """Separate RankLand origin, rooted only at the checked-in fixture files."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.server = None
        self.thread = None
        self.requests = []
        self.lock = threading.Lock()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        require(self.directory.is_dir(), "RankLand fixture directory is missing")
        owner = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def log_request(self, code="-", size="-"):
                # Never record request headers or bodies.
                with owner.lock:
                    owner.requests.append({"method": self.command,
                                           "path": self.path.split("?", 1)[0], "status": code})

            def do_POST(self):
                self.send_error(405, "Read-only preflight fixture")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(self.directory)))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="rankland-preflight-http", daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)
