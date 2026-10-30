import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from main import app
from domain.config import today
from database import Base, get_db
from portal_models import Account, Course, fill_course
from security import password_hash

PASSWORD = 'Testing-strong-password'
HASH = password_hash(PASSWORD)


def sample(title='Upcoming GP CPD', start='2099-06-15', city='Kuala Lumpur'):
    quote = f'{title} by Learning Institute in Malaysia {city}. {start}. CPD points 2.'
    return {
        'title': title,
        'provider': 'Learning Institute',
        'mode': 'in_person',
        'country': 'MY',
        'start_date': start,
        'city': city,
        'fee': 350,
        'currency': 'MYR',
        'source_url': 'https://example.org/upcoming',
        'source_text': quote,
        'points': 2,
        'credit_label': 'CPD',
        'evidence': {key: quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'city', 'points', 'credit_label']},
    }


class DigestCertificateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.folder.name + '/test.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        def dependency():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = dependency
        self.env = patch.dict(os.environ, {
            'APP_ENV': 'test',
            'DEMO_MODE': 'false',
            'SCRAPER_SERVICE_TOKEN': 'test-service-token',
            'ALLOW_SIGNUP': 'true',
            'DAILY_SCRAPE_ENABLED': 'false',
            'DIGEST_ENABLED': 'false',
            'MAIL_PROVIDER': 'log',
            'DIGEST_LOG_DIR': self.folder.name + '/digests',
            # Unsubscribe links prefer the public Next BFF host (portal /api/v1 proxy).
            'PUBLIC_FRONTEND_BASE': 'http://portal.test',
            'PUBLIC_API_BASE': 'http://api-direct.test',
        })
        self.env.start()
        availability = patch('services.preference_service.digest_available', return_value=True)
        availability.start(); self.addCleanup(availability.stop)
        self.client = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'http://127.0.0.1:3000'})
        with self.Session() as db:
            doc = Account(email='doc@example.com', name='Doctor Dig', password_hash=HASH, city='Kuala Lumpur')
            op = Account(email='op@example.com', name='Operator', password_hash=HASH, role='operator')
            course = fill_course(Course(source_key='upcoming'), sample())
            db.add_all([doc, op, course])
            db.commit()
            self.doc_id = doc.id
            self.course_id = course.id
        self.client.post('/api/v1/auth/login', json={'email': 'doc@example.com', 'password': PASSWORD})

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.env.stop()
        self.engine.dispose()
        self.folder.cleanup()

    def test_suggestions_prefer_city(self):
        result = self.client.get('/api/v1/me/suggestions')
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertTrue(body['items'])
        self.assertEqual(body['items'][0]['city'], 'Kuala Lumpur')
        self.assertIn('advisory', body)
        with self.Session() as db:
            hidden = fill_course(Course(source_key='cancelled-upcoming'), sample('Cancelled GP', start='2099-07-01'))
            hidden.publication_status = 'cancelled'
            hidden.cancellation_status = 'cancelled'
            db.add(hidden)
            db.commit()
        skipped = self.client.get('/api/v1/me/suggestions').json()
        self.assertFalse(any(item['title'] == 'Cancelled GP' for item in skipped['items']))

    def test_suggestions_prefer_recent_mode(self):
        from portal_models import Record
        with self.Session() as db:
            online = fill_course(Course(source_key='kl-online'), sample('KL online CME', start='2099-08-01', city='Kuala Lumpur'))
            online.mode = 'online'
            online.data = {**online.data, 'mode': 'online'}
            later_city = fill_course(Course(source_key='kl-later-inperson'), sample('Later KL workshop', start='2099-09-01', city='Kuala Lumpur'))
            attended = fill_course(Course(source_key='past-online'), sample('Past webinar', start='2020-01-01', city='Penang'))
            attended.mode = 'online'
            attended.data = {**attended.data, 'mode': 'online'}
            db.add_all([online, later_city, attended])
            db.commit()
            db.add(Record(account_id=self.doc_id, course_id=attended.id, attended=True, attendance_status='attended', attended_on='2020-01-01'))
            db.commit()
        body = self.client.get('/api/v1/me/suggestions').json()
        self.assertEqual(body['preferred_mode'], 'online')
        self.assertEqual(body['items'][0]['title'], 'KL online CME')
        self.assertEqual(body['items'][0]['reason'], 'Matches your city and recent learning mode')

    def test_suggestions_skip_status_attended_without_bool(self):
        """PROG-02 must honour attendance_status even if the legacy attended bool drifted."""
        from portal_models import Record
        with self.Session() as db:
            listed = db.get(Course, self.course_id)
            listed.title = 'Status-attended session'
            db.add(
                Record(
                    account_id=self.doc_id,
                    course_id=self.course_id,
                    attended=False,
                    attendance_status='attended',
                    attended_on='2099-06-15',
                )
            )
            db.commit()
        body = self.client.get('/api/v1/me/suggestions').json()
        self.assertFalse(any(item['id'] == self.course_id for item in body['items']))

    def test_suggestions_skip_status_signed_up_without_bool(self):
        """PROG-02 must honour signup_status even if the legacy signed_up bool drifted."""
        from portal_models import Record
        with self.Session() as db:
            listed = db.get(Course, self.course_id)
            listed.title = 'Status-signed session'
            db.add(
                Record(
                    account_id=self.doc_id,
                    course_id=self.course_id,
                    signed_up=False,
                    signup_status='signed_up',
                    signed_up_at=1,
                )
            )
            db.commit()
        body = self.client.get('/api/v1/me/suggestions').json()
        self.assertFalse(any(item['id'] == self.course_id for item in body['items']))

    def test_suggestions_do_not_skip_cancelled_when_bool_drifts(self):
        """Cancelled sign-up must not stay in the signed-up skip set if legacy signed_up bool drifted."""
        from portal_models import Record
        with self.Session() as db:
            listed = db.get(Course, self.course_id)
            listed.title = 'Cancelled-but-bool session'
            db.add(
                Record(
                    account_id=self.doc_id,
                    course_id=self.course_id,
                    signed_up=True,
                    signup_status='cancelled',
                    signed_up_at=1,
                )
            )
            db.commit()
        body = self.client.get('/api/v1/me/suggestions').json()
        self.assertTrue(any(item['id'] == self.course_id for item in body['items']), body)

    def test_suggestions_strip_whitespace_city_and_ignore_junk_mode(self):
        from portal_models import Account, Record
        from services.suggestion_service import suggestions_for

        with self.Session() as db:
            account = db.get(Account, self.doc_id)
            account.city = '  Kuala Lumpur  '
            junk = fill_course(Course(source_key='junk-mode-past'), sample('Junk mode past', start='2020-02-01', city='Penang'))
            junk.mode = 'webinar'
            junk.data = {**(junk.data or {}), 'mode': 'webinar'}
            db.add(junk)
            db.flush()
            db.add(
                Record(
                    account_id=self.doc_id,
                    course_id=junk.id,
                    attended=True,
                    attendance_status='attended',
                    attended_on='2020-02-01',
                )
            )
            db.commit()
            body = suggestions_for(db, account, limit=5)
        self.assertEqual(body['city'], 'Kuala Lumpur')
        self.assertIsNone(body['preferred_mode'])
        self.assertTrue(body['items'])
        self.assertEqual(body['items'][0]['city'], 'Kuala Lumpur')

    def test_suggestions_prefer_most_recent_mode_not_majority(self):
        """PROG-02 preferred_mode is the latest attended delivery mode, not the majority."""
        from portal_models import Account, Record
        from services.suggestion_service import suggestions_for

        with self.Session() as db:
            account = db.get(Account, self.doc_id)
            older_a = fill_course(Course(source_key='past-ip-a'), sample('Past IP A', start='2019-01-01', city='Penang'))
            older_b = fill_course(Course(source_key='past-ip-b'), sample('Past IP B', start='2019-06-01', city='Penang'))
            newest = fill_course(Course(source_key='past-online-new'), sample('Past online', start='2021-01-01', city='Penang'))
            newest.mode = 'online'
            newest.data = {**(newest.data or {}), 'mode': 'online'}
            upcoming_online = fill_course(
                Course(source_key='kl-online-recent'),
                sample('KL online recent mode', start='2099-08-01', city='Kuala Lumpur'),
            )
            upcoming_online.mode = 'online'
            upcoming_online.data = {**(upcoming_online.data or {}), 'mode': 'online'}
            upcoming_ip = fill_course(
                Course(source_key='kl-ip-majority'),
                sample('KL in-person majority', start='2099-07-01', city='Kuala Lumpur'),
            )
            db.add_all([older_a, older_b, newest, upcoming_online, upcoming_ip])
            db.flush()
            db.add_all([
                Record(
                    account_id=self.doc_id, course_id=older_a.id, attended=True,
                    attendance_status='attended', attended_on='2019-01-15',
                ),
                Record(
                    account_id=self.doc_id, course_id=older_b.id, attended=True,
                    attendance_status='attended', attended_on='2019-06-15',
                ),
                Record(
                    account_id=self.doc_id, course_id=newest.id, attended=True,
                    attendance_status='attended', attended_on='2021-01-15',
                ),
            ])
            db.commit()
            body = suggestions_for(db, account, limit=5)
        self.assertEqual(body['preferred_mode'], 'online')
        self.assertEqual(body['items'][0]['title'], 'KL online recent mode')

    def test_suggestions_match_padded_catalogue_city(self):
        from portal_models import Account
        from services.suggestion_service import suggestions_for

        with self.Session() as db:
            account = db.get(Account, self.doc_id)
            account.city = 'Kuala Lumpur'
            listed = db.get(Course, self.course_id)
            listed.city = '  Kuala Lumpur  '
            listed.data = {**(listed.data or {}), 'city': '  Kuala Lumpur  '}
            db.commit()
            body = suggestions_for(db, account, limit=5)
        self.assertTrue(body['items'])
        self.assertEqual(body['items'][0]['reason'], 'Matches your city')

    def test_suggestions_city_case_insensitive(self):
        """Catalogue city casing from extraction must still match the profile city."""
        from portal_models import Account
        from services.suggestion_service import suggestions_for

        with self.Session() as db:
            account = db.get(Account, self.doc_id)
            account.city = 'Kuala Lumpur'
            listed = db.get(Course, self.course_id)
            listed.city = 'kuala lumpur'
            listed.data = {**(listed.data or {}), 'city': 'kuala lumpur'}
            elsewhere = fill_course(
                Course(source_key='penang-case'),
                sample('Penang case session', start='2099-07-15', city='Penang'),
            )
            db.add(elsewhere)
            db.commit()
            body = suggestions_for(db, account, limit=5)
        self.assertEqual(body['city'], 'Kuala Lumpur')
        self.assertTrue(body['items'])
        self.assertEqual(body['items'][0]['reason'], 'Matches your city')
        self.assertEqual((body['items'][0]['city'] or '').casefold(), 'kuala lumpur')

    def test_suggestions_skip_before_limit_keeps_later_city(self):
        """Signed-up same-city rows must not empty the city bucket via post-LIMIT skip."""
        from portal_models import Account, Record
        from services.suggestion_service import suggestions_for

        with self.Session() as db:
            account = db.get(Account, self.doc_id)
            account.city = 'Kuala Lumpur'
            # Sign up the fixture KL row plus enough earlier same-city rows to fill city LIMIT.
            db.add(
                Record(
                    account_id=self.doc_id,
                    course_id=self.course_id,
                    signed_up=True,
                    signup_status='signed_up',
                    signed_up_at=1,
                )
            )
            for i in range(4):
                early = fill_course(
                    Course(source_key=f'kl-early-{i}'),
                    sample(f'Early KL {i}', start=f'2099-06-{10 + i:02d}', city='Kuala Lumpur'),
                )
                db.add(early)
                db.flush()
                db.add(
                    Record(
                        account_id=self.doc_id,
                        course_id=early.id,
                        signed_up=True,
                        signup_status='signed_up',
                        signed_up_at=1,
                    )
                )
            later = fill_course(
                Course(source_key='kl-later-unsinged'),
                sample('Later KL keep', start='2099-08-01', city='Kuala Lumpur'),
            )
            other = fill_course(
                Course(source_key='jb-other-city'),
                sample('Johor other', start='2099-07-01', city='Johor Bahru'),
            )
            db.add_all([later, other])
            db.commit()
            body = suggestions_for(db, account, limit=2)
        self.assertTrue(any(item['title'] == 'Later KL keep' for item in body['items']), body)
        self.assertEqual(body['items'][0]['title'], 'Later KL keep')
        self.assertEqual(body['items'][0]['reason'], 'Matches your city')
        self.assertFalse(any(item['title'] == 'Johor other' for item in body['items'][:1]))

    def test_digest_price_label_does_not_invent_myr(self):
        from services.digest_service import upcoming_sessions
        with self.Session() as db:
            bare = fill_course(Course(source_key='fee-no-currency'), sample('Fee only', start='2099-10-01'))
            bare.fee = 120
            bare.currency = None
            bare.data = {**(bare.data or {}), 'fee': 120, 'currency': None}
            db.add(bare)
            # Whitespace-only currency must not render as a fake code (NTF-01 fee honesty).
            padded = fill_course(Course(source_key='fee-ws-currency'), sample('Fee whitespace currency', start='2099-10-02'))
            padded.fee = 90
            padded.currency = '   '
            padded.data = {**(padded.data or {}), 'fee': 90, 'currency': '   '}
            db.add(padded)
            trimmed = fill_course(Course(source_key='fee-pad-myr'), sample('Fee padded MYR', start='2099-10-03'))
            trimmed.fee = 80
            trimmed.currency = ' MYR '
            trimmed.data = {**(trimmed.data or {}), 'fee': 80, 'currency': ' MYR '}
            db.add(trimmed)
            db.commit()
            rows = upcoming_sessions(db, 'Kuala Lumpur', limit=20)
        match = next(item for item in rows if item['title'] == 'Fee only')
        self.assertIn('currency unknown', match['price_label'])
        self.assertNotIn('MYR', match['price_label'])
        ws = next(item for item in rows if item['title'] == 'Fee whitespace currency')
        self.assertIn('currency unknown', ws['price_label'])
        self.assertIsNone(ws['currency'])
        myr = next(item for item in rows if item['title'] == 'Fee padded MYR')
        self.assertEqual(myr['currency'], 'MYR')
        self.assertEqual(myr['price_label'], '80 MYR')

    def test_digest_opt_in_and_send(self):
        got = self.client.get('/api/v1/me/digest')
        self.assertEqual(got.status_code, 200)
        self.assertFalse(got.json()['opted_in'])
        patched = self.client.patch('/api/v1/me/digest', json={'opted_in': True, 'cadence_days': 14})
        self.assertEqual(patched.status_code, 200)
        self.assertTrue(patched.json()['opted_in'])
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': PASSWORD})
        run = self.client.post('/api/v1/admin/digests/run')
        self.assertEqual(run.status_code, 200, run.text)
        self.assertEqual(run.json()['sent'], 1)
        from portal_models import DigestSend
        with self.Session() as db:
            send = db.query(DigestSend).one()
            self.assertGreaterEqual(send.event_count, 1)
            self.assertEqual(send.recorded_points_snapshot, 0)
        # Cadence: a second immediate run must not re-send while still opted in.
        again = self.client.post('/api/v1/admin/digests/run')
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()['sent'], 0)
        logs = list(Path(self.folder.name, 'digests').glob('*.txt'))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text()
        self.assertIn('Upcoming catalogue sessions', text)
        self.assertIn('350 MYR', text)
        self.assertIn('http://portal.test/api/v1/digest/unsubscribe?token=', text)
        self.assertNotIn('http://api-direct.test/api/v1/digest/unsubscribe', text)
        html_logs = list(Path(self.folder.name, 'digests').glob('*.html'))
        self.assertEqual(len(html_logs), 1)
        html = html_logs[0].read_text()
        self.assertIn('<a href=', html)
        self.assertIn('http://portal.test/api/v1/digest/unsubscribe?token=', html)
        self.assertIn('Upcoming catalogue sessions', html)
        with self.Session() as db:
            self.assertEqual(db.query(DigestSend).count(), 1)

    def test_digest_unsubscribe_falls_back_to_public_api_base(self):
        """API-direct demos without PUBLIC_FRONTEND_BASE still get a working unsubscribe host."""
        from services.digest_service import run_due_digests
        from portal_models import DigestPreference

        self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            pref.last_sent_at = None
            db.commit()
        with patch.dict(os.environ, {'PUBLIC_FRONTEND_BASE': '', 'PUBLIC_API_BASE': 'http://api-only.test'}):
            with self.Session() as db:
                result = run_due_digests(db, now=time.time())
        self.assertEqual(result['sent'], 1)
        text = next(Path(self.folder.name, 'digests').glob('*.txt')).read_text()
        self.assertIn('http://api-only.test/api/v1/digest/unsubscribe?token=', text)

    def test_digest_unsubscribe_whitespace_frontend_base_falls_back(self):
        """Whitespace-only PUBLIC_FRONTEND_BASE must not invent a blank host (parity with OAuth strip)."""
        from services.digest_service import run_due_digests
        from portal_models import DigestPreference

        self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            pref.last_sent_at = None
            db.commit()
        with patch.dict(os.environ, {'PUBLIC_FRONTEND_BASE': '   ', 'PUBLIC_API_BASE': 'http://api-ws.test'}):
            with self.Session() as db:
                result = run_due_digests(db, now=time.time())
        self.assertEqual(result['sent'], 1)
        text = next(Path(self.folder.name, 'digests').glob('*.txt')).read_text()
        self.assertIn('http://api-ws.test/api/v1/digest/unsubscribe?token=', text)
        self.assertNotIn('http://   /api/v1/digest/unsubscribe', text)

    def test_digest_cadence_persists_when_opt_in_omits_cadence(self):
        custom = self.client.patch('/api/v1/me/digest', json={'opted_in': True, 'cadence_days': 30})
        self.assertEqual(custom.status_code, 200, custom.text)
        self.assertEqual(custom.json()['cadence_days'], 30)
        # Toggle without cadence_days must not wipe the stored NTF-01 preference.
        toggled = self.client.patch('/api/v1/me/digest', json={'opted_in': False})
        self.assertEqual(toggled.status_code, 200, toggled.text)
        self.assertFalse(toggled.json()['opted_in'])
        self.assertEqual(toggled.json()['cadence_days'], 30)
        again = self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertTrue(again.json()['opted_in'])
        self.assertEqual(again.json()['cadence_days'], 30)
        got = self.client.get('/api/v1/me/digest')
        self.assertEqual(got.json()['cadence_days'], 30)

    def test_unsubscribe_without_login(self):
        self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        from portal_models import DigestPreference
        with self.Session() as db:
            token = db.get(DigestPreference, self.doc_id).unsubscribe_token
        bare = TestClient(app)
        html = bare.get('/api/v1/digest/unsubscribe', params={'token': token})
        self.assertEqual(html.status_code, 200)
        self.assertIn('text/html', html.headers.get('content-type', ''))
        self.assertIn('You are unsubscribed', html.text)
        self.client.post('/api/v1/auth/login', json={'email': 'doc@example.com', 'password': PASSWORD})
        self.assertFalse(self.client.get('/api/v1/me/digest').json()['opted_in'])
        json_again = TestClient(app).get(
            '/api/v1/digest/unsubscribe',
            params={'token': token},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(json_again.status_code, 200)
        self.assertFalse(json_again.json()['opted_in'])

    def test_unsubscribe_blank_and_unknown_token_html(self):
        bare = TestClient(app)
        missing = bare.get('/api/v1/digest/unsubscribe')
        self.assertEqual(missing.status_code, 404)
        self.assertIn('text/html', missing.headers.get('content-type', ''))
        self.assertIn('Unsubscribe link invalid', missing.text)
        blank = bare.get('/api/v1/digest/unsubscribe', params={'token': '   '})
        self.assertEqual(blank.status_code, 404)
        self.assertIn('Unsubscribe link invalid', blank.text)
        unknown = bare.get('/api/v1/digest/unsubscribe', params={'token': 'not-a-token'})
        self.assertEqual(unknown.status_code, 404)
        self.assertIn('Unsubscribe link invalid', unknown.text)
        json_blank = bare.get(
            '/api/v1/digest/unsubscribe',
            params={'token': ''},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(json_blank.status_code, 404)
        self.assertEqual(json_blank.json()['error']['code'], 'not_found')

    def test_digest_html_escapes_catalogue_fields(self):
        from services.digest_service import compose_digest, render_html, render_text
        from portal_models import Account, Course, fill_course

        with self.Session() as db:
            account = db.get(Account, self.doc_id)
            account.name = 'Dr <Script>'
            nasty = fill_course(
                Course(source_key='xss-upcoming'),
                sample(title='GP <b>Bold</b>', start='2099-11-01', city='Kuala Lumpur'),
            )
            nasty.provider = 'Inst & Co'
            nasty.data = {**(nasty.data or {}), 'provider': 'Inst & Co'}
            db.add(nasty)
            db.commit()
            payload = compose_digest(db, account)
        html = render_html(payload, 'http://example.test/unsub?token=abc')
        self.assertIn('Dr &lt;Script&gt;', html)
        self.assertIn('GP &lt;b&gt;Bold&lt;/b&gt;', html)
        self.assertIn('Inst &amp; Co', html)
        self.assertNotIn('<Script>', html)
        self.assertIn('Unsubscribe: http://example.test/unsub?token=abc', render_text(payload, 'http://example.test/unsub?token=abc'))

    def test_digest_plain_html_name_and_place_parity(self):
        from services.digest_service import render_html, render_text

        for blank in (None, '', '   '):
            payload = {
                'name': blank,
                'progress': {'year': 2026, 'points': 0, 'attended': 0, 'signed_up': 0, 'excluded': 0},
                'sessions': [{
                    'start_date': '2099-12-01',
                    'title': 'Place-free GP',
                    'provider': 'Institute',
                    'city': None,
                    'mode': None,
                    'price_label': 'Free',
                    'points': None,
                    'credit_label': None,
                }],
            }
            text = render_text(payload, 'http://example.test/unsub')
            html = render_html(payload, 'http://example.test/unsub')
            self.assertIn('Hi Doctor,', text)
            self.assertNotIn('Hi None,', text)
            self.assertIn('Hi Doctor,', html)
            self.assertIn('location unknown', text)
            self.assertIn('location unknown', html)

    def test_digest_failure_uses_bounded_backoff(self):
        self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': PASSWORD})
        with patch('services.digest_service.send_via_provider', return_value={'status': 'failed', 'provider_message_id': None, 'error': 'SMTP down'}):
            first = self.client.post('/api/v1/admin/digests/run')
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()['failed'], 1)
            second = self.client.post('/api/v1/admin/digests/run')
            self.assertEqual(second.json()['failed'], 0)
            self.assertEqual(second.json()['sent'], 0)
        from services.digest_service import backoff_seconds
        from portal_models import DigestPreference
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            self.assertEqual(pref.fail_count, 1)
            self.assertGreater(pref.next_retry_at, time.time())
            self.assertEqual(backoff_seconds(1), 15 * 60)
            self.assertEqual(backoff_seconds(8), 24 * 3600)
            pref.next_retry_at = time.time() - 1
            db.commit()
        with patch('services.digest_service.send_via_provider', return_value={'status': 'failed', 'provider_message_id': None, 'error': 'SMTP down'}):
            retried = self.client.post('/api/v1/admin/digests/run')
        self.assertEqual(retried.json()['failed'], 1)
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            self.assertEqual(pref.fail_count, 2)

    def test_reopt_in_clears_send_backoff(self):
        self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': PASSWORD})
        with patch('services.digest_service.send_via_provider', return_value={'status': 'failed', 'provider_message_id': None, 'error': 'SMTP down'}):
            failed = self.client.post('/api/v1/admin/digests/run')
            self.assertEqual(failed.json()['failed'], 1)
        self.client.post('/api/v1/auth/login', json={'email': 'doc@example.com', 'password': PASSWORD})
        from portal_models import DigestPreference
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            self.assertGreater(pref.fail_count, 0)
            self.assertIsNotNone(pref.next_retry_at)
            token = pref.unsubscribe_token
        bare = TestClient(app)
        self.assertEqual(bare.get('/api/v1/digest/unsubscribe', params={'token': token}).status_code, 200)
        self.client.post('/api/v1/auth/login', json={'email': 'doc@example.com', 'password': PASSWORD})
        again = self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        self.assertEqual(again.status_code, 200, again.text)
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            self.assertTrue(pref.opted_in)
            self.assertEqual(pref.fail_count, 0)
            self.assertIsNone(pref.next_retry_at)
        # Idempotent opted_in=true while already in must not wipe an active backoff.
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': PASSWORD})
        with patch('services.digest_service.send_via_provider', return_value={'status': 'failed', 'provider_message_id': None, 'error': 'SMTP down'}):
            self.assertEqual(self.client.post('/api/v1/admin/digests/run').json()['failed'], 1)
        self.client.post('/api/v1/auth/login', json={'email': 'doc@example.com', 'password': PASSWORD})
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            fail_count = pref.fail_count
            retry_at = pref.next_retry_at
        keep = self.client.patch('/api/v1/me/digest', json={'opted_in': True})
        self.assertEqual(keep.status_code, 200, keep.text)
        with self.Session() as db:
            pref = db.get(DigestPreference, self.doc_id)
            self.assertEqual(pref.fail_count, fail_count)
            self.assertEqual(pref.next_retry_at, retry_at)

    def test_certificate_issue_and_download(self):
        with self.Session() as db:
            past = fill_course(Course(source_key='past-cme'), sample(title='Past CME', start='2026-01-10', city='Kuala Lumpur'))
            db.add(past)
            db.commit()
            past_id = past.id
        save = self.client.put(
            '/api/v1/me/trainings/' + past_id,
            json={
                'signed_up': True,
                'attended': True,
                'attended_on': '2026-01-15',
                'points': 4,
                'credit_label': 'CPD',
                'notes': '',
                'public': False,
                'version': 0,
            },
        )
        self.assertEqual(save.status_code, 200, save.text)
        issued = self.client.post('/api/v1/me/certificates', json={'year': 2026})
        self.assertEqual(issued.status_code, 201, issued.text)
        body = issued.json()
        self.assertEqual(body['recorded_points_snapshot'], 4)
        self.assertIn('CERT-01', body['disclaimer_version'])
        self.assertEqual(body['download_url'], body['download_path'])
        download = self.client.get(body['pdf_download_url'])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers['content-type'], 'application/pdf')
        disposition = download.headers.get('content-disposition', '')
        self.assertIn('attachment', disposition.lower())
        self.assertIn(f'carecredits-{body["year"]}-', disposition)
        self.assertTrue(download.content.startswith(b'%PDF-1.4'))
        self.assertIn(b'CareCredits', download.content)
        self.assertIn(b'not an MMC', download.content)
        self.assertIn(b'calendar year 2026', download.content)
        self.assertIn(body['document_hash'].encode(), download.content)
        self.assertIn(b'/Title (', download.content)
        self.assertIn(b'/Info 6 0 R', download.content)
        bad_format = self.client.get(body['download_path'].split('?')[0] + '?format=xml')
        self.assertEqual(bad_format.status_code, 422)
        bad_year = self.client.post('/api/v1/me/certificates', json={'year': 1800})
        self.assertEqual(bad_year.status_code, 422)
        # year=0 must not coerce via falsy `or` into the current calendar year.
        zero_year = self.client.post('/api/v1/me/certificates', json={'year': 0})
        self.assertEqual(zero_year.status_code, 422)
        default_year = self.client.post('/api/v1/me/certificates', json={})
        self.assertEqual(default_year.status_code, 201, default_year.text)
        self.assertEqual(default_year.json()['year'], today().year)
        html = self.client.get(body['print_url'])
        self.assertEqual(html.status_code, 200)
        self.assertIn('CareCredits', html.text)
        self.assertIn('not an MMC', html.text)
        self.assertIn('MOH', html.text)
        self.assertIn('APC', html.text)
        # Unicode names fold for Helvetica PDF but remain intact in HTML.
        from types import SimpleNamespace
        from services.certificate_service import _pdf_escape, render_html, render_pdf

        self.assertIn('José', _pdf_escape('José'))
        self.assertNotIn('\u0301', _pdf_escape('José'))
        # Whitespace-only city must not paint a dangling " · " on PDF/HTML.
        blank_city = SimpleNamespace(email='c@example.com', name='  Dr Pad  ', city='   ')
        cert_row = SimpleNamespace(
            year=2026,
            recorded_points_snapshot=1.0,
            issued_at=1700000000.0,
            document_hash='abc',
            disclaimer_version='CERT-01-v1',
            id='certblank1',
        )
        cert_row._identity_snapshot = vars(blank_city)
        html_blank = render_html(blank_city, cert_row)
        self.assertIn('Dr Pad', html_blank)
        self.assertNotIn('·', html_blank.split('calendar year')[1].split('</p>')[0])
        pdf_blank = render_pdf(blank_city, cert_row)
        self.assertIn(b'Dr Pad', pdf_blank)
        self.assertIn(b'calendar year 2026.', pdf_blank)
        self.assertNotIn(b'calendar year 2026 \xb7', pdf_blank)
        # Whitespace-only / blank display name falls back to Doctor on PDF and HTML.
        blank_name = SimpleNamespace(email='n@example.com', name='   ', city='KL')
        cert_row._identity_snapshot = vars(blank_name)
        html_name = render_html(blank_name, cert_row)
        self.assertIn('<strong>Doctor</strong>', html_name)
        self.assertNotIn('<strong>   </strong>', html_name)
        pdf_name = render_pdf(blank_name, cert_row)
        self.assertIn(b'Doctor', pdf_name)
        self.assertIn(b'KL', pdf_name)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': PASSWORD})
        self.assertEqual(self.client.get(body['download_path']).status_code, 404)


if __name__ == '__main__':
    unittest.main()
