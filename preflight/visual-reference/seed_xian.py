#!/usr/bin/env python3
"""Seed display-only Xi'an fixtures through the original DOMjudge REST API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import zipfile

import requests

from reference import BASE, CONTAINER, EVIDENCE, docker_bytes

CONTEST = "qoj-vp-xian-reference"
NAMES = ["Bridge", "Cells Coloring", "Clone Ranran", "Contests", "Find Maximum", "Hotel", "Perfect Word", "Power of Two", "Square Grid", "Strange Sum", "Streets", "Tree"]


def fixture_pdf(label: str, title: str) -> bytes:
    text = f"{label} - {title}: visual reference fixture, not the contest statement."
    content = f"BT /F1 12 Tf 40 760 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{n:010} 00000 n \n".encode() for n in offsets[1:])
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF\n".encode()
    return pdf


def main() -> None:
    secret = docker_bytes("exec", CONTAINER, "cat", "/opt/domjudge/domserver/etc/initial_admin_password.secret").decode().strip()
    api = requests.Session()
    api.auth = ("admin", secret)
    api.trust_env = False
    contests = api.get(BASE + "/api/v4/contests?onlyActive=false", timeout=10)
    contests.raise_for_status()
    if not any(c["id"] == CONTEST for c in contests.json()):
        now = datetime.now(timezone.utc)
        data = {"id": CONTEST, "name": "The 2022 ICPC Asia Xi'an Regional Contest", "start_time": (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S%z"), "duration": "5:00:00", "activation_time": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S%z"), "public": True, "penalty_time": 20}
        response = api.post(BASE + "/api/v4/contests", files={"json": ("contest.json", json.dumps(data), "application/json")}, timeout=20)
        if not response.ok:
            raise RuntimeError(f"Reference contest API returned HTTP {response.status_code}; raw response withheld")
    existing = api.get(BASE + f"/api/v4/contests/{CONTEST}/problems", timeout=10)
    existing.raise_for_status()
    known = {p["id"] for p in existing.json()}
    for index, title in enumerate(NAMES):
        label = chr(65 + index)
        problem_id = "xian-" + label.lower()
        if problem_id in known:
            continue
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            ini = f'name = "{title}"\nshort-name = "{label}"\nexternalid = "{problem_id}"\ntimelimit = 2\nallow_submit = 1\nallow_judge = 0\n'
            archive.writestr("domjudge-problem.ini", ini)
            archive.writestr("problem.yaml", "name: " + title + "\nvalidation: default\n")
            archive.writestr("problem_statement/problem.pdf", fixture_pdf(label, title))
            archive.writestr("data/sample/reference.in", "0\n")
            archive.writestr("data/sample/reference.ans", "0\n")
        response = api.post(BASE + f"/api/v4/contests/{CONTEST}/problems", files={"zip": (problem_id + ".zip", buf.getvalue(), "application/zip")}, timeout=20)
        if not response.ok:
            raise RuntimeError(f"Reference problem {label} API returned HTTP {response.status_code}; raw response withheld")
    response = api.get(BASE + f"/api/v4/contests/{CONTEST}/problems", timeout=10)
    response.raise_for_status()
    problems = response.json()
    assert len(problems) == 12
    evidence = {"contestId": CONTEST, "problemCount": len(problems), "namesSource": "https://cdn.algoux.cn/rankland/file/94031158458802176/icpc2022xi_an.srk.json", "problems": problems, "fixtureOnly": True, "statementAndSamples": "Explicitly marked display fixtures; these are not real Xi'an statements or samples.", "judgehost": False}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "xian-seed.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"contestId": CONTEST, "problemCount": len(problems), "apiStatus": response.status_code, "fixtureOnly": True}))


if __name__ == "__main__":
    main()
