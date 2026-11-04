from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from qojvp import Application, ApplicationError
from qojvp.native_host import MAX_OUTGOING, write_frame
from tests.unit.support import QojFixture
from tests.unit.test_application import AT, ROOT, inline_sample_statement


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
        self.fixture.attachment_overrides[self.args['problemId']] = (200, archive_bytes(files), 'application/zip')

    def mixed_changchun(self, *, incomplete=False):
        self.args['problemId'] = '22918'
        self.fixture.contest_html = ('<table><tr><td>I</td><td>'
            '<a href="/contest/3387/problem/22918">Synthetic Changchun resource shape</a></td></tr></table>')
        files = {'1.in': b'first input\r\n', '1.ans': b'first answer\n',
                 '2.in': b'second input\n', '2.ans': b'second answer\n',
                 'triplet_testing_tool.py': b'# synthetic tester payload\n'}
        if incomplete:
            files['3.in'] = b'unpaired input\n'
        self.attach(files)
        return files, self.prepare(interactiveHint=True)

    def make_legacy(self, entry):
        legacy = {key: value for key, value in entry.items() if key != 'downloads'}
        self.app.resources.write_entry(self.session, self.args['problemId'], legacy)
        for download in entry.get('downloads', []):
            if download['resourceId'] != entry['resourceId']:
                self.app.resources.object_path(self.session, self.args['problemId'], download).unlink(missing_ok=True)
        return legacy

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

    def test_changchun_mixed_resource_has_independent_samples_and_original_attachment_downloads(self):
        original, entry = self.mixed_changchun()
        downloads = entry.get('downloads', [])
        self.assertEqual([item['kind'] for item in downloads], ['samples', 'attachment'])
        self.assertEqual([item['filename'] for item in downloads], ['samples-I.zip', 'attachments-I.zip'])
        self.assertEqual(len({entry['resourceId'], *(item['resourceId'] for item in downloads)}), 3)
        samples, attachments = downloads
        self.assertEqual((samples['sampleCount'], samples['pairCount']), (2, 2))
        with zipfile.ZipFile(io.BytesIO(self.download(samples))) as archive:
            self.assertEqual(set(archive.namelist()), {'samples-I/' + name for name in ['1.in', '1.ans', '2.in', '2.ans']})
            for name in archive.namelist():
                self.assertEqual(archive.read(name), original[name.rsplit('/', 1)[-1]])
        with zipfile.ZipFile(io.BytesIO(self.download(attachments))) as archive:
            self.assertEqual(set(archive.namelist()), {'attachment-extras/problem-I/' + name for name in original})
            for name, contents in original.items():
                self.assertEqual(archive.read('attachment-extras/problem-I/' + name), contents)
        with zipfile.ZipFile(io.BytesIO(self.download(entry))) as archive:
            self.assertEqual(len(archive.namelist()), 9)

    def test_unpaired_sample_input_remains_in_attachments_without_entering_complete_samples(self):
        original, entry = self.mixed_changchun(incomplete=True)
        self.assertEqual(len(entry.get('downloads', [])), 2)
        samples, attachments = entry['downloads']
        with zipfile.ZipFile(io.BytesIO(self.download(samples))) as archive:
            self.assertNotIn('samples-I/3.in', archive.namelist())
            self.assertEqual(len(archive.namelist()), 4)
        with zipfile.ZipFile(io.BytesIO(self.download(attachments))) as archive:
            self.assertEqual(archive.read('samples-I/3.in'), original['3.in'])
            self.assertEqual(archive.read('attachment-extras/problem-I/3.in'), original['3.in'])

    def test_old_combined_cache_migrates_offline_and_still_serves_legacy_resource_id(self):
        _, prepared = self.mixed_changchun()
        self.assertEqual(len(prepared.get('downloads', [])), 2)
        legacy = self.make_legacy(prepared)
        self.app.close()
        self.app = Application(self.directory.name, clock=lambda: AT + 1000)
        migrated = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
        self.assertEqual([item['kind'] for item in migrated['downloads']], ['samples', 'attachment'])
        self.assertEqual(migrated['resourceId'], legacy['resourceId'])
        self.assertEqual(migrated['preparedAt'], legacy['preparedAt'])
        self.assertEqual([item['resourceId'] for item in migrated['downloads']],
                         [item['resourceId'] for item in prepared['downloads']])
        for item in [migrated, *migrated['downloads']]:
            self.download(item)
        self.assertEqual(self.fixture.posts, [])

    def test_single_download_reuses_original_object_instead_of_copying_it(self):
        for files, kind in [({'1.in': b'input', '1.ans': b'answer'}, 'samples'),
                            ({'tools/interactor.py': b'payload'}, 'attachment')]:
            with self.subTest(kind=kind):
                self.attach(files)
                entry = self.prepare()
                self.assertEqual(len(entry.get('downloads', [])), 1)
                self.assertEqual((entry['downloads'][0]['kind'], entry['downloads'][0]['resourceId']),
                                 (kind, entry['resourceId']))
                self.make_legacy(entry)
                migrated = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
                self.assertEqual(migrated['downloads'][0]['resourceId'], entry['resourceId'])

    def test_failed_refresh_retains_verified_downloads_and_replaced_manifest_unbinds_old_ids(self):
        _, entry = self.mixed_changchun()
        self.assertEqual(len(entry.get('downloads', [])), 2)
        self.fixture.attachment_overrides[self.args['problemId']] = (404, b'not found', 'text/plain')
        failed = self.prepare(interactiveHint=True)
        self.assertEqual(failed['status'], 'ready')
        self.assertEqual(failed['downloads'], entry['downloads'])
        self.assertEqual(failed['lastAttempt']['status'], 'unknown')
        for descriptor in failed['downloads']:
            self.download(descriptor)
        self.attach({'different.in': b'new input', 'different.ans': b'new answer'})
        self.prepare()
        for descriptor in entry['downloads']:
            with self.assertRaises(ApplicationError) as error:
                self.offline('resource_chunk', {**self.args, 'resourceId': descriptor['resourceId'], 'offset': 0})
            self.assertEqual(error.exception.code, 'RESOURCE_NOT_FOUND')

    def test_old_cache_migration_checks_member_hashes_before_creating_downloads(self):
        _, entry = self.mixed_changchun()
        legacy = self.make_legacy(entry)
        legacy['files'][0]['sha256'] = '0' * 64
        self.app.resources.write_entry(self.session, self.args['problemId'], legacy)
        observed = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
        self.assertEqual(observed['status'], 'unknown')
        self.assertEqual(observed['lastAttempt']['code'], 'CACHE_CORRUPT')
        self.assertNotIn('downloads', observed)

    def test_migration_rejects_unsafe_zip_paths_and_extraction_limits(self):
        _, entry = self.mixed_changchun()
        legacy = self.make_legacy(entry)
        for name in ['../outside.py', '/outside.py', 'attachment-extras/problem-I/../outside.py',
                     'attachment-extras/problem-I/tools\\outside.py']:
            with self.subTest(name=name):
                payload = archive_bytes({name: b'untrusted'})
                digest = hashlib.sha256(payload).hexdigest()
                altered = {**legacy, 'resourceId': digest, 'sha256': digest, 'totalBytes': len(payload),
                    'files': [{'name': name, 'bytes': 9, 'sha256': hashlib.sha256(b'untrusted').hexdigest()}]}
                self.app.resources.atomic_write(self.app.resources.object_path(self.session, self.args['problemId'], altered), payload)
                self.app.resources.write_entry(self.session, self.args['problemId'], altered)
                observed = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
                self.assertEqual(observed['status'], 'unknown')
                self.assertEqual(observed['lastAttempt']['code'], 'CACHE_CORRUPT')
        for limit in ['MAX_ARCHIVE_FILES', 'MAX_EXPANDED_BYTES']:
            with self.subTest(limit=limit), patch('qojvp.resources.' + limit, 1):
                self.app.resources.write_entry(self.session, self.args['problemId'], legacy)
                observed = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
                self.assertEqual(observed['status'], 'unknown')
                self.assertEqual(observed['lastAttempt']['code'], 'CACHE_CORRUPT')

    def test_split_object_corruption_is_not_returned_as_ready_or_downloadable(self):
        _, entry = self.mixed_changchun()
        descriptor = entry['downloads'][0]
        self.app.resources.object_path(self.session, self.args['problemId'], descriptor).write_bytes(b'corrupted split file')
        observed = self.offline('resource_manifest', {'sessionId': self.session['sessionId']})['problems'][0]
        self.assertEqual(observed['status'], 'unknown')
        with self.assertRaises(ApplicationError) as error:
            self.download(descriptor)
        self.assertEqual(error.exception.code, 'CACHE_CORRUPT')

    def test_concurrent_offline_migration_publishes_one_complete_download_manifest(self):
        _, entry = self.mixed_changchun()
        self.make_legacy(entry)
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: self.app.resources.manifest(self.session), range(4)))
        manifests = [result['problems'][0] for result in results]
        self.assertTrue(all(manifest == manifests[0] for manifest in manifests))
        self.assertEqual([item['kind'] for item in manifests[0]['downloads']], ['samples', 'attachment'])
        for descriptor in manifests[0]['downloads']:
            self.download(descriptor)

    def test_split_downloads_remain_bound_to_account_contest_and_problem(self):
        _, entry = self.mixed_changchun()
        self.assertEqual(len(entry.get('downloads', [])), 2)
        for other in [{'contestId': '3387', 'account': 'OtherUser'}, {'contestId': '9999', 'account': 'FixtureUser'}]:
            session = self.app.dispatch('create_session', other)
            for descriptor in entry['downloads']:
                with self.assertRaises(ApplicationError) as error:
                    self.offline('resource_chunk', {**self.args, 'sessionId': session['sessionId'],
                        'resourceId': descriptor['resourceId'], 'offset': 0})
                self.assertEqual(error.exception.code, 'RESOURCE_NOT_FOUND')
        for descriptor in entry['downloads']:
            with self.assertRaises(ApplicationError) as error:
                self.offline('resource_chunk', {**self.args, 'problemId': '15419',
                    'resourceId': descriptor['resourceId'], 'offset': 0})
            self.assertEqual(error.exception.code, 'RESOURCE_NOT_FOUND')

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
        # An already prepared object spans several native messages. Opening
        # compressed members on each chunk would inflate the whole ZIP again.
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('Cached chunks must not decompress ZIP members')):
            downloaded = self.download(good)
        with zipfile.ZipFile(io.BytesIO(downloaded)) as archive:
            self.assertEqual(archive.read('attachment-extras/problem-A/interactor.bin'), data)
        result_frame = io.BytesIO()
        write_frame(result_frame, {'type': 'result', 'id': 'prepare', 'ok': True, 'result': good})
        self.assertLess(len(result_frame.getvalue()), MAX_OUTGOING)
        with self.assertRaises(ApplicationError) as cm:
            self.app.dispatch('qoj_samples', self.args, self.fixture.exchange)
        self.assertEqual(cm.exception.code, 'ARTIFACT_TOO_LARGE')


if __name__ == '__main__':
    unittest.main()
