"""Verify install, CLI submission and removal in a disposable Hydro guest."""
import json
import os
from pathlib import Path
import re
import shlex
import site
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build.package_hydro import package_hydro


def run(*command, env=None):
    print('$ ' + shlex.join(str(part) for part in command), flush=True)
    result = subprocess.run([str(part) for part in command], env=env, capture_output=True, text=True, timeout=60)
    print(result.stdout, end='', flush=True)
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr, flush=True)
    if result.returncode:
        raise RuntimeError(f'Command exited with {result.returncode}')
    return result.stdout


def main():
    state = subprocess.run(['dpkg-query', '-W', '-f=${Status}', 'qoj-vp'], capture_output=True, text=True)
    if state.stdout.strip() == 'install ok installed':
        raise RuntimeError('Use a disposable Hydro guest with qoj-vp uninstalled')
    original = Path('/usr/local/bin/submit')
    original_bytes = original.read_bytes()
    original_mode = original.stat().st_mode
    baseline = run('/bin/bash', '-lc', 'command -v submit').strip()
    assert baseline == str(original), baseline
    with tempfile.TemporaryDirectory(prefix='qoj-submit-installed-') as directory:
        work = Path(directory)
        package = package_hydro(ROOT, work / 'packages', development=True)
        upgrade_tree = work / 'upgrade'
        run('dpkg-deb', '-R', package, upgrade_tree)
        control = upgrade_tree / 'DEBIAN/control'
        control.write_text(re.sub(r'(?m)^(Version: \S+)$', r'\1.1', control.read_text()))
        upgrade = work / 'upgraded.deb'
        run('dpkg-deb', '--root-owner-group', '--build', upgrade_tree, upgrade)
        env = {**os.environ, 'XDG_DATA_HOME': str(work / 'data')}
        installed = False
        try:
            installed = True
            run('sudo', '-n', 'dpkg', '-i', package)
            resolved = run('/bin/bash', '-lc', 'command -v submit').strip()
            assert resolved == '/usr/lib/qoj-vp/bin/submit', resolved
            run('/bin/bash', '-lc', 'type -a submit; submit --help')
            repeated = run('/bin/bash', '-lc', '. /etc/profile.d/qoj-vp.sh; . /etc/profile.d/qoj-vp.sh; printf "%s" "$PATH"')
            assert repeated.split(':').count('/usr/lib/qoj-vp/bin') == 1
            report = work / 'http.json'
            saved = work / 'data/qoj-submitter/config.json'
            source = work / 'A.cpp'
            source.write_text('int main() { return 0; }\n')
            # System .pth hooks are honored by the launcher's isolated Python.
            # Install it only in this disposable guest, while the CLI uses its
            # real shebang, login-shell PATH and persisted contest selection.
            hook = Path(site.getsitepackages()[-1]) / 'qoj_vp_submit_fixture.pth'
            assert not hook.exists(), hook
            startup = work / 'qoj_vp_submit_fixture.pth'
            startup.write_text("import os, runpy; runpy.run_path(os.environ['QOJ_SUBMIT_FIXTURE_ROOT'] + '/tests/browser/submit_python_startup.py') if os.environ.get('QOJ_SUBMIT_FIXTURE_ROOT') else None\n")
            run('sudo', '-n', 'install', '-D', '-m', '644', startup, hook)
            try:
                fixture_env = {**env, 'QOJ_SUBMIT_FIXTURE_ROOT': str(ROOT), 'QOJ_SUBMIT_FIXTURE_REPORT': str(report)}
                run('/bin/bash', '-lc', 'python3 -I -c \'import os; assert os.environ.get("QOJ_SUBMIT_FIXTURE_ACTIVE") == "1"\'', env=fixture_env)
                run('/bin/bash', '-lc', 'qoj contest 3387', env=fixture_env)
                saved_bytes = saved.read_bytes()
                result = run('/bin/bash', '-lc', 'cd ' + shlex.quote(str(work)) + ' && printf "y\\n" | submit A.cpp', env=fixture_env)
                assert 'Submission received: https://qoj.ac/submission/1000005' in result
                uploads = json.loads(report.read_text())['uploads']
                assert len(uploads) == 1 and uploads[0]['path'] == '/contest/3387/problem/15419/statement/zh_cn'
                print('PASS: qoj contest 3387 then submit A.cpp uses the saved contest and sends once', flush=True)
            finally:
                run('sudo', '-n', 'rm', '--', hook)
            cookies = saved.with_name('qoj.ac.cookies')
            cookies.write_text('# Netscape HTTP Cookie File\nqoj.ac\tFALSE\t/\tTRUE\t2147483647\tfixture_session\tfixture-only\n')
            cookie_bytes = cookies.read_bytes()
            run('sudo', '-n', 'dpkg', '-i', package)
            run('sudo', '-n', 'dpkg', '-i', upgrade)
            assert saved.read_bytes() == saved_bytes
            assert cookies.read_bytes() == cookie_bytes
            assert run('/bin/bash', '-lc', 'command -v submit').strip() == resolved
            assert original.read_bytes() == original_bytes
            assert original.stat().st_mode == original_mode
            print('PASS: installed command, fixture receipt, repeated setup and upgrade preservation', flush=True)
        finally:
            if installed:
                run('sudo', '-n', 'dpkg', '--remove', 'qoj-vp')
        assert run('/bin/bash', '-lc', 'command -v submit').strip() == baseline
        assert original.read_bytes() == original_bytes
        assert original.stat().st_mode == original_mode
        assert saved.read_bytes() == saved_bytes
        assert cookies.read_bytes() == cookie_bytes
        print('PASS: removal restores DOMjudge and preserves QOJ configuration', flush=True)


if __name__ == '__main__':
    main()
