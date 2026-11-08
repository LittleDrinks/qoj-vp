"""Exercise the command-line entry points shipped in the Debian package."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.build.package_hydro import package_hydro

ROOT = Path(__file__).resolve().parents[2]


class SubmitPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='qoj-submit-package-')
        cls.addClassCleanup(cls.work.cleanup)
        cls.directory = Path(cls.work.name)
        package = package_hydro(ROOT, cls.directory / 'packages', development=True)
        cls.installed = cls.directory / 'installed'
        subprocess.run(['dpkg-deb', '-x', str(package), str(cls.installed)], check=True)

    def command(self, name, *arguments):
        path = self.installed / ('usr/lib/qoj-vp/bin/submit' if name == 'submit' else 'usr/bin/' + name)
        return subprocess.run([sys.executable, '-I', str(path), *arguments],
                              capture_output=True, text=True, timeout=20,
                              env={**os.environ, 'XDG_DATA_HOME': str(self.directory / self.id())})

    def test_installed_commands_expose_login_binding_and_submission(self):
        result = self.command('qoj', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('login', result.stdout)
        self.assertIn('contest', result.stdout)
        for name in ('qoj-submit', 'submit'):
            with self.subTest(command=name):
                result = self.command(name, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--dry-run', result.stdout)
                self.assertIn('--problem', result.stdout)

    def fixture_command(self, name, *arguments, outcome='detail-redirect', answer=''):
        path = self.installed / ('usr/lib/qoj-vp/bin/submit' if name == 'submit' else 'usr/bin/' + name)
        report = self.directory / 'http.json'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'tests/submit_http_fixture.py'),
                                 str(path), str(report), outcome, *arguments],
                                input=answer, capture_output=True, text=True, timeout=20,
                                env={**os.environ, 'XDG_DATA_HOME': str(self.directory / self.id())})
        return result, json.loads(report.read_text())

    def test_submit_infers_problem_and_language_and_confirms_list_receipt(self):
        result, _ = self.fixture_command('qoj', 'contest', '3387')
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.directory / 'A.cpp'
        source.write_text('int main() { return 0; }\n')
        result, traffic = self.fixture_command('submit', str(source), outcome='list-redirect', answer='y\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Submit? [y/N]', result.stdout)
        self.assertIn('Submission received: https://qoj.ac/submission/1000005', result.stdout)
        self.assertEqual(traffic['uploads'], [{'path': '/contest/3387/problem/15419/statement/zh_cn',
                                             'filename': 'A.cpp', 'source': source.read_text(), 'language': 'C++20'}])

    def test_explicit_options_and_spaced_filename_reach_the_qoj_request(self):
        source = self.directory / 'my solution.txt'
        source.write_text('print(3)\n')
        result, traffic = self.fixture_command('submit', '-c', '3387', '-p', 'B', '-l', 'py', '-y', str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Submit? [y/N]', result.stdout)
        self.assertEqual(traffic['uploads'], [{'path': '/contest/3387/problem/15420/statement/zh_cn',
                                             'filename': 'my solution.txt', 'source': 'print(3)\n', 'language': 'Python3'}])

    def test_dry_run_and_declining_confirmation_send_no_submission(self):
        source = self.directory / 'A.cpp'
        source.write_text('int main() {}\n')
        for flags, answer, message in [(('--dry-run',), '', 'Dry run:'), ((), 'n\n', 'Cancelled.')]:
            with self.subTest(flags=flags):
                result, traffic = self.fixture_command('submit', '-c', '3387', *flags, str(source), answer=answer)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(message, result.stdout)
                self.assertEqual(traffic['uploads'], [])

    def test_failed_and_uncertain_submissions_preserve_exit_status_and_send_once(self):
        source = self.directory / 'A.cpp'
        source.write_text('int main() {}\n')
        for outcome, status in [('rejected', 1), ('connection-error', 2)]:
            with self.subTest(outcome=outcome):
                result, traffic = self.fixture_command('submit', '-c', '3387', '-y', str(source), outcome=outcome)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn('Error:', result.stderr)
                self.assertEqual(len(traffic['uploads']), 1)
