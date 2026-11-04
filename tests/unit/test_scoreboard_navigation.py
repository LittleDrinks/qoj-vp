import unittest
from qojvp.scoreboards import contest_navigation


class ScoreboardNavigationTests(unittest.TestCase):
    def test_observed_ucup_external_standings_and_discussions(self):
        page = '<ul class="nav"><a href="/results/QOJ4569?mode=pc2">External Standings(PC^2)</a><a href="/contest/4569/discussions">Discussions &amp; Issues</a></ul>'
        self.assertEqual(contest_navigation(page, '4569'), {
            'scoreboardUrl': 'https://qoj.ac/results/QOJ4569?mode=pc2',
            'discussionsUrl': 'https://qoj.ac/contest/4569/discussions'})

    def test_no_guess_or_wrong_contest_or_secret_parameters(self):
        for link in ['/contest/99/standings', '/results/QOJ99?mode=pc2', '//evil.test/results/QOJ4569',
                     '/results/QOJ4569?token=private', '/results/QOJ4569?mode=pc2&token=private',
                     'https://user@qoj.ac/results/QOJ4569']:
            self.assertEqual(contest_navigation(f'<ul class="nav"><a href="{link}">Standings</a></ul>', '4569'), {})
        self.assertEqual(contest_navigation('<article><a href="/contest/4569/standings">Standings</a></article>', '4569'), {})

    def test_native_link_only_when_observed_and_ambiguous_stays_unbound(self):
        a = '<a href="/contest/4569/standings">Standings</a>'
        self.assertEqual(contest_navigation('<nav class="nav">'+a+'</nav>', 4569), {'scoreboardUrl': 'https://qoj.ac/contest/4569/standings'})
        self.assertEqual(contest_navigation('<nav class="nav">'+a+'<a href="/results/QOJ4569">External Standings</a></nav>', 4569), {})


if __name__ == '__main__':
    unittest.main()
