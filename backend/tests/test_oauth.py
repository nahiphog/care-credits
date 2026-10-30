import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

FOLDER = tempfile.TemporaryDirectory()
os.environ['APP_ENV'] = 'test'
os.environ['DEMO_MODE'] = 'false'
os.environ['ALLOW_SIGNUP'] = 'true'
os.environ['SCRAPER_SERVICE_TOKEN'] = 'test-service-token'
os.environ['DAILY_SCRAPE_ENABLED'] = 'false'
os.environ['DIGEST_ENABLED'] = 'false'
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(FOLDER.name) / 'oauth.db')
os.environ.pop('GOOGLE_CLIENT_ID', None)
os.environ.pop('GOOGLE_CLIENT_SECRET', None)

from main import app


def _set_cookie_values(response, name: str):
    """Read Set-Cookie values without httpx jar CookieConflict (domain '' vs testserver.local)."""
    headers = response.headers
    if hasattr(headers, 'get_list'):
        lines = headers.get_list('set-cookie')
    else:
        lines = [v for k, v in headers.multi_items() if k.lower() == 'set-cookie']
    values = []
    for line in lines:
        match = re.match(rf'(?i){re.escape(name)}=([^;]*)', line.strip())
        if match:
            values.append(match.group(1))
    return values


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'http://127.0.0.1:3000'})

    def test_unconfigured_start_is_unavailable(self):
        self.client.cookies.set('oauth_state', 'stale-start-state')
        result = self.client.get('/api/v1/auth/oauth/google', follow_redirects=False)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()['error']['code'], 'unavailable')
        # Unconfigured start clears leftover oauth_state (parity with callback failure paths).
        self.assertIn('oauth_state', result.headers.get('set-cookie', '').lower())

    def test_callback_rejects_bad_state(self):
        result = self.client.get('/api/v1/auth/oauth/google/callback?code=abc&state=nope', follow_redirects=False)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()['error']['code'], 'unavailable')

    def test_callback_unconfigured_is_unavailable_even_with_state_cookie(self):
        # Stale oauth_state after credentials were removed must not KeyError → 500.
        self.client.cookies.set('oauth_state', 'stale-state-token')
        result = self.client.get(
            '/api/v1/auth/oauth/google/callback?code=abc&state=stale-state-token',
            follow_redirects=False,
        )
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()['error']['code'], 'unavailable')
        # Failure paths clear leftover oauth_state so the next start is clean.
        self.assertIn('oauth_state', result.headers.get('set-cookie', '').lower())

    def test_callback_denied_redirects_without_secrets(self):
        self.client.cookies.set('oauth_state', 'stale-state-token')
        result = self.client.get('/api/v1/auth/oauth/google/callback?error=access_denied', follow_redirects=False)
        self.assertEqual(result.status_code, 302)
        self.assertIn('oauth=denied', result.headers['location'])
        self.assertIn('oauth_state', result.headers.get('set-cookie', '').lower())

    def test_default_redirect_uri_uses_frontend_base(self):
        from services.oauth_service import redirect_uri

        with patch.dict(
            os.environ,
            {
                'PUBLIC_FRONTEND_BASE': 'http://127.0.0.1:3000',
                'PUBLIC_API_BASE': 'http://127.0.0.1:8000',
            },
            clear=False,
        ):
            os.environ.pop('GOOGLE_REDIRECT_URI', None)
            self.assertEqual(
                redirect_uri(),
                'http://127.0.0.1:3000/api/v1/auth/oauth/google/callback',
            )
        with patch.dict(os.environ, {'GOOGLE_REDIRECT_URI': 'https://app.example/oauth/cb'}, clear=False):
            self.assertEqual(redirect_uri(), 'https://app.example/oauth/cb')
        # Whitespace-only override must not stick; fall back to the BFF callback.
        with patch.dict(
            os.environ,
            {
                'PUBLIC_FRONTEND_BASE': 'http://127.0.0.1:3000',
                'GOOGLE_REDIRECT_URI': '   ',
            },
            clear=False,
        ):
            self.assertEqual(
                redirect_uri(),
                'http://127.0.0.1:3000/api/v1/auth/oauth/google/callback',
            )
        # Padded / whitespace-only PUBLIC_FRONTEND_BASE must strip like digest BFF preference.
        with patch.dict(
            os.environ,
            {
                'PUBLIC_FRONTEND_BASE': '  http://portal.test/  ',
                'GOOGLE_REDIRECT_URI': '',
            },
            clear=False,
        ):
            os.environ.pop('GOOGLE_REDIRECT_URI', None)
            self.assertEqual(
                redirect_uri(),
                'http://portal.test/api/v1/auth/oauth/google/callback',
            )
        with patch.dict(
            os.environ,
            {
                'PUBLIC_FRONTEND_BASE': '   ',
                'GOOGLE_REDIRECT_URI': '',
            },
            clear=False,
        ):
            os.environ.pop('GOOGLE_REDIRECT_URI', None)
            self.assertEqual(
                redirect_uri(),
                'http://127.0.0.1:3000/api/v1/auth/oauth/google/callback',
            )

    def test_start_redirects_when_configured(self):
        with patch.dict(os.environ, {'GOOGLE_CLIENT_ID': 'cid.apps.googleusercontent.com', 'GOOGLE_CLIENT_SECRET': 'secret'}):
            config = self.client.get('/api/v1/config')
            self.assertTrue(config.json()['oauth_google'])
            result = self.client.get('/api/v1/auth/oauth/google', follow_redirects=False)
            self.assertEqual(result.status_code, 302)
            self.assertIn('accounts.google.com', result.headers['location'])
            # Authorize URL must target the frontend BFF callback by default (cookie host).
            self.assertIn('redirect_uri=http%3A%2F%2F127.0.0.1%3A3000%2Fapi%2Fv1%2Fauth%2Foauth%2Fgoogle%2Fcallback', result.headers['location'])
            cookie = result.headers.get('set-cookie', '')
            self.assertIn('oauth_state', cookie)
            self.assertRegex(cookie, r'(?i)httponly')
            self.assertRegex(cookie, r'(?i)samesite=lax')
            with patch.dict(os.environ, {'APP_ENV': 'production', 'GOOGLE_CLIENT_ID': 'cid.apps.googleusercontent.com', 'GOOGLE_CLIENT_SECRET': 'secret'}):
                prod = self.client.get('/api/v1/auth/oauth/google', follow_redirects=False)
                self.assertEqual(prod.status_code, 302)
                prod_cookie = prod.headers.get('set-cookie', '')
                self.assertRegex(prod_cookie, r'(?i);\s*secure')
                self.assertRegex(prod_cookie, r'(?i)samesite=lax')
                self.assertRegex(prod_cookie, r'(?i)httponly')
            # Bad state while configured redirects to /live?oauth=failed (not a raw JSON page).
            bad = self.client.get('/api/v1/auth/oauth/google/callback?code=abc&state=nope', follow_redirects=False)
            self.assertEqual(bad.status_code, 302)
            self.assertIn('oauth=failed', bad.headers['location'])
            self.assertIn('oauth_state', bad.headers.get('set-cookie', '').lower())
            # Provider/account OAuthError maps to the demo shell instead of a raw JSON page.
            from services.oauth_service import OAuthError

            with patch('routers.auth.exchange_code', side_effect=OAuthError('Google rejected the sign-in request.', 401)):
                self.client.cookies.set('oauth_state', 'good-state')
                failed = self.client.get(
                    '/api/v1/auth/oauth/google/callback?code=abc&state=good-state',
                    follow_redirects=False,
                )
            self.assertEqual(failed.status_code, 302)
            self.assertIn('oauth=failed', failed.headers['location'])
            self.assertIn('oauth_state', failed.headers.get('set-cookie', '').lower())
        # Outside the configured patch, start stays unavailable and config stays false.
        disabled = self.client.get('/api/v1/config')
        self.assertFalse(disabled.json()['oauth_google'])
        self.assertEqual(self.client.get('/api/v1/auth/oauth/google', follow_redirects=False).status_code, 503)

    def test_callback_shares_login_ip_throttle(self):
        """AUTH-01: configured Google callback uses the same login-ip budget as password login."""
        import time

        from database import Base, SessionLocal, engine
        from portal_models import Throttle
        from security import digest

        Base.metadata.create_all(engine)
        # Dedicated peer so filling this bucket cannot 429 later OAuthTests on testclient.
        peer = 'oauth-login-ip-throttle'
        bucket = digest('login-ip:' + peer) + ':' + str(int(time.time()) // 300)
        with SessionLocal() as db:
            row = db.get(Throttle, bucket)
            if row:
                row.count = 30
            else:
                db.add(Throttle(key=bucket, count=30))
            db.commit()
        with patch.dict(
            os.environ,
            {'GOOGLE_CLIENT_ID': 'cid.apps.googleusercontent.com', 'GOOGLE_CLIENT_SECRET': 'secret'},
        ), patch('routers.auth.client_host', return_value=peer):
            self.client.cookies.set('oauth_state', 'throttle-state', domain='testserver.local', path='/')
            blocked = self.client.get(
                '/api/v1/auth/oauth/google/callback?code=abc&state=throttle-state',
                follow_redirects=False,
            )
        # Browser callback — throttle maps to /live?oauth=failed (not a raw JSON 429 page).
        self.assertEqual(blocked.status_code, 302)
        self.assertIn('oauth=failed', blocked.headers['location'])
        self.assertIn('oauth_state', blocked.headers.get('set-cookie', '').lower())
        oauth_values = _set_cookie_values(blocked, 'oauth_state')
        self.assertEqual(len(oauth_values), 1, oauth_values)
        self.assertIn(oauth_values[0], ('', '""'))

    def test_callback_success_rotates_presented_session(self):
        from database import Base, SessionLocal, engine
        from services.oauth_service import issue_session
        from portal_models import Account, LoginSession
        from security import digest, password_hash

        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            account = db.query(Account).filter_by(email='oauth-rotate@example.com').first()
            if not account:
                account = Account(
                    email='oauth-rotate@example.com',
                    name='OAuth Rotate',
                    password_hash=password_hash('Testing-strong-password'),
                )
                db.add(account)
                db.flush()
            prior = issue_session(db, account)
            account_id = account.id
        # Plant prior cookies on the TestClient host so the jar does not keep a domain='' twin.
        self.client.cookies.set('care_session', prior, domain='testserver.local', path='/')
        self.client.cookies.set('oauth_state', 'rotate-state', domain='testserver.local', path='/')
        with patch.dict(
            os.environ,
            {'GOOGLE_CLIENT_ID': 'cid.apps.googleusercontent.com', 'GOOGLE_CLIENT_SECRET': 'secret'},
        ), patch(
            'routers.auth.exchange_code',
            return_value={'email': 'oauth-rotate@example.com', 'name': 'OAuth Rotate', 'subject': 'google-rotate-1'},
        ), patch(
            'routers.auth.upsert_account',
            side_effect=lambda db, identity, allow: db.query(Account).filter_by(id=account_id).one(),
        ):
            result = self.client.get(
                '/api/v1/auth/oauth/google/callback?code=abc&state=rotate-state',
                follow_redirects=False,
            )
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.headers['location'].endswith('/live'))
        # Production sets one care_session and clears oauth_state (no duplicate care_session Set-Cookie).
        care_values = _set_cookie_values(result, 'care_session')
        oauth_values = _set_cookie_values(result, 'oauth_state')
        self.assertEqual(len(care_values), 1, care_values)
        self.assertEqual(len(oauth_values), 1, oauth_values)
        nxt = care_values[0]
        self.assertTrue(nxt)
        self.assertNotEqual(prior, nxt)
        self.assertIn(oauth_values[0], ('', '""'))
        with SessionLocal() as db:
            self.assertIsNone(db.get(LoginSession, digest(prior)))
            self.assertIsNotNone(db.get(LoginSession, digest(nxt)))

    def test_upsert_stores_google_subject(self):
        from database import Base, SessionLocal, engine
        from services.oauth_service import upsert_account
        from portal_models import Account
        from security import password_hash
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            if not db.query(Account).first():
                db.add(Account(email='seed@example.com', name='Seed', password_hash=password_hash('Testing-strong-password')))
                db.commit()
            created = upsert_account(db, {'email': 'gp@example.com', 'name': 'Dr GP', 'subject': 'google-sub-1'}, True)
            db.commit()
            stored = db.query(Account).filter_by(email='gp@example.com').one()
            self.assertEqual(stored.id, created.id)
            self.assertEqual(stored.identity_issuer, 'https://accounts.google.com')
            self.assertEqual(stored.identity_subject, 'google-sub-1')
            again = upsert_account(db, {'email': 'other@example.com', 'name': 'Other', 'subject': 'google-sub-1'}, True)
            self.assertEqual(again.id, stored.id)

    def test_upsert_rejects_subject_mismatch_on_same_email(self):
        from database import Base, SessionLocal, engine
        from services.oauth_service import upsert_account, OAuthError
        from portal_models import Account
        from security import password_hash
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            if not db.query(Account).first():
                db.add(Account(email='seed@example.com', name='Seed', password_hash=password_hash('Testing-strong-password')))
                db.commit()
            first = upsert_account(db, {'email': 'linked@example.com', 'name': 'Linked', 'subject': 'google-sub-a'}, True)
            db.commit()
            self.assertEqual(first.identity_subject, 'google-sub-a')
            with self.assertRaises(OAuthError) as raised:
                upsert_account(db, {'email': 'linked@example.com', 'name': 'Intruder', 'subject': 'google-sub-b'}, True)
            self.assertEqual(raised.exception.status_code, 401)
            stored = db.query(Account).filter_by(email='linked@example.com').one()
            self.assertEqual(stored.identity_subject, 'google-sub-a')


if __name__ == '__main__':
    unittest.main()


class GoogleIdentityClaimsTests(unittest.TestCase):
    def exchange(self, changes):
        import httpx
        from services.oauth_service import exchange_code
        claims = {'aud': 'test-client', 'iss': 'https://accounts.google.com',
                  'email': 'Doctor@example.com', 'email_verified': True, 'sub': 'google-subject'}
        claims.update(changes)
        def respond(request):
            return httpx.Response(200, json=claims if request.url.path == '/tokeninfo' else {'id_token': 'test-token'})
        with patch.dict(os.environ, {'GOOGLE_CLIENT_ID': 'test-client', 'GOOGLE_CLIENT_SECRET': 'test-secret'}), httpx.Client(transport=httpx.MockTransport(respond)) as client:
            return exchange_code('test-code', client)

    def test_requires_explicit_verified_email(self):
        from services.oauth_service import OAuthError
        for value in (None, False, 'false', '', 1, 'TRUE'):
            with self.subTest(value=value), self.assertRaises(OAuthError) as raised:
                self.exchange({'email_verified': value})
            self.assertEqual(raised.exception.status_code, 401)
        for value in (True, 'true'):
            self.assertEqual(self.exchange({'email_verified': value})['email'], 'doctor@example.com')

    def test_requires_nonempty_untruncated_subject(self):
        from services.oauth_service import OAuthError
        for value in (None, '', '   ', 123, 'x' * 201):
            with self.subTest(value=value), self.assertRaises(OAuthError) as raised:
                self.exchange({'sub': value})
            self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(self.exchange({'sub': 'stable-subject'})['subject'], 'stable-subject')
