"""Compatibility URL configuration, independent of local board identity."""
from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

def rankland_url(raw, session_id, start_at, *, allow_loopback=False, board=None):
    if not raw:
        return None
    parsed = urlparse(str(raw).strip())
    if (parsed.scheme == 'https' and parsed.netloc == 'rl.algoux.cn'
            and not parsed.params and not parsed.fragment):
        match = re.fullmatch(r'/ranklist/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})/?', parsed.path)
        if match:
            parsed = parsed._replace(netloc='vp.xcpc.link', path='/',
                                     query=urlencode({'contest': match[1]}))
    official = parsed.scheme == 'https' and parsed.netloc == 'vp.xcpc.link'
    loopback = (allow_loopback and parsed.scheme in {'http', 'https'}
                and parsed.hostname in {'127.0.0.1', 'localhost'}
                and parsed.port is not None and 0 < parsed.port <= 65535)
    if (not (official or loopback) or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('', '/') or parsed.params or parsed.fragment):
        raise ValueError('Use a RankLand ranklist URL or a https://vp.xcpc.link/ contest URL')
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not query.get('contest'):
        raise ValueError('The RankLand URL must select a contest')
    if board is not None:
        config = board_settings(board)
        for key in ('rule', 'count', 'ratio'):
            query.pop(key, None)
        if config['rule'] != 'auto':
            query['rule'] = config['rule']
        if config['rule'] == 'CCPC26':
            query.update(count=str(config['revealCount']), ratio=str(config['revealRatio']))
    # The provider's current replay advances from `at` on the wall clock.
    # `run` is no longer a provider identity, and copied pause/speed anchors
    # must not override the QOJ clock managed by this local session.
    query.pop('run', None)
    query.pop('anchor', None)
    query.update({'from': '0', 'play': '0' if start_at is None else '1', 'speed': '1'})
    if start_at is None:
        query.pop('at', None)
    else:
        query['at'] = datetime.fromtimestamp(start_at / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    origin = (parsed.scheme, f'{parsed.hostname}:{parsed.port}') if loopback else ('https', 'vp.xcpc.link')
    return urlunparse((*origin, '/', '', urlencode(query), ''))



def board_settings(value):
    """Explicit local scoring rules; no dependence on a website storage identity."""
    if not isinstance(value, dict) or set(value) - {'rule', 'revealCount', 'revealRatio'}:
        raise ValueError('Invalid board settings')
    rule = value.get('rule', 'auto')
    count, ratio = value.get('revealCount', 50), value.get('revealRatio', 20)
    if rule not in {'auto', 'ICPC', 'CCPC26'}:
        raise ValueError('Unsupported board rules')
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100000:
        raise ValueError('Invalid CCPC26 reveal count')
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 <= ratio <= 100:
        raise ValueError('Invalid CCPC26 reveal ratio')
    if rule == 'CCPC26' and count == 0 and ratio == 0:
        raise ValueError('CCPC26 requires a nonzero reveal threshold')
    return {'rule': rule, 'revealCount': count, 'revealRatio': ratio}
