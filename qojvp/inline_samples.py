"""Extract only the observed, labelled QOJ statement sample section."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def statement_page_path(url, contest_id, problem_id):
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    prefix = f'/contest/{contest_id}/problem/{problem_id}'
    if (parsed.scheme != 'https' or parsed.netloc != 'qoj.ac' or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.params
            or not re.fullmatch(re.escape(prefix) + r'(?:/statement/[A-Za-z][A-Za-z0-9_-]{0,31})?/?', parsed.path)):
        return None
    return parsed.path


def statement_language_paths(html, current_url, contest_id, problem_id):
    current_path = statement_page_path(current_url, contest_id, problem_id)
    if current_path is None:
        return []
    paths = []
    for link in BeautifulSoup(html, 'html.parser').select('a[href]'):
        try:
            candidate = statement_page_path(urljoin(current_url, link['href']), contest_id, problem_id)
        except ValueError:
            continue
        if candidate and '/statement/' in candidate and candidate != current_path and candidate not in paths:
            paths.append(candidate)
    priorities = {'zh_cn': 0, 'zh': 1, 'en': 2, 'default': 3}
    return sorted(paths, key=lambda path: priorities.get(path.rstrip('/').rsplit('/', 1)[-1].casefold(), 4))[:3]


def statement_sample_files(html):
    """Return raw .in/.ans pairs suitable for upstream samples.organize.

    Live QOJ 1051/A and C expose one active tab's article, an H2 or H3 样例 section,
    numbered H4 输入/输出 labels and adjacent plain-text PRE elements. Text in
    source snippets, explanations, inactive tabs and unrelated PREs is not data.
    Ambiguous, empty or incomplete sections are deliberately not guessed.
    """
    page = BeautifulSoup(html, 'html.parser')
    articles = page.select('div.tab-pane.active > article.uoj-article.top-buffer-md')
    if len(articles) != 1:
        return {}
    sample_section = False
    files = {}
    indexes = {'in': set(), 'ans': set()}
    for node in articles[0].find_all(recursive=False):
        if node.name in {'h1', 'h2', 'h3'}:
            text = re.sub(r'\s+', ' ', node.get_text(' ', strip=True)).casefold()
            sample_section = node.name in {'h2', 'h3'} and text in {'样例', 'sample', 'samples', 'example', 'examples'}
            continue
        if not sample_section or node.name != 'pre':
            continue
        label = node.find_previous_sibling()
        if label is None or label.name != 'h4':
            continue
        match = re.fullmatch(r'(输入|输出|input|output)\s*#?\s*(\d+)',
                             label.get_text(' ', strip=True), flags=re.IGNORECASE)
        if not match:
            continue
        # The actual verified PRE has no element children. Unknown markup
        # (copy controls, nested code widgets, hidden text) is not flattened.
        if node.find(True) is not None:
            return {}
        index = int(match[2])
        kind = 'in' if match[1].casefold() in {'输入', 'input'} else 'ans'
        if not 1 <= index <= 500 or index in indexes[kind]:
            return {}
        text = node.get_text().replace('\r\n', '\n').replace('\r', '\n')
        if not text.strip():
            return {}
        indexes[kind].add(index)
        files[f'inline-{index}.{kind}'] = (text if text.endswith('\n') else text + '\n').encode('utf-8')
    return files if indexes['in'] and indexes['in'] == indexes['ans'] else {}
