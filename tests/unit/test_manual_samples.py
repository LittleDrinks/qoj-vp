from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

from qojvp import Application, ApplicationError
from qojvp.native_host import MAX_INCOMING, MAX_OUTGOING, read_frame, serve_once
from qojvp.resources import MAX_MANUAL_FILE_BYTES, MAX_MANUAL_BYTES
from tests.unit.support import QojFixture
from tests.unit.test_application import AT, ROOT


def file_list(files):
    return [{'name': name, 'base64': base64.b64encode(data).decode()} for name, data in files.items()]


def zip_payload(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files:
            archive.writestr(name, value)
    return base64.b64encode(stream.getvalue()).decode()


class ManualSampleIntegrationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='manual-samples-')
        self.fixture = QojFixture().__enter__()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: AT)
        self.app.dispatch('qoj_contest', {'contestId': '3387'}, self.fixture.exchange)
        self.session = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser'})
        self.args = {'sessionId': self.session['sessionId'], 'problemId': '15419'}

    def tearDown(self):
        self.app.close()
        self.fixture.__exit__(None, None, None)
        self.directory.cleanup()

    def offline(self, method, args):
        return self.app.dispatch(method, args, lambda _: self.fail('Manual resource operation attempted HTTP'))

    def imported(self, **args):
        return self.offline('import_samples', {**self.args, **args})

    def downloaded(self, descriptor):
        data = bytearray()
        while True:
            chunk = self.offline('resource_chunk', {**self.args, 'resourceId': descriptor['resourceId'], 'offset': len(data)})
            data.extend(base64.b64decode(chunk['bytesBase64']))
            if chunk['eof']:
                break
        self.assertEqual(hashlib.sha256(data).hexdigest(), descriptor['sha256'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_files_import_is_offline_normalized_and_survives_restart(self):
        raw = {'nested/example10.in': b'10\r\n', 'nested/example10.out': b'answer 10\n',
               'nested/example2.in': b'2\n', 'nested/example2.ans': b''}
        imported = self.imported(files=file_list(raw))
        self.assertEqual((imported['sampleSource'], imported['manualSamples']), ('manual', True))
        self.assertEqual(imported['downloads'][0]['sampleSource'], 'manual')
        self.app.close()
        self.app = Application(self.directory.name, clock=lambda: AT + 1000)
        entry = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
        self.assertEqual(self.downloaded(entry['downloads'][0]), {'samples-A/1.in': b'2\n', 'samples-A/1.ans': b'',
            'samples-A/2.in': b'10\r\n', 'samples-A/2.ans': b'answer 10\n'})
        self.assertEqual(self.app.ledger.session(self.session['sessionId'])['state'], 'prepared')
        self.assertEqual(self.fixture.posts, [])

    def test_zip_import_and_explicit_replacement_preserve_original_attachment_descriptor(self):
        original = [('1.in', b'old input\n'), ('1.ans', b'old output\n'), ('tools/interactor.py', b'print("tool")\n')]
        self.fixture.attachment_overrides['15419'] = (200, base64.b64decode(zip_payload(original)), 'application/zip')
        old = self.app.dispatch('prepare_resource', self.args, self.fixture.exchange)
        attachment = next(item for item in old['downloads'] if item['kind'] == 'attachment')
        old_files = self.downloaded(attachment)
        incoming = zip_payload([('a.in', b'new input\n'), ('a.out', b'new output\n')])
        with self.assertRaises(ApplicationError) as caught:
            self.imported(zipBase64=incoming)
        self.assertEqual(caught.exception.code, 'CONFIRMATION_REQUIRED')
        self.assertEqual(self.app.resources.read_entry(self.session, '15419'), old)
        current = self.imported(zipBase64=incoming, confirmedReplace=True)
        self.assertEqual(current['downloads'][1], attachment)
        self.assertEqual(self.downloaded(attachment), old_files)
        self.assertEqual(self.downloaded(current['downloads'][0]),
                         {'samples-A/1.in': b'new input\n', 'samples-A/1.ans': b'new output\n'})
        manifest = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})
        self.assertEqual(manifest['problems'][0]['status'], 'ready')

    def test_preparation_refresh_and_concurrent_provider_store_never_replace_manual_samples(self):
        old = self.app.dispatch('prepare_resource', self.args, self.fixture.exchange)
        payload = self.app.resources.object_path(self.session, '15419', old).read_bytes()
        current = self.imported(files=file_list({'1.in': b'manual\n', '1.ans': b'answer\n'}), confirmedReplace=True)
        self.assertEqual(self.offline('prepare_resource', self.args)['resourceId'], current['resourceId'])
        self.assertEqual(self.offline('prepare_resource', {**self.args, 'refresh': True})['resourceId'], current['resourceId'])
        preserved = self.app.resources.store(self.session, '15419', old, payload, AT + 500)
        self.assertEqual(preserved['downloads'], current['downloads'])
        self.assertTrue(preserved['manualSamples'])

    def test_manual_samples_do_not_overwrite_incomplete_original_attachment_inputs(self):
        self.fixture.attachment_overrides['15419'] = (200, base64.b64decode(zip_payload([
            ('1.in', b'original incomplete input'), ('judge.py', b'print("tool")')])), 'application/zip')
        old = self.app.dispatch('prepare_resource', self.args, self.fixture.exchange)
        self.assertEqual([item['kind'] for item in old['downloads']], ['attachment'])
        original = self.downloaded(old['downloads'][0])
        current = self.imported(files=file_list({'1.in': b'manual input', '1.out': b'manual answer'}))
        self.assertEqual(current['downloads'][1], old['downloads'][0])
        self.assertEqual(self.downloaded(current['downloads'][1]), original)
        self.assertEqual(self.downloaded(current['downloads'][0]),
                         {'samples-A/2.in': b'manual input', 'samples-A/2.ans': b'manual answer'})
        self.assertEqual(self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]['status'], 'ready')

    def test_import_requires_verified_account_contest_and_problem_binding(self):
        files = file_list({'1.in': b'1', '1.ans': b'2'})
        for change in ({'problemId': '999999'}, {'problemId': '15419', 'sessionId': self.app.dispatch('create_session',
                {'contestId': '9999', 'account': 'FixtureUser'})['sessionId']},
                {'sessionId': self.app.dispatch('create_session', {'contestId': '3387', 'account': 'OtherUser'})['sessionId']},
                {'sessionId': self.app.dispatch('create_session', {'contestId': '3387'})['sessionId']}):
            with self.subTest(change=change), self.assertRaises(ApplicationError):
                self.imported(files=files, **change)
        self.assertEqual(self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'], [])

    def test_old_scoped_resource_metadata_can_authorize_an_offline_import(self):
        self.fixture.attachment_overrides['15419'] = (404, b'not found', 'text/plain')
        self.fixture.problem_html['15419'] = '<main>No verified sample block</main>'
        entry = self.app.dispatch('prepare_resource', self.args, self.fixture.exchange)
        self.assertEqual((entry['status'], entry['problemLabel']), ('unknown', 'A'))
        self.app.ledger.db.execute('DELETE FROM contest_snapshots')
        current = self.imported(files=file_list({'1.in': b'1', '1.ans': b'2'}))
        self.assertEqual(current['downloads'][0]['filename'], 'samples-A.zip')

    def test_rejects_ambiguous_or_incomplete_files_without_publishing_partial_cache(self):
        cases = [file_list({'1.in': b'1'}), file_list({'1.ans': b'2'}),
                 file_list({'1.in': b'1', '1.ans': b'2', '1.out': b'3'}),
                 file_list({'1.in': b'1', '1.ans': b'2', 'readme.txt': b'notice'}),
                 [{'name': '1.in', 'base64': '*'}],
                 file_list({'1.in': b'1', '1.ans': b'2'}) + file_list({'1.in': b'1'})]
        for files in cases:
            with self.subTest(files=[row['name'] for row in files]), self.assertRaises(ApplicationError):
                self.imported(files=files)
        with self.assertRaises(ApplicationError):
            self.imported(files=file_list({'1.in': b'1', '1.ans': b'2'}), zipBase64='')
        with self.assertRaises(ApplicationError):
            self.imported()
        self.assertIsNone(self.app.resources.read_entry(self.session, '15419'))

    def test_rejects_zip_unsafe_paths_duplicates_symlinks_and_encryption(self):
        for name in ('../1.in', '/1.in', 'folder/../1.in', 'folder//1.in', 'C:1.in', 'folder\\1.in', 'nul\x00.in'):
            with self.subTest(name=name), self.assertRaises(ApplicationError):
                self.imported(files=[{'name': name, 'base64': 'MQ=='}])
        for name in ('../1.in', '/1.in', 'folder/../1.in', 'folder//1.in', 'C:1.in', 'folder\\1.in'):
            with self.subTest(zip_name=name), self.assertRaises(ApplicationError):
                self.imported(zipBase64=zip_payload([(name, b'1'), ('1.ans', b'2')]))
        symbolic = zipfile.ZipInfo('1.in')
        symbolic.create_system = 3
        symbolic.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ApplicationError):
            self.imported(zipBase64=zip_payload([(symbolic, b'../other'), ('1.ans', b'2')]))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            duplicated = zip_payload([('1.in', b'1'), ('1.in', b'2'), ('1.ans', b'2')])
        with self.assertRaises(ApplicationError):
            self.imported(zipBase64=duplicated)
        encrypted = bytearray(base64.b64decode(zip_payload([('1.in', b'1'), ('1.ans', b'2')])))
        offset = 0
        while (offset := encrypted.find(b'PK\x01\x02', offset)) >= 0:
            encrypted[offset + 8] |= 1
            offset += 4
        with self.assertRaises(ApplicationError):
            self.imported(zipBase64=base64.b64encode(encrypted).decode())
        self.assertIsNone(self.app.resources.read_entry(self.session, '15419'))

    def test_import_limits_apply_to_zip_expansion_file_count_and_file_bytes(self):
        with self.assertRaises(ApplicationError) as caught:
            self.imported(files=file_list({'1.in': b'x' * (MAX_MANUAL_FILE_BYTES + 1), '1.ans': b''}))
        self.assertEqual(caught.exception.code, 'SAMPLES_TOO_LARGE')
        with self.assertRaises(ApplicationError):
            self.imported(zipBase64=zip_payload([('1.in', b'x' * (MAX_MANUAL_FILE_BYTES + 1)), ('1.ans', b'')]))
        with patch('qojvp.resources.MAX_MANUAL_BYTES', 10):
            with self.assertRaises(ApplicationError):
                self.imported(files=file_list({'1.in': b'012345', '1.ans': b'678901'}))
        files = file_list({f'{i}.{kind}': b'' for i in range(501) for kind in ('in', 'ans')})
        with self.assertRaises(ApplicationError):
            self.imported(files=files)
        expanded = [('1.in', b'x' * (MAX_MANUAL_BYTES // 2)), ('1.ans', b'x' * (MAX_MANUAL_BYTES // 2)), ('2.in', b'x'), ('2.ans', b'x')]
        with self.assertRaises(ApplicationError):
            self.imported(zipBase64=zip_payload(expanded))

    def test_cache_metadata_contains_no_upload_payload_and_chunk_response_remains_bounded(self):
        current = self.imported(files=file_list({'1.in': b'private sample input', '1.ans': b'expected'}))
        serialized = json.dumps(current)
        self.assertNotIn('base64', serialized.lower())
        self.assertNotIn('private sample input', serialized)
        self.assertEqual(self.downloaded(current['downloads'][0])['samples-A/1.in'], b'private sample input')
        self.assertEqual(self.fixture.posts, [])

    def test_full_eight_mib_import_crosses_native_frame_and_returns_only_metadata(self):
        files = file_list({'1.in': b'x' * MAX_MANUAL_FILE_BYTES, '1.ans': b'y' * MAX_MANUAL_FILE_BYTES})
        task = {'type': 'task', 'id': 'maximum-manual-import', 'method': 'import_samples',
                'args': {**self.args, 'files': files}}
        encoded = json.dumps(task, separators=(',', ':')).encode()
        self.assertLess(len(encoded), MAX_INCOMING)
        source = io.BytesIO(struct.pack('<I', len(encoded)) + encoded)
        sink = io.BytesIO()
        with patch.dict(os.environ, {'QOJ_VP_STATE_DIR': self.directory.name}):
            self.assertEqual(serve_once(source, sink), 0)
        self.assertLess(len(sink.getvalue()) - 4, MAX_OUTGOING)
        sink.seek(0)
        reply = read_frame(sink)
        self.assertEqual((reply['type'], reply['id'], reply['ok']), ('result', 'maximum-manual-import', True))
        self.assertTrue(reply['result']['manualSamples'])
        self.assertEqual(sum(item['bytes'] for item in reply['result']['files']), MAX_MANUAL_BYTES)
        self.assertNotIn('bytesBase64', reply['result'])
        self.assertIsNone(read_frame(sink), 'Offline import should produce one terminal frame and no HTTP requests')


if __name__ == '__main__':
    unittest.main()
