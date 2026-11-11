import unittest
from qojvp.scoreboards import contest_navigation


class ScoreboardNavigationTests(unittest.TestCase):
    def test_jinan_original_contest_alias_supplies_year_for_rankland_discovery(self):
        alias = '第十一届中国大学生程序设计竞赛 济南站（CCPC 2025 Jinan Site）'
        page = '<h1>The 4th Universal Cup. Stage 9: Grand Prix of Jinan</h1>'
        page += f'<a href="/contest/2693?v=1">{alias}</a>'
        self.assertEqual(contest_navigation(page, '2693')['titles'], [alias])

    def test_aliases_only_include_named_versions_of_the_same_qoj_contest(self):
        links = ['/contest/99?v=1', '//evil.test/contest/2693?v=1',
                 '/contest/2693?v=1&token=private', '/contest/2693?v=oops',
                 'https://user@qoj.ac/contest/2693?v=1']
        page = ''.join(f'<a href="{link}">Unrelated title</a>' for link in links)
        self.assertEqual(contest_navigation(page, '2693').get('titles', []), [])

    def test_observed_ucup_external_standings_and_discussions(self):
        page = '<ul class="nav"><a href="/results/QOJ4569?mode=pc2">External Standings(PC^2)</a><a href="/contest/4569/discussions">Discussions &amp; Issues</a></ul>'
        self.assertEqual(contest_navigation(page, '4569'), {
            'titles': [],
            'scoreboardUrl': 'https://qoj.ac/results/QOJ4569?mode=pc2',
            'discussionsUrl': 'https://qoj.ac/contest/4569/discussions'})

    def test_no_guess_or_wrong_contest_or_secret_parameters(self):
        for link in ['/contest/99/standings', '/results/QOJ99?mode=pc2', '//evil.test/results/QOJ4569',
                     '/results/QOJ4569?token=private', '/results/QOJ4569?mode=pc2&token=private',
                     'https://user@qoj.ac/results/QOJ4569']:
            self.assertEqual(contest_navigation(f'<ul class="nav"><a href="{link}">Standings</a></ul>', '4569'), {'titles': []})
        self.assertEqual(contest_navigation('<article><a href="/contest/4569/standings">Standings</a></article>', '4569'), {'titles': []})

    def test_native_link_only_when_observed_and_ambiguous_stays_unbound(self):
        a = '<a href="/contest/4569/standings">Standings</a>'
        self.assertEqual(contest_navigation('<nav class="nav">'+a+'</nav>', 4569), {'titles': [], 'scoreboardUrl': 'https://qoj.ac/contest/4569/standings'})
        self.assertEqual(contest_navigation('<nav class="nav">'+a+'<a href="/results/QOJ4569">External Standings</a></nav>', 4569), {'titles': []})


if __name__ == '__main__':
    unittest.main()
