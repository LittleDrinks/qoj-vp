"""Read contest navigation without guessing a scoreboard or participation identity."""
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import re
from bs4 import BeautifulSoup


def contest_navigation(html, cid):
    cid = str(cid)
    if not re.fullmatch(r'\d{1,20}', cid):
        return {}
    page = BeautifulSoup(html, 'html.parser')
    standings, discussions = [], []
    for anchor in page.select('.nav a[href]'):
        raw = anchor.get('href', '')
        url = urlsplit(urljoin('https://qoj.ac/', raw))
        if url.scheme != 'https' or url.netloc != 'qoj.ac' or url.username or url.password or url.fragment:
            continue
        text = anchor.get_text(' ', strip=True).casefold()
        # A menu item can carry authentication parameters. Never persist them.
        query = parse_qsl(url.query, keep_blank_values=True)
        if any(key != 'mode' or value != 'pc2' for key, value in query) or len(query) > 1:
            continue
        safe = urlunsplit(('https', 'qoj.ac', url.path, urlencode(query), ''))
        if url.path.rstrip('/') == f'/contest/{cid}/discussions' and not query:
            discussions.append(safe)
        if not any(word in text for word in ('standings', 'scoreboard', '排名', '榜单')):
            continue
        if url.path.rstrip('/') == f'/contest/{cid}/standings' or re.fullmatch(rf'/results/QOJ{cid}/?', url.path):
            standings.append(safe)
    result = {}
    if len(set(standings)) == 1:
        result['scoreboardUrl'] = standings[0]
    if len(set(discussions)) == 1:
        result['discussionsUrl'] = discussions[0]
    return result
