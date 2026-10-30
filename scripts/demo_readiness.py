"""Report DEMO-01 readiness without printing secrets or spending credits.

Run from the repository root with the project virtualenv:

    .venv/bin/python scripts/demo_readiness.py

Exit codes: 0 = live DEMO-01 prerequisites present; 1 = fixture-only / blocked.
Local `/health/live` probes are localhost-only and never call Tavily or the model.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / 'backend')]

from dotenv import load_dotenv  # noqa: E402
from scripts.dev import is_live_body  # noqa: E402
from shared.model_defaults import PROVISIONAL_MODEL, using_provisional  # noqa: E402


def load_owner_env() -> None:
    """Load ignored `.env` for the CLI / opted-in T-10 run. Importing this module must not."""
    load_dotenv(root / '.env')


FRONTEND_PORTS = (3040, 3030, 3021, 3020, 3010, 3000)
BACKEND_PORTS = (8022, 8021, 8020, 8010, 8000)
SCRAPER_PORTS = (8002, 8012, 18002)


def present(name: str) -> bool:
    current = (os.getenv(name) or '').strip()
    if current:
        return True
    if name in PROVISIONAL_MODEL:
        return bool(PROVISIONAL_MODEL[name])
    return False


def readiness_checks():
    return [
        ('TAVILY_API_KEY', present('TAVILY_API_KEY')),
        ('MODEL_API_KEY', present('MODEL_API_KEY')),
        ('MODEL_ID', present('MODEL_ID')),
        ('MODEL_WEIGHTS_URL', present('MODEL_WEIGHTS_URL')),
        ('MODEL_LICENSE_URL', present('MODEL_LICENSE_URL')),
        ('MODEL_OPEN_WEIGHT_CONFIRMED', (os.getenv('MODEL_OPEN_WEIGHT_CONFIRMED') or '') == 'true'),
        ('MODEL_MAX_INPUT_CHARS', present('MODEL_MAX_INPUT_CHARS')),
        ('MODEL_MAX_OUTPUT_TOKENS', present('MODEL_MAX_OUTPUT_TOKENS')),
        ('SCRAPER_SERVICE_TOKEN', present('SCRAPER_SERVICE_TOKEN')),
    ]


def live_ready() -> bool:
    return all(ok for _, ok in readiness_checks())


def format_check(label: str, ok: bool) -> str:
    """CLI line for a readiness flag. Provisional OPEN-03 identity is still OK, but labelled."""
    if ok and using_provisional(label):
        return f'  OK  {label} (OPEN-03 sample default)'
    return f'  {"OK " if ok else "NO "} {label}'


def fetch(url: str, timeout: float = 2):
    try:
        with urlopen(url, timeout=timeout) as response:
            return getattr(response, 'status', 200), response.read()
    except HTTPError as exc:
        return exc.code, exc.read() or b''
    except (URLError, TimeoutError, OSError, ValueError):
        return None, b''


def parse_json(body: bytes):
    try:
        payload = json.loads(body or b'{}')
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def classify_frontend(port: int) -> dict:
    origin = 'http://127.0.0.1:' + str(port)
    live_status, live_body = fetch(origin + '/health/live')
    live = live_status == 200 and is_live_body(parse_json(live_body) or {})
    html_status, html = fetch(origin + '/')
    skip = html_status == 200 and b'Skip to content' in (html or b'')
    config_status, config_body = fetch(origin + '/api/v1/config')
    config = parse_json(config_body) if config_status == 200 else None
    carecredits = isinstance(config, dict) and 'demo' in config
    if live and skip and carecredits:
        state = 'carecredits-live'
    elif live_status or html_status or carecredits:
        state = 'stale-or-other'
    else:
        state = 'unreachable'
    return {
        'kind': 'frontend',
        'port': port,
        'state': state,
        'health_live': live,
        'skip_link': skip,
        'demo': bool(config and config.get('demo')),
        'carecredits': carecredits,
    }


def classify_backend(port: int) -> dict:
    origin = 'http://127.0.0.1:' + str(port)
    live_status, live_body = fetch(origin + '/health/live')
    payload = parse_json(live_body) if live_status == 200 else None
    live = is_live_body(payload or {})
    config_status, config_body = fetch(origin + '/api/v1/config')
    config = parse_json(config_body) if config_status == 200 else None
    me_status, _ = fetch(origin + '/api/v1/me')
    if live:
        state = 'carecredits-live'
    elif config is not None or me_status in (401, 403):
        state = 'stale-or-other'
    elif live_status:
        state = 'stale-or-other'
    else:
        state = 'unreachable'
    return {
        'kind': 'backend',
        'port': port,
        'state': state,
        'health_live': live,
        'demo': bool(config and config.get('demo')),
        'me_status': me_status,
    }


def classify_scraper(port: int) -> dict:
    origin = 'http://127.0.0.1:' + str(port)
    live_status, live_body = fetch(origin + '/health/live')
    live = live_status == 200 and is_live_body(parse_json(live_body) or {})
    ready_status, ready_body = fetch(origin + '/health/ready')
    ready = parse_json(ready_body) if ready_status in (200, 503) else None
    if live:
        state = 'carecredits-live'
    elif ready is not None:
        state = 'stale-or-other'
    else:
        state = 'unreachable'
    return {
        'kind': 'scraper',
        'port': port,
        'state': state,
        'health_live': live,
        'tavily_configured': bool(ready and ready.get('tavily_configured')),
        'model_ready': bool(ready and ready.get('model_ready')),
    }


def local_stack():
    rows = [classify_frontend(port) for port in FRONTEND_PORTS]
    rows.extend(classify_backend(port) for port in BACKEND_PORTS)
    extra = os.getenv('SCRAPER_HEALTH_URL') or ''
    scraper_ports = list(SCRAPER_PORTS)
    if extra.startswith('http://127.0.0.1:') or extra.startswith('http://localhost:'):
        try:
            port = int(extra.rsplit(':', 1)[-1].split('/')[0])
            if port not in scraper_ports:
                scraper_ports.append(port)
        except ValueError:
            pass
    rows.extend(classify_scraper(port) for port in scraper_ports)
    return rows


def format_stack_row(row: dict) -> str:
    flags = []
    if row.get('health_live'):
        flags.append('/health/live')
    if row.get('skip_link'):
        flags.append('skip-link')
    if row.get('demo'):
        flags.append('demo')
    detail = (' (' + ', '.join(flags) + ')') if flags else ''
    return f"  {row['state'].upper():16} {row['kind']:8} :{row['port']}{detail}"


def redact_url(url: str) -> str:
    """CLI-safe URL: never print userinfo that could carry a secret."""
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit((url or '').strip())
        if not parts.scheme or not parts.netloc:
            return '(set)' if (url or '').strip() else '(default)'
        host = parts.hostname or ''
        if parts.port:
            netloc = f'{host}:{parts.port}'
        else:
            netloc = host
        return urlunsplit((parts.scheme, netloc, parts.path or '', '', ''))
    except Exception:
        return '(set)'


def main() -> int:
    load_owner_env()
    checks = readiness_checks()
    # Match scraper/worker.py: unset URL defaults to local backend.
    backend_url = (os.getenv('BACKEND_INTERNAL_URL') or 'http://127.0.0.1:8000').strip()
    print('CareCredits DEMO-01 readiness (no secrets printed, no paid API calls):')
    for label, ok in checks:
        print(format_check(label, ok))
    print(f'  OK  BACKEND_INTERNAL_URL (effective: {redact_url(backend_url)})')

    fixture = root / 'backend' / 'seed_demo.py'
    live_ui = root / 'frontend' / 'app' / 'live' / 'page.tsx'
    print(f'  {"OK " if fixture.exists() else "NO "} fixture seed module')
    print(f'  {"OK " if live_ui.exists() else "NO "} /live demo shell')

    print('Local stack identity (localhost /health/live only):')
    seen_live = {'frontend': False, 'backend': False, 'scraper': False}
    for row in local_stack():
        if row['state'] == 'unreachable':
            continue
        print(format_stack_row(row))
        if row['state'] == 'carecredits-live':
            seen_live[row['kind']] = True
    if not any(seen_live.values()):
        print('  none of the candidate ports answered as current CareCredits /health/live')
    missing_services = [name for name, ok in seen_live.items() if not ok]
    if missing_services:
        print('  missing current live services: ' + ', '.join(missing_services))
    else:
        print('  three current /health/live services are reachable on localhost candidate ports')

    live_ready_now = live_ready()
    if live_ready_now:
        print('Live DEMO-01 prerequisites look present. Set T10_LIVE=1 and run backend.tests.test_t10_live to spend one bounded Tavily+model call and record redacted evidence.')
        return 0

    missing = [label for label, ok in checks if not ok]
    print('Live DEMO-01 remains owner-blocked until these are set via scripts/setup_integrations.py:')
    for label in missing:
        print(f'  - {label}')
    print('Offline fixture path (DEMO_MODE seed + /live FIXTURE queue) can still demonstrate review and personal tracking without spending credits.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
