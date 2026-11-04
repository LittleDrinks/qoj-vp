#!/usr/bin/env python3
"""Run isolated Firefox regressions, optionally checking the live RankLand page."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'results/ci'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rankland-online', action='store_true',
                        help='Also run the network-dependent original RankLand regression')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2,
                        help='Concurrent isolated Firefox suites (default: 2)')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / 'tests/browser/vendor_py'))
    report = {'schema': 'qoj-vp-hydro-ci-v1', 'status': 'running', 'startedAt': time.time(),
              'judge': 'local-fixtures', 'realQojSubmission': False, 'realRanklandTested': False,
              'ranklandOnlineRequested': args.rankland_online,
              'python': platform.python_version(), 'kernel': platform.release(), 'checks': []}
    target = OUTPUT / 'hydro-summary.json'

    def save():
        target.write_text(json.dumps(report, indent=2) + '\n')

    save()
    try:
        if os.getuid() == 0:
            raise RuntimeError('Run browser tests as the dedicated unprivileged CI user')
        if not Path('/usr/bin/firefox-esr').is_file():
            raise RuntimeError('The guest harnesses require /usr/bin/firefox-esr')
        driver = ROOT / 'tests/browser/tools/geckodriver'
        if not driver.is_file() or not os.access(driver, os.X_OK):
            raise RuntimeError('Install the pinned geckodriver before running browser tests')
        for module in ('selenium', 'requests', 'bs4', 'pycurl'):
            if importlib.util.find_spec(module) is None:
                raise RuntimeError('Missing browser-test dependency: ' + module)
        report['os'] = platform.freedesktop_os_release()
        report['firefox'] = subprocess.check_output(['/usr/bin/firefox-esr', '--version'], text=True).strip()
        report['geckodriver'] = subprocess.check_output([str(driver), '--version'], text=True).splitlines()[0]
        cases = [
            ('visual-parity', ['tests/browser/guest_visual_parity.py', '--reference-snapshot',
                               'tests/browser/visual-reference/rendered', '--width', '1440', '--height', '880']),
            ('rankland-export', ['tests/browser/guest_rankland_sync.py']),
            ('administration', ['tests/browser/guest_admin_flow.py']),
            ('resources', ['tests/browser/guest_resource_cache.py']),
            ('home-refresh', ['tests/browser/guest_home_parity.py', '--reference-snapshot',
                              'tests/browser/visual-reference/rendered']),
            ('local-board', ['tests/browser/guest_local_board.py']),
            ('receipts', ['tests/browser/guest_transport_diagnostics.py']),
        ]
        if args.rankland_online:
            cases.append(('rankland-online', ['tests/browser/guest_rankland_readiness.py', '--mode', 'verify']))
        def run_case(case):
            name, arguments = case
            started = time.time()
            with (OUTPUT / (name + '.txt')).open('w') as log:
                result = subprocess.run([sys.executable, *arguments], cwd=ROOT, stdout=log,
                                        stderr=subprocess.STDOUT, check=False)
            return {'name': name, 'status': 'passed' if result.returncode == 0 else 'failed',
                    'exitCode': result.returncode, 'seconds': round(time.time() - started, 2)}

        # Separate processes, profiles, fixture ports and native-host identities.
        # Only the coordinator writes the combined report.
        report['workers'] = args.workers
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_case, case) for case in cases]
            for future in as_completed(futures):
                check = future.result()
                if check['name'] == 'rankland-online':
                    report['realRanklandTested'] = True
                report['checks'].append(check)
                print(check['name'] + ': ' + check['status'], flush=True)
                save()
        report['status'] = 'passed' if all(check['status'] == 'passed' for check in report['checks']) else 'failed'
    except Exception as error:
        report.update(status='failed', errorType=type(error).__name__, error=str(error))
    finally:
        report['finishedAt'] = time.time()
        save()
    print(json.dumps({'status': report['status'], 'summary': str(target)}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
