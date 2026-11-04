from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile
import shutil
import subprocess

from scripts.release.prepare_firefox_release import prepare_release, release_identity, verify_xpi

ROOT = Path(__file__).resolve().parents[2]
COMMIT = 'a' * 40


class FirefoxReleaseTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='firefox-release-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ext = self.root / 'src/firefox'
        self.ext.mkdir(parents=True)
        (self.root / 'src/qojvp').mkdir()
        (self.root / 'src/qojvp/__init__.py').write_text('__version__ = "1.2.3"\n')
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "1.2.3"\n')
        shutil.copytree(ROOT / 'infra/linux', self.root / 'infra/linux')
        shutil.copyfile(ROOT / 'LICENSE', self.root / 'LICENSE')
        (self.root / 'vendor/qoj-submitter/qoj_submitter').mkdir(parents=True)
        (self.root / 'vendor/qoj-submitter/qoj_submitter/client.py').write_text('# fixture')
        (self.ext / 'icons').mkdir()
        (self.ext / 'icons/domjudge-32.png').write_bytes(b'fixture-icon')
        self.manifest = {'version': '1.2.3', 'browser_specific_settings': {'gecko': {'id': 'fixture@example'}}}
        (self.ext / 'manifest.json').write_text(json.dumps(self.manifest))
        (self.ext / 'ui.js').write_text('/* fixture */')
        self.artifacts = self.root / 'dist'
        self.artifacts.mkdir()
        self.output = self.root / 'release'
        self.unsigned = self.artifacts / 'qoj-vp-firefox-1.2.3-unsigned.xpi'
        self.write_xpi(self.unsigned)
        (self.artifacts / 'qoj_vp_workbench-1.2.3-py3-none-any.whl').write_bytes(b'fixture-wheel')
        self.write_source()

    def write_xpi(self, path, *, signatures=False, override=None):
        with zipfile.ZipFile(path, 'w') as archive:
            for file in self.ext.rglob("*"):
                if not file.is_file(): continue
                archive.writestr(str(file.relative_to(self.ext)), (override or {}).get(file.name, file.read_bytes()))
            if signatures:
                # Structural test fixture only, deliberately not a valid signed XPI.
                for name in ('mozilla.rsa', 'mozilla.sf', 'manifest.mf'):
                    archive.writestr('META-INF/' + name, b'test-signature-placeholder')

    def write_source(self, commit=COMMIT):
        with tarfile.open(self.artifacts / 'qoj-vp-mvp-source.tar.gz', 'w:gz') as archive:
            for name, content in [('SOURCE_COMMIT', commit.encode()),
                                  ('src/firefox/manifest.json', json.dumps(self.manifest).encode())]:
                entry = tarfile.TarInfo('qoj-vp/' + name)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))

    def prepare(self, **kwargs):
        return prepare_release(self.root, self.artifacts, self.output, COMMIT, **kwargs)

    def test_source_archive_timestamps_package_reproducibly(self):
        import contextlib
        import os
        from unittest.mock import patch
        from scripts.build import package_extension

        with patch.object(package_extension, 'ROOT', self.root):
            with self.assertRaisesRegex(SystemExit, 'Build the Board first'):
                package_extension.main()
            generated = self.ext / 'board/generated'
            generated.mkdir(parents=True)
            for name in ('engine.js', 'view.js', 'view.css', 'upstream.json',
                         'standard-ranklist-utils.LICENSE', 'standard-ranklist-renderer-component.LICENSE'):
                (generated / name).write_text('fixture')
            payloads = []
            for timestamp in (0, 1800000000):
                for path in self.ext.rglob('*'):
                    if path.is_file(): os.utime(path, (timestamp, timestamp))
                with contextlib.redirect_stdout(io.StringIO()):
                    package_extension.main()
                payloads.append(self.unsigned.read_bytes())
            self.assertEqual(payloads[0], payloads[1])
            verify_xpi(self.unsigned, self.ext, signed=False)

    def test_development_release_is_explicitly_unsigned_and_downloads_are_hashed(self):
        result = self.prepare()
        self.assertFalse(result['mozillaSigned'])
        self.assertTrue(result['xpi'].endswith('-unsigned.xpi'))
        self.assertIn('未签名开发包', (self.output / 'RELEASE_NOTES.md').read_text())
        lines = (self.output / 'SHA256SUMS').read_text().splitlines()
        self.assertEqual({line.split('  ')[1] for line in lines},
                         {result['xpi'], 'qoj-vp_1.2.3~dev_amd64.deb'})
        self.assertFalse((self.output / 'INSTALL.md').exists())
        self.assertNotIn('INSTALL.md', (self.output / 'RELEASE_NOTES.md').read_text())
        for line in lines:
            digest, name = line.split('  ')
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)

    def test_wrong_tag_or_helper_version_prevents_publication(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.prepare(tag='v9.9.9')
        (self.root / 'src/qojvp/__init__.py').write_text('__version__ = "1.2.2"\n')
        with self.assertRaisesRegex(ValueError, 'must agree'):
            release_identity(self.root)
        self.assertFalse(self.output.exists())

    def test_signature_presence_does_not_allow_changed_payload(self):
        signed = self.artifacts / 'from-amo.xpi'
        self.write_xpi(signed, signatures=True, override={'ui.js': b'changed script'})
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            self.prepare(signed_xpi=signed)
        self.assertFalse(self.output.exists())

    def test_unsigned_zip_cannot_be_mislabeled_as_signed(self):
        with self.assertRaisesRegex(ValueError, 'no Firefox signature'):
            self.prepare(signed_xpi=self.unsigned)

    def test_original_payload_with_signature_entries_is_normalized(self):
        signed = self.artifacts / 'from-amo.xpi'
        self.write_xpi(signed, signatures=True)
        result = self.prepare(tag='v1.2.3', signed_xpi=signed)
        self.assertTrue(result['mozillaSigned'])
        self.assertEqual((self.output / result['xpi']).read_bytes(), signed.read_bytes())
        self.assertFalse((self.output / self.unsigned.name).exists())
        extracted=self.root/'deb-content'
        subprocess.run(['dpkg-deb','-x',str(self.output/'qoj-vp_1.2.3_amd64.deb'),str(extracted)],check=True)
        self.assertEqual((extracted/'usr/lib/qoj-vp/firefox.xpi').read_bytes(), signed.read_bytes())
        self.assertEqual((extracted/'usr/share/doc/qoj-vp/source.tar.gz').read_bytes(),
                         (self.artifacts/'qoj-vp-mvp-source.tar.gz').read_bytes())

    def test_signed_manifest_can_be_reformatted_without_changing_the_download(self):
        signed = self.artifacts / 'from-amo.xpi'
        self.write_xpi(signed, signatures=True,
                       override={'manifest.json': json.dumps(self.manifest, indent=2).encode()})
        result = self.prepare(signed_xpi=signed)
        self.assertEqual((self.output / result['xpi']).read_bytes(), signed.read_bytes())

    def test_unsigned_manifest_still_requires_exact_build_bytes(self):
        self.write_xpi(self.unsigned,
                       override={'manifest.json': json.dumps(self.manifest, indent=2).encode()})
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            verify_xpi(self.unsigned, self.ext, signed=False)

    def test_signed_manifest_changes_are_rejected(self):
        signed = self.artifacts / 'from-amo.xpi'
        for changes in ({'version': '1.2.4'}, {'permissions': ['cookies']},
                        {'browser_specific_settings': {'gecko': {'id': 'other@example'}}}):
            with self.subTest(changes=changes):
                altered = {**self.manifest, **changes}
                self.write_xpi(signed, signatures=True,
                               override={'manifest.json': json.dumps(altered, indent=2).encode()})
                with self.assertRaisesRegex(ValueError, 'payload differs'):
                    verify_xpi(signed, self.ext, signed=True)

    def test_signed_manifest_duplicate_fields_are_rejected(self):
        signed = self.artifacts / 'from-amo.xpi'
        repeated = '{"version":"9.9.9",' + json.dumps(self.manifest)[1:]
        self.write_xpi(signed, signatures=True, override={'manifest.json': repeated.encode()})
        with self.assertRaises(ValueError):
            verify_xpi(signed, self.ext, signed=True)

    def test_wrong_source_commit_cannot_ship_with_extension(self):
        self.write_source('b' * 40)
        with self.assertRaisesRegex(ValueError, 'Source archive'):
            self.prepare()

    def test_existing_release_directory_is_not_overwritten(self):
        self.prepare()
        before = (self.output / 'SHA256SUMS').read_bytes()
        with self.assertRaisesRegex(ValueError, 'must be empty'):
            self.prepare()
        self.assertEqual(before, (self.output / 'SHA256SUMS').read_bytes())

    def test_duplicate_paths_are_rejected_even_if_last_entry_matches(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.unsigned, 'a') as archive:
                archive.writestr('ui.js', (self.ext / 'ui.js').read_bytes())
        with self.assertRaisesRegex(ValueError, 'duplicate paths'):
            verify_xpi(self.unsigned, self.ext, signed=False)


if __name__ == '__main__':
    unittest.main()
