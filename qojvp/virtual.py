"""Read QOJ's native VP pages without registering or starting a contest."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .account import navigation_account
from .transport import BASE


class VirtualPageError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def verify_page(response, cid, account, *, registration=False):
    parsed = urlparse(response.url)
    expected = f'/contest/{cid}' + ('/virtual/register' if registration else '')
    if parsed.path.startswith('/login'):
        raise VirtualPageError('LOGIN_REQUIRED', 'Log in to QOJ in Firefox before preparing this VP')
    if (parsed.scheme != 'https' or parsed.netloc != 'qoj.ac' or parsed.username or parsed.password
            or parsed.path.rstrip('/') != expected or response.status_code != 200):
        raise VirtualPageError('QOJ_VIRTUAL_PAGE_MISMATCH', 'QOJ did not return the requested VP page')
    found = navigation_account(response.text)
    if not found:
        raise VirtualPageError('ACCOUNT_UNKNOWN', 'QOJ did not expose an unambiguous account on this VP page')
    if found.casefold() != account.casefold():
        raise VirtualPageError('ACCOUNT_MISMATCH', 'The QOJ account changed while reading this VP')


def _form(page, cid, form_id, button_id, button_name, *, registration=False):
    forms = page.select('form#' + form_id)
    if len(forms) != 1:
        return None
    form = forms[0]
    path = f'/contest/{cid}' + ('/virtual/register' if registration else '')
    action = urlparse(urljoin(BASE + path, form.get('action') or path))
    buttons = form.select(f'button#{button_id}[name="{button_name}"][type="submit"]')
    if ((form.get('method') or 'get').lower() != 'post' or len(buttons) != 1
            or action.scheme != 'https' or action.netloc != 'qoj.ac' or action.username or action.password
            or action.path.rstrip('/') != path or action.query or action.fragment):
        return None
    return form


def registration_rules(html, cid):
    """The form identities and English rule were observed on QOJ 2644."""
    page = BeautifulSoup(html, 'html.parser')
    form = _form(page, cid, 'form-register_vp', 'button-submit-register_vp', 'submit-register_vp', registration=True)
    if form is None:
        raise VirtualPageError('QOJ_VIRTUAL_PAGE_UNSUPPORTED', 'The QOJ VP confirmation form was not recognized')
    durations = set()
    for node in page.select('li'):
        text = node.get_text(' ', strip=True)
        match = re.fullmatch(r'The contest is (\d+) minutes long\.', text, re.I)
        if not match:
            match = re.fullmatch(r'(?:本场)?比赛(?:的)?时长(?:为|是|：|:)\s*(\d+)\s*分钟[。.！!]?', text)
        if match:
            duration = int(match[1]) * 60000
            if 0 < duration <= 14 * 86400000:
                durations.add(duration)
    if len(durations) != 1:
        raise VirtualPageError('QOJ_VIRTUAL_DURATION_UNKNOWN', 'The native QOJ VP duration could not be verified')
    return {'state': 'not_started', 'startAt': None, 'durationMs': durations.pop(),
            'source': 'qoj-registration-rules', 'registrationUrl': f'{BASE}/contest/{cid}/virtual/register'}


def registration_snapshot(snapshot, cid, account):
    """Validate the browser's minimal registration DOM captured before POST.

    The background must validate the real tab, sender and register URL before
    forwarding this, just as it validates BrowserSession HTTP responses. Raw
    DOM is only used during this request; the ledger retains parsed rules.
    """
    if (not isinstance(snapshot, dict) or set(snapshot) != {'url', 'html'}
            or not isinstance(snapshot['url'], str) or not isinstance(snapshot['html'], str)
            or len(snapshot['url']) > 2048 or len(snapshot['html'].encode('utf-8')) > 131072):
        raise VirtualPageError('QOJ_VIRTUAL_SNAPSHOT_INVALID', 'Invalid captured QOJ registration page')
    response = SimpleNamespace(url=snapshot['url'], text=snapshot['html'], status_code=200)
    verify_page(response, cid, account, registration=True)
    rules = registration_rules(response.text, cid)
    return {**rules, 'source': 'qoj-registration-snapshot'}


def _server_countdown(page, duration_ms):
    """Read the raw, server-rendered QOJ 2644 clock observed Nov 3, 2026.

    This card is also used by normal contests. The caller must already have a
    native VP registration binding and a duration verified from QOJ's rules.
    Both clock operands come from the same HTTP response, never local time.
    """
    if (isinstance(duration_ms, bool) or not isinstance(duration_ms, int)
            or not 0 < duration_ms <= 14 * 86400000):
        return None
    clocks = page.select('.countdown')
    if len(clocks) != 1:
        return None
    clock = clocks[0]
    card = clock.find_parent(class_='card')
    headers = card.select('.card-header') if card else []
    remaining = clock.get('data-rest', '')
    if (len(headers) != 1 or headers[0].get_text(' ', strip=True) != 'Contest ends in'
            or not re.fullmatch(r'\d{1,8}', remaining)):
        return None
    remaining_ms = int(remaining) * 1000
    if remaining_ms > duration_ms:
        return None
    clocks = []
    for node in page.select('.uoj-footer p'):
        match = re.fullmatch(r'Server Time:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*'
                             r'\(UTC([+-])(\d{1,2})(?::(\d{2}))?\)', node.get_text(' ', strip=True))
        if not match:
            continue
        hours, minutes = int(match[3]), int(match[4] or 0)
        if hours > 14 or minutes > 59 or hours == 14 and minutes:
            return None
        offset = (hours * 60 + minutes) * (1 if match[2] == '+' else -1)
        try:
            server = datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S').replace(
                tzinfo=timezone(timedelta(minutes=offset)))
        except ValueError:
            return None
        clocks.append(int(server.timestamp() * 1000))
    if len(clocks) != 1:
        return None
    server_now = clocks[0]
    return {'state': 'running', 'startAt': server_now + remaining_ms - duration_ms,
            'durationMs': duration_ms, 'serverNow': server_now, 'remainingMs': remaining_ms,
            'timeSource': 'provider-countdown', 'source': 'qoj-native-server-countdown'}


def dashboard_state(html, cid, *, native_duration_ms=None):
    """Unknown clock formats never become a local start time."""
    page = BeautifulSoup(html, 'html.parser')
    waiting = _form(page, cid, 'form-regvir', 'button-submit-regvir', 'submit-regvir')
    if waiting is not None:
        return {'state': 'not_started', 'startAt': None, 'source': 'qoj-native-registration-entry'}
    finished = _form(page, cid, 'form-finish-panel', 'button-submit-finish-panel', 'submit-finish-panel')
    if finished is not None:
        card = finished.find_parent(class_='card')
        text = card.get_text(' ', strip=True) if card else ''
        if 'Your participation in the contest has been finished.' in text:
            return {'state': 'finished', 'startAt': None, 'source': 'qoj-native-finished-panel'}
    if native_duration_ms is not None:
        running = _server_countdown(page, native_duration_ms)
        if running is not None:
            return running
    return {'state': 'unknown', 'startAt': None, 'source': 'qoj-native-clock-unverified'}
