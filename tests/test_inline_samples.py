from __future__ import annotations

import base64
from html import escape
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from qojvp import Application
from qojvp.inline_samples import statement_sample_files
from tests.support import QojFixture

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_INPUT = '5\n1 1 1\n2 3 3\n9 9 9\n3 26 47\n1064 822 1048576'
PUBLIC_ANSWER = '1\n7\n45\n44\n21860'


def statement(section='h3', between='', after=''):
    return ('<div class="tab-pane active"><article class="uoj-article top-buffer-md">'
            '<h3>输入格式</h3><p>Not sample input</p><h3>输出格式</h3><p>Not sample output</p>'
            '<' + section + '>样例</' + section + '><h4>输入 1</h4><pre>' + escape(PUBLIC_INPUT) + '</pre>'
            + between + '<h4>输出 1</h4><pre>' + escape(PUBLIC_ANSWER) + '</pre>'
            + after + '</article></div>')


class InlineSectionScopeTests(unittest.TestCase):
    def test_xian_prefixed_sample_labels_support_multiple_pairs(self):
        # Verified on QOJ 1051/D,E,F,G,I,J,K: the H4 labels include 样例.
        html = statement(after='<h4>样例输入 2</h4><pre>2\n3 4\n</pre>'
                               '<h4>样例输出 2</h4><pre>7\n</pre>')
        html = html.replace('<h4>输入 1', '<h4>样例输入 1').replace('<h4>输出 1', '<h4>样例输出 1')
        self.assertEqual(statement_sample_files(html), {
            'inline-1.in': (PUBLIC_INPUT + '\n').encode(),
            'inline-1.ans': (PUBLIC_ANSWER + '\n').encode(),
            'inline-2.in': b'2\n3 4\n', 'inline-2.ans': b'7\n',
        })

    def test_prefixed_labels_still_require_complete_unambiguous_pairs(self):
        html = statement().replace('<h4>输入 1', '<h4>样例输入 1').replace('<h4>输出 1', '<h4>样例输出 1')
        for invalid in (
            html.replace('样例输出 1', '样例说明 1'),
            html.replace('样例输出 1', '样例输出 2'),
            html.replace('</article>', '<h4>输入 1</h4><pre>duplicate</pre></article>'),
            html.replace('<pre>5', '<pre><code>5').replace('1048576</pre>', '1048576</code></pre>'),
        ):
            with self.subTest(invalid=invalid[:100]):
                self.assertEqual(statement_sample_files(invalid), {})

    def test_verified_raw_h3_and_existing_h2_sections_extract_only_complete_labelled_pairs(self):
        self.assertEqual((len(PUBLIC_INPUT.encode()), len(PUBLIC_ANSWER.encode())), (44, 15))
        expected = {'inline-1.in': (PUBLIC_INPUT + '\n').encode(), 'inline-1.ans': (PUBLIC_ANSWER + '\n').encode()}
        for heading in ('h2', 'h3'):
            with self.subTest(heading=heading):
                self.assertEqual(statement_sample_files(statement(heading)), expected)

    def test_other_h1_h2_h3_heading_ends_sample_scope_before_output(self):
        for sample_heading in ('h2', 'h3'):
            for boundary in ('h1', 'h2', 'h3'):
                with self.subTest(sample_heading=sample_heading, boundary=boundary):
                    self.assertEqual(statement_sample_files(statement(sample_heading,
                        between='<' + boundary + '>解释代码</' + boundary + '>')), {})

    def test_labelled_pre_in_later_non_sample_section_is_not_included(self):
        later = '<h3>实现示例</h3><h4>输入 2</h4><pre>private-looking-code</pre><h4>输出 2</h4><pre>not-a-sample</pre>'
        files = statement_sample_files(statement(after=later))
        self.assertEqual(sorted(files), ['inline-1.ans', 'inline-1.in'])
        self.assertNotIn(b'private-looking-code', b''.join(files.values()))

    def test_unverified_heading_and_non_plain_or_non_adjacent_pre_remain_rejected(self):
        cases = [statement('h1'), statement('h4'),
                 statement().replace('<h3>样例</h3>', '<h3>样例实现</h3>'),
                 statement().replace('<pre>5', '<pre><code>5').replace('1048576</pre>', '1048576</code></pre>'),
                 statement().replace('<h4>输出 1</h4><pre>', '<h4>输出 1</h4><p>untrusted separator</p><pre>')]
        for html in cases:
            with self.subTest(html=html[:130]):
                self.assertEqual(statement_sample_files(html), {})


class InlineResourceDispatchTests(unittest.TestCase):
    def test_raw_h3_statement_prepares_nonempty_cached_samples_while_interactive_hint_blocks_fallback(self):
        (ROOT / '.scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch', prefix='inline-h3-') as state, QojFixture() as fixture:
            fixture.contest_html = ('<title>Public sample shape fixture</title><table><tr><td>C</td><td>'
                '<a href="/contest/3387/problem/5115">Clone Ranran</a></td></tr></table>')
            fixture.problem_html['5115'] = statement().replace('<h4>输入 1', '<h4>样例输入 1').replace('<h4>输出 1', '<h4>样例输出 1')
            fixture.attachment_overrides['5115'] = (404, b'not found', 'text/plain')
            with Application(state, fixture_origin=fixture.origin) as app:
                session = app.dispatch('create_session', {'contestId': '3387', 'account': fixture.account})
                args = {'sessionId': session['sessionId'], 'problemId': '5115'}
                blocked = app.dispatch('prepare_resource', {**args, 'interactiveHint': True}, fixture.exchange)
                self.assertEqual(blocked['status'], 'unknown')
                self.assertNotIn('resourceId', blocked)
                ready = app.dispatch('prepare_resource', args, fixture.exchange)
                self.assertEqual(ready['status'], 'ready')
                self.assertEqual((ready['status'], ready['kind'], ready['sampleSource']), ('ready', 'samples', 'inline-statement'))
                chunk = app.dispatch('resource_chunk', {**args, 'resourceId': ready['resourceId'], 'offset': 0})
                self.assertTrue(chunk['eof'])
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(chunk['bytesBase64']))) as archive:
                    self.assertEqual(sorted(archive.namelist()), ['samples-C/1.ans', 'samples-C/1.in'])
                    self.assertEqual(archive.read('samples-C/1.in'), (PUBLIC_INPUT + '\n').encode())
                    self.assertEqual(archive.read('samples-C/1.ans'), (PUBLIC_ANSWER + '\n').encode())
                self.assertEqual(fixture.posts, [])


if __name__ == '__main__':
    unittest.main()
