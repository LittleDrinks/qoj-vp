import json
from pathlib import Path
import tempfile
import unittest
from qojvp.desktop import HOST, DESCRIPTION, configure, migrate_registration


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.config'
        self.state = self.home / 'custom-state'
        self.state.mkdir()
        (self.state / 'record').write_bytes(b'existing contest')
        self.manifest = self.home / '.mozilla/native-messaging-hosts' / (HOST + '.json')
        self.manifest.parent.mkdir(parents=True)
        self.original = json.dumps({'name': HOST, 'description': DESCRIPTION,
                                    'path': str(self.state / 'native-launcher.sh')}).encode()
        self.manifest.write_bytes(self.original)

    def test_upgrade_preserves_custom_directory_and_is_repeatable(self):
        migration, _ = configure(self.home, self.config, lambda: {'version': 'test'})
        self.assertEqual(Path(migration['backup']).read_bytes(), self.original)
        self.assertFalse(self.manifest.exists())
        settings = self.config / 'qoj-vp/runtime.json'
        self.assertEqual(json.loads(settings.read_text())['stateDir'], str(self.state))
        self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
        self.assertFalse(migrate_registration(self.home, self.config)['migrated'])
        self.assertEqual((self.state / 'record').read_bytes(), b'existing contest')

    def test_broken_new_host_restores_old_connection(self):
        def fail():
            raise RuntimeError('Cannot start')
        with self.assertRaises(RuntimeError):
            configure(self.home, self.config, fail)
        self.assertEqual(self.manifest.read_bytes(), self.original)
        self.assertEqual((self.state / 'record').read_bytes(), b'existing contest')

    def test_failed_check_does_not_overwrite_concurrent_installer(self):
        def fail():
            self.manifest.write_text('new registration')
            raise RuntimeError('Cannot start')
        with self.assertRaises(RuntimeError):
            configure(self.home, self.config, fail)
        self.assertEqual(self.manifest.read_text(), 'new registration')
        self.assertEqual(len(list(self.manifest.parent.glob('*.before-deb-*'))), 1)

    def test_foreign_registration_is_untouched(self):
        self.manifest.write_text('{}')
        with self.assertRaises(ValueError):
            migrate_registration(self.home, self.config)
        self.assertEqual(self.manifest.read_text(), '{}')
        self.assertFalse(self.config.exists())

    def test_conflicting_state_is_untouched(self):
        settings = self.config / 'qoj-vp/runtime.json'
        settings.parent.mkdir(parents=True)
        settings.write_text('{"stateDir":"/another/state"}')
        with self.assertRaises(ValueError):
            migrate_registration(self.home, self.config)
        self.assertEqual(self.manifest.read_bytes(), self.original)
        self.assertEqual(settings.read_text(), '{"stateDir":"/another/state"}')
