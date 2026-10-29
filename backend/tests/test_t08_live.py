"""T-08 live walk through the frontend proxy when a local portal is running."""
import json
import os
import unittest
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


CANDIDATES = [
    os.getenv('T08_FRONTEND_URL', '').rstrip('/'),
    'http://127.0.0.1:3040',
    'http://127.0.0.1:3030',
    'http://127.0.0.1:3021',
    'http://127.0.0.1:3020',
    'http://127.0.0.1:3010',
    'http://127.0.0.1:3000',
]


def _current_carecredits(opener, candidate):
    request = Request(
        candidate + '/api/v1/config',
        method='GET',
        headers={'X-Care-Client': '1', 'Origin': candidate},
    )
    try:
        with opener.open(request, timeout=3) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False
    if not (isinstance(payload, dict) and {'demo', 'signup_enabled'} <= set(payload)):
        return False
    html_ok = False
    for path in ('/live', '/'):
        page = Request(candidate + path, method='GET', headers={'Accept': 'text/html'})
        try:
            with opener.open(page, timeout=3) as response:
                ctype = response.headers.get('Content-Type') or ''
                body = response.read().decode('utf-8', 'replace')
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            continue
        if 'text/html' in ctype and 'Skip to' in body:
            html_ok = True
            break
    if not html_ok:
        return False
    live = Request(candidate + '/health/live', method='GET', headers={'Accept': 'application/json'})
    try:
        with opener.open(live, timeout=3) as response:
            health = json.loads(response.read().decode() or '{}')
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False
    if not (isinstance(health, dict) and health.get('status') == 'live'):
        return False
    probe = Request(
        candidate + '/api/v1/me',
        method='GET',
        headers={'X-Care-Client': '1', 'Origin': candidate},
    )
    try:
        with opener.open(probe, timeout=3):
            return True
    except HTTPError as exc:
        return exc.code in {401, 403}
    except (URLError, TimeoutError, OSError):
        return False


def _carecredits_frontend():
    seen = []
    for candidate in CANDIDATES:
        if not candidate or candidate in seen:
            continue
        seen.append(candidate)
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        if _current_carecredits(opener, candidate):
            return candidate
    return None


FRONTEND = _carecredits_frontend()


class LivePortalWalkTests(unittest.TestCase):
    def setUp(self):
        if not FRONTEND:
            self.skipTest('A current CareCredits frontend is not running on :3040, :3030, :3021, :3020, :3010, or :3000')
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.origin = FRONTEND

    def _open(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(
            FRONTEND + path,
            data=data,
            method=method,
            headers={'Content-Type': 'application/json', 'X-Care-Client': '1', 'Origin': self.origin},
        )
        try:
            with self.opener.open(request, timeout=8) as response:
                return response.status, response.headers.get('Content-Type') or '', response.read()
        except HTTPError as exc:
            return exc.code, exc.headers.get('Content-Type') or '', exc.read()

    def _json(self, method, path, body=None):
        status, _ctype, raw = self._open(method, path, body)
        try:
            return status, json.loads(raw.decode() or '{}')
        except ValueError:
            return status, raw

    def test_sign_in_search_and_detail_through_frontend_proxy(self):
        try:
            status, config = self._json('GET', '/api/v1/config')
        except URLError:
            self.skipTest('Frontend is not running at ' + FRONTEND)
        if status != 200 or not isinstance(config, dict) or not config.get('demo'):
            self.skipTest('Live T-08 walk needs DEMO_MODE seed (demo@carecredits.local) at ' + FRONTEND)
        live_status, live_type, live_raw = self._open('GET', '/live')
        self.assertEqual(live_status, 200, live_raw[:200])
        self.assertIn('text/html', live_type)
        live_html = live_raw.decode('utf-8', 'replace')
        self.assertIn('Skip to', live_html)
        health_status, health_payload = self._json('GET', '/health/live')
        self.assertEqual(health_status, 200, health_payload)
        self.assertEqual(health_payload.get('status'), 'live')
        skip_at = live_html.lower().find('skip to')
        email_at = live_html.lower().find('autocomplete="username"')
        self.assertGreater(skip_at, -1)
        if email_at > 0:
            self.assertLess(skip_at, email_at)
        home_status, home_type, home_raw = self._open('GET', '/')
        self.assertEqual(home_status, 200, home_raw[:200])
        self.assertIn('text/html', home_type)
        self.assertIn('Skip to', home_raw.decode('utf-8', 'replace'))
        user = None
        for email in ('demo@carecredits.local', 'doctor@carecredits.local'):
            status, payload = self._json(
                'POST',
                '/api/v1/auth/login',
                {'email': email, 'password': 'CareCredits-demo-2026'},
            )
            if status == 200:
                user = payload
                break
        if user is None:
            self.skipTest('Documented demo login is not available at ' + FRONTEND)
        self.assertTrue(user.get('name'))
        progress = self._json('GET', '/api/v1/me/progress')
        self.assertEqual(progress[0], 200, progress[1])
        self.assertIn('excluded_reasons', progress[1])
        suggestions = self._json('GET', '/api/v1/me/suggestions')
        self.assertEqual(suggestions[0], 200, suggestions[1])
        digest = self._json('GET', '/api/v1/me/digest')
        self.assertEqual(digest[0], 200, digest[1])
        self.assertIn('opted_in', digest[1])
        audit = self._json('GET', '/api/v1/me/audit?page=1&page_size=8')
        self.assertEqual(audit[0], 200, audit[1])
        self.assertIn('items', audit[1])
        self.assertNotIn('notes', str(audit[1]).lower())
        export_status, export_type, _raw = self._open('GET', '/api/v1/me/export/csv')
        self.assertEqual(export_status, 200)
        self.assertIn('text/csv', export_type)
        eml_status, eml_type, _eml = self._open('GET', '/api/v1/me/export/eml')
        self.assertEqual(eml_status, 200)
        self.assertIn('message/rfc822', eml_type)
        cert = self._json('POST', '/api/v1/me/certificates', {'year': 2026})
        self.assertEqual(cert[0], 201, cert[1])
        self.assertTrue(cert[1].get('id'))
        listed = self._json('GET', '/api/v1/trainings?period=upcoming&q=GP&page_size=5')
        self.assertEqual(listed[0], 200, listed[1])
        items = listed[1].get('items') or []
        if not items:
            listed = self._json('GET', '/api/v1/trainings?period=all&q=GP&page_size=5')
            self.assertEqual(listed[0], 200, listed[1])
            items = listed[1].get('items') or []
        self.assertTrue(items, 'Catalogue search returned no trainings')
        course_id = items[0]['id']
        before = self._json('GET', '/api/v1/me/trainings')
        detail = self._json('GET', '/api/v1/trainings/' + course_id)
        self.assertEqual(detail[0], 200, detail[1])
        self.assertIn('title', detail[1])
        self.assertIsNone(detail[1].get('record'))
        history = self._json('GET', '/api/v1/me/trainings/' + course_id + '/history')
        self.assertEqual(history[0], 200, history[1])
        self.assertIn('items', history[1])
        after = self._json('GET', '/api/v1/me/trainings')
        self.assertEqual(before[1].get('total'), after[1].get('total'))
