"""Open the native QOJ start page and inject the isolated readiness UI prototype."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
contest = sys.argv[1] if len(sys.argv) > 1 else "4686"
if not contest.isdigit():
    raise SystemExit("Usage: npm run preview:ready -- <contest ID>")
subprocess.run(["opencli", "browser", "ready-ui", "open",
                f"https://qoj.ac/contest/{contest}/virtual/register", "--window", "foreground"], check=True)
subprocess.run(["opencli", "browser", "ready-ui", "wait", "selector", "#form-register_vp"], check=True)
source = (root / "src/firefox/qoj-ready-prototype.js").read_text()
subprocess.run(["opencli", "browser", "ready-ui", "eval", source], check=True)
