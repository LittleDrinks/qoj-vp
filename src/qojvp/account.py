"""Verify QOJ's navigation account independently of localized link labels."""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .transport import BASE

UNKNOWN_ACCOUNT = '(account name unavailable)'


def _qoj_path(href):
    parsed = urlparse(urljoin(BASE + '/', str(href)))
    if parsed.scheme != 'https' or parsed.netloc != 'qoj.ac' or parsed.username or parsed.password:
        return None
    # Logout contains a CSRF query on the real site. Only the same-origin path
    # participates in identity evidence; no query is returned or persisted.
    return parsed.path


def navigation_account(html):
    """Account scope observed in actual VMware/QOJ menu metadata.

    Header username and localized profile menu links belong to a nav dropdown.
    Logout is a separate li.nav-item within the same right-hand ul.nav. Footer
    authors and arbitrary body profile links cannot identify the current user.
    """
    page = BeautifulSoup(html, 'html.parser')
    candidates = set()
    for nav in page.select('ul.nav.nav-pills.float-right'):
        if not any(_qoj_path(link['href']) == '/logout' for link in nav.select('a[href]')):
            continue
        for dropdown in nav.select('li.nav-item.dropdown'):
            for link in dropdown.select('a[href]'):
                path = _qoj_path(link['href'])
                match = re.fullmatch(r'/user/profile/([^/]+)/?', path or '')
                if not match:
                    continue
                account = unquote(match[1])
                if (not account or len(account) > 100 or any(ord(c) < 33 for c in account)
                        or any(c in account for c in '/\\') or account == UNKNOWN_ACCOUNT):
                    continue
                candidates.add(account)
    # Conflicting names within authenticated navigation are ambiguous.
    return next(iter(candidates)) if len(candidates) == 1 else None


def current_account(client):
    """Reuse the upstream status GET/checks, then verify its account scope.

    Return (verified account or None, upstream logged-in indication). The latter
    distinguishes a logged-out page from an unsupported authenticated menu.
    Neither an English body link nor the upstream placeholder is trusted.
    """
    upstream = client.status()
    response = client.session.last_response
    return navigation_account(response.text) if response is not None else None, upstream is not None
