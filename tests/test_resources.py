from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
import zipfile

from qojvp import Application, ApplicationError
from qojvp.native_host import MAX_OUTGOING, write_frame
from tests.support import QojFixture
from tests.test_application import AT, ROOT, inline_sample_statement


def archive_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


class ResourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='resources-')
        self.fixture = QojFixture().__enter__()
        self.app = Application(self.directory.name, fixture_origin=self.fixture.origin, clock=lambda: AT)
        # Resource preparation is useful before a local practice timer starts.
        self.session = self.app.dispatch('create_session', {'contestId': '3387', 'account': 'FixtureUser'})
        self.args = {'sessionId': self.session['sessionId'], 'problemId': '15419'}

    def tearDown(self):
        self.app.close()
        self.fixture.__exit__(None, None, None)
        self.directory.cleanup()

    def prepare(self, **args):
        return self.app.dispatch('prepare_resource', {**self.args, **args}, self.fixture.exchange)

    def attach(self, files):
        self.fixture.attachment_overrides['15419'] = (200, archive_bytes(files), 'application/zip')

    def offline(self, method, args):
        def forbidden(_):
            self.fail('A cache read attempted network access')
        return self.app.dispatch(method, args, forbidden)

    def download(self, entry):
        output = bytearray()
        while True:
            chunk = self.offline('resource_chunk', {**self.args, 'resourceId': entry['resourceId'],
                                                   'offset': len(output)})
            data = base64.b64decode(chunk['bytesBase64'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), chunk['chunkSha256'])
            self.assertEqual(chunk['offset'], len(output))
            output.extend(data)
            self.assertEqual(chunk['nextOffset'], len(output))
            frame = io.BytesIO()
            write_frame(frame, {'type': 'result', 'id': 'resource-test', 'ok': True, 'result': chunk})
            self.assertLess(len(frame.getvalue()), MAX_OUTGOING)
            if chunk['eof']:
                break
        self.assertEqual(len(output), entry['totalBytes'])
        self.assertEqual(hashlib.sha256(output).hexdigest(), entry['sha256'])
        return bytes(output)

    def test_prepared_session_resources_survive_restart_and_read_without_network(self):
        self.attach({'sample7.in': b'1\n', 'sample7.ans': b'2\n'})
        entry = self.prepare()
        self.assertEqual((entry['status'], entry['kind'], entry['sampleCount'], entry['pairCount']),
                         ('ready', 'samples', 1, 1))
        self.assertEqual(entry['filename'], 'samples-A.zip')
        self.assertNotIn('zipBase64', entry)
        self.assertEqual(self.app.dispatch('inspect_session', {'sessionId': self.session['sessionId']})['state'], 'prepared')
        self.app.close()
        self.app = Application(self.directory.name, clock=lambda: AT + 1000)
        manifest = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})
        self.assertEqual(manifest['problems'][0]['resourceId'], entry['resourceId'])
        with zipfile.ZipFile(io.BytesIO(self.download(entry))) as archive:
            self.assertEqual(archive.read('samples-A/1.in'), b'1\n')
            self.assertEqual(archive.read('samples-A/1.ans'), b'2\n')
        self.assertEqual(self.fixture.posts, [])

    def test_extras_only_retains_nested_interactor_path_and_exact_bytes(self):
        contents = b'// synthetic interactor\r\n\x00\xff'
        self.attach({'tools/interactor.cpp': contents})
        entry = self.prepare(interactiveHint=True)
        self.assertEqual((entry['status'], entry['kind'], entry['sampleCount']), ('ready', 'attachment', 0))
        self.assertEqual(entry['filename'], 'attachments-A.zip')
        with zipfile.ZipFile(io.BytesIO(self.download(entry))) as archive:
            self.assertEqual(archive.namelist(), ['attachment-extras/problem-A/tools/interactor.cpp'])
            self.assertEqual(archive.read(archive.namelist()[0]), contents)
        self.assertNotIn('interactive', entry)

    def test_mixed_and_incomplete_attachments_keep_original_files(self):
        self.attach({'example.in': b'input', 'tools/checker.cpp': b'checker'})
        entry = self.prepare()
        self.assertEqual((entry['kind'], entry['sampleCount'], entry['pairCount']), ('attachment', 1, 0))
        with zipfile.ZipFile(io.BytesIO(self.download(entry))) as archive:
            self.assertEqual(archive.read('samples-A/1.in'), b'input')
            self.assertEqual(archive.read('attachment-extras/problem-A/example.in'), b'input')
            self.assertEqual(archive.read('attachment-extras/problem-A/tools/checker.cpp'), b'checker')

    def test_negative_responses_remain_unknown_without_empty_zip(self):
        for status, data, kind in [(404, b'not found', 'text/plain'), (200, b'', 'application/octet-stream'),
                                   (200, archive_bytes({}), 'application/zip'), (403, b'blocked', 'text/html')]:
            with self.subTest(status=status, size=len(data)):
                self.fixture.attachment_overrides['15419'] = (status, data, kind)
                entry = self.prepare()
                self.assertEqual(entry['status'], 'unknown')
                self.assertEqual(entry['lastAttempt']['status'], 'unknown')
                self.assertNotIn('resourceId', entry)
                self.assertNotIn('kind', entry)
                self.assertEqual(list((Path(self.directory.name) / 'resources').rglob('*.zip')), [])
        entry = self.app.dispatch('prepare_resource', self.args, lambda _: {'error': {'code': 'READ_OFFLINE'}})
        self.assertEqual(entry['status'], 'unknown')
        self.assertNotIn('resourceId', entry)

    def test_interactive_hint_blocks_inline_dialogue_fallback(self):
        self.fixture.attachment_overrides['15419'] = (404, b'not found', 'text/plain')
        self.fixture.problem_html['15419'] = inline_sample_statement()
        entry = self.prepare(interactiveHint=True)
        self.assertEqual(entry['status'], 'unknown')
        entry = self.prepare(interactiveHint=False)
        self.assertEqual((entry['status'], entry['sampleSource']), ('ready', 'inline-statement'))
        old_inline = self.prepare(interactiveHint=True)
        self.assertEqual(old_inline['resourceId'], entry['resourceId'])
        self.assertEqual(old_inline['sampleSource'], 'inline-statement')
        self.assertEqual(old_inline['lastAttempt']['status'], 'unknown')
        self.assertTrue(old_inline['lastAttempt']['interactiveHint'])

    def test_failed_refresh_keeps_previous_verified_package(self):
        self.attach({'one.in': b'a', 'one.ans': b'b'})
        good = self.prepare()
        self.fixture.attachment_overrides['15419'] = (404, b'not found', 'text/plain')
        failed = self.prepare()
        self.assertEqual((failed['status'], failed['resourceId']), ('ready', good['resourceId']))
        self.assertEqual(failed['lastAttempt']['status'], 'unknown')
        self.assertEqual(self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0], failed)
        self.download(failed)
        self.fixture.account = 'OtherUser'
        failed_account = self.prepare()
        self.assertEqual(failed_account['resourceId'], good['resourceId'])
        self.assertEqual(failed_account['lastAttempt']['code'], 'ACCOUNT_MISMATCH')

    def test_authenticated_html_and_tokens_are_not_written_to_resource_cache(self):
        private_marker = 'synthetic-private-csrf-do-not-persist'
        html = ('<!doctype html><html><form><input name="_token" value="' + private_marker + '"></form></html>').encode()
        self.fixture.attachment_overrides['15419'] = (200, html, 'text/html')
        entry = self.prepare()
        self.assertEqual(entry['status'], 'unknown')
        for path in (Path(self.directory.name) / 'resources').rglob('*'):
            if path.is_file():
                self.assertNotIn(private_marker.encode(), path.read_bytes())
                self.assertNotIn(b'<html', path.read_bytes())
        self.assertNotIn(private_marker, json.dumps(entry))

    def test_account_and_contest_scopes_cannot_read_each_others_objects(self):
        self.attach({'one.in': b'a', 'one.ans': b'b'})
        good = self.prepare()
        for other in ({'contestId': '3387', 'account': 'OtherUser'},
                      {'contestId': '9999', 'account': 'FixtureUser'}):
            session = self.app.dispatch('create_session', other)
            self.assertEqual(self.offline('resource_manifest', {'sessionId': session['sessionId']})['problems'], [])
            with self.assertRaises(ApplicationError) as cm:
                self.offline('resource_chunk', {**self.args, 'sessionId': session['sessionId'],
                                               'resourceId': good['resourceId'], 'offset': 0})
            self.assertEqual(cm.exception.code, 'RESOURCE_NOT_FOUND')

    def test_cache_corruption_never_returns_trusted_ready_data(self):
        self.attach({'one.in': b'a', 'one.ans': b'b'})
        good = self.prepare()
        path = next((Path(self.directory.name) / 'resources').rglob(good['resourceId'] + '.zip'))
        path.write_bytes(b'corrupt')
        entry = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
        self.assertEqual(entry['status'], 'unknown')
        self.assertEqual(entry['lastAttempt']['code'], 'CACHE_CORRUPT')
        with self.assertRaises(ApplicationError) as cm:
            self.offline('resource_chunk', {**self.args, 'resourceId': good['resourceId'], 'offset': 0})
        self.assertEqual(cm.exception.code, 'CACHE_CORRUPT')

    def test_resource_id_and_chunk_ranges_are_validated(self):
        self.attach({'one.in': b'a', 'one.ans': b'b'})
        good = self.prepare()
        cases = [{'offset': -1}, {'offset': True}, {'offset': 1.5}, {'offset': good['totalBytes'] + 1},
                 {'maxBytes': 0}, {'maxBytes': 262145}, {'resourceId': '../../vp.sqlite3'},
                 {'resourceId': '0' * 64}]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ApplicationError):
                self.offline('resource_chunk', {**self.args, 'resourceId': good['resourceId'], 'offset': 0, **fields})
        eof = self.offline('resource_chunk', {**self.args, 'resourceId': good['resourceId'], 'offset': good['totalBytes']})
        self.assertTrue(eof['eof'])
        self.assertEqual(eof['bytesBase64'], '')

    def test_large_attachment_uses_bounded_native_chunks_and_legacy_limit_remains(self):
        data = random.Random(43).randbytes(800000)
        self.attach({'interactor.bin': data})
        good = self.prepare()
        self.assertGreater(good['totalBytes'], 512 * 1024)
        with zipfile.ZipFile(io.BytesIO(self.download(good))) as archive:
            self.assertEqual(archive.read('attachment-extras/problem-A/interactor.bin'), data)
        result_frame = io.BytesIO()
        write_frame(result_frame, {'type': 'result', 'id': 'prepare', 'ok': True, 'result': good})
        self.assertLess(len(result_frame.getvalue()), MAX_OUTGOING)
        with self.assertRaises(ApplicationError) as cm:
            self.app.dispatch('qoj_samples', self.args, self.fixture.exchange)
        self.assertEqual(cm.exception.code, 'ARTIFACT_TOO_LARGE')


if __name__ == '__main__':
    unittest.main()
