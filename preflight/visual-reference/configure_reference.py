#!/usr/bin/env python3
"""Set the official single-source-file option and record actual fixture metadata."""
from __future__ import annotations

import json
import re
import subprocess

import requests

from reference import BASE, CONTAINER, HERE, docker_bytes
from seed_xian import CONTEST


def console_sql(sql: str) -> str:
    result = subprocess.run(["docker", "exec", CONTAINER, "php", "/opt/domjudge/domserver/webapp/bin/console", "dbal:run-sql", sql, "--env=prod", "--no-ansi"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Reference-only configuration console operation failed; raw output withheld")
    return result.stdout


def json_rows(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        start, end = line.find("{"), line.rfind("}")
        if start >= 0 and end > start:
            rows.append(json.loads(line[start:end + 1]))
    return rows


def main() -> None:
    console_sql("INSERT INTO configuration (name,value) VALUES ('sourcefiles_limit','1'),('show_public_stats','false'),('show_limits_on_team_page','false') ON DUPLICATE KEY UPDATE value=VALUES(value)")
    # QOJ exposes no problem color. Keep the original DOMjudge null-color
    # fallback instead of inventing a palette in the display fixture.
    console_sql("UPDATE contestproblem cp JOIN contest c ON c.cid=cp.cid SET cp.color=NULL WHERE c.externalid='qoj-vp-xian-reference'")
    sql = "SELECT JSON_OBJECT('probid',p.probid,'externalId',p.externalid,'label',cp.shortname,'title',p.name,'timeLimitSeconds',p.timelimit,'memoryLimitKiB',p.memlimit,'outputLimitKiB',p.outputlimit,'statementType',p.problemstatement_type,'typesFlag',p.types,'multipassLimit',p.multipass_limit,'allowSubmit',cp.allow_submit,'allowJudge',cp.allow_judge,'points',cp.points,'color',cp.color,'specialRun',p.special_run,'specialCompare',p.special_compare) AS metadata FROM problem p JOIN contestproblem cp ON cp.probid=p.probid JOIN contest c ON c.cid=cp.cid WHERE c.externalid='qoj-vp-xian-reference' ORDER BY cp.shortname"
    problems = json_rows(console_sql(sql))
    assert len(problems) == 12
    selected = json_rows(console_sql("SELECT JSON_OBJECT('name',name,'value',value) AS metadata FROM configuration WHERE name IN ('memory_limit','output_limit','sourcefiles_limit','show_public_stats','show_limits_on_team_page')"))
    database_values = {row["name"]: json.loads(row["value"]) for row in selected}
    specification = docker_bytes("exec", CONTAINER, "cat", "/opt/domjudge/domserver/etc/db-config.yaml").decode()
    effective = {}
    for name in ("memory_limit", "output_limit", "sourcefiles_limit"):
        default = re.search(r"name: " + name + r"\s+type: int\s+default_value: (\d+)", specification)
        assert default
        effective[name] = database_values.get(name, int(default[1]))
    assert effective["sourcefiles_limit"] == 1
    effective["show_public_stats"] = database_values["show_public_stats"]
    effective["show_limits_on_team_page"] = database_values["show_limits_on_team_page"]
    assert effective["show_public_stats"] is False
    assert effective["show_limits_on_team_page"] is False

    session = requests.Session()
    session.trust_env = False
    response = session.get(BASE + f"/api/v4/contests/{CONTEST}", timeout=10)
    response.raise_for_status()
    contest = response.json()
    for problem in problems:
        problem["effectiveMemoryLimitKiB"] = problem["memoryLimitKiB"] or effective["memory_limit"]
        problem["effectiveOutputLimitKiB"] = problem["outputLimitKiB"] or effective["output_limit"]
        problem["typeName"] = "pass-fail" if problem["typesFlag"] == 1 else "other"
        problem["samples"] = "one display-only sample pair: reference.in/reference.ans"
    metadata = {
        "providerVersion": "9.0.1", "contest": contest,
        "configuration": effective,
        "configurationMethod": "Original Symfony console dbal:run-sql writes configuration row; original PHP/Twig code is unchanged.",
        "team": {"id": "exteam", "internalId": 2, "name": "Example teamname"},
        "problems": problems,
        "styles": {
            "successButtonBase": "style_domjudge.css .btn-success background #0a8927",
            "navbarSubmit": "a.nav-link > span.btn.btn-success.btn-sm > i.fas.fa-cloud-upload-alt",
            "cardSubmit": "a.justify-content-center > span.btn.btn-success > i.fas.fa-cloud-upload-alt",
            "modalSubmit": "button.btn-success.btn > i.fas.fa-cloud-upload-alt",
            "problemCard": "div.card > div.card-body; all colors NULL, original DOMjudge uncolored badge fallback",
            "limitsText": "Hidden by original show_limits_on_team_page=false configuration", "typeText": "Type: pass-fail",
            "problemStatistics": "Hidden by original show_public_stats=false configuration",
            "bootstrap": "5.3.7", "fontAwesome": "Free 6.5.2",
        },
        "comparisonLimits": [
            "NULL problem colors match absent QOJ color metadata; original DOMjudge renders its own uncolored fallback.",
            "The fixture's pass-fail type, hidden 2-second/2-GB limits, statements, samples, team identity and timestamps are display-test data, not real QOJ contest metadata.",
            "The reference has no submissions and no judgehost; histories/histograms differ from an extension session with real submissions.",
            "Full-page pixel equality must first align metadata, visible controls, clock, viewport and button state.",
        ],
    }
    (HERE / "rendered" / "configuration.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"sourcefiles_limit": 1, "show_public_stats": False, "show_limits_on_team_page": False, "problemCount": len(problems), "effectiveMemoryLimitKiB": effective["memory_limit"], "effectiveOutputLimitKiB": effective["output_limit"], "metadata": "preflight/visual-reference/rendered/configuration.json"}))


if __name__ == "__main__":
    main()
