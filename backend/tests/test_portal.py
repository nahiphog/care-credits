import os
import secrets
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from main import app, today, migrate_schema
from database import Base, get_db
from portal_models import Account, Audit, Course, Record, Job, Candidate, FieldEvidence, LoginSession, SchemaVersion, SourceDocument, Throttle, fill_course, purge_expired_source_text
from security import digest, password_hash

PASSWORD = 'Testing-strong-password'
HASH = password_hash(PASSWORD)


def sample(title='GP training'):
    quote='GP training by Learning Institute in Malaysia Kuala Lumpur online. 2026-01-01. CPD points 2.'
    return {'title':title, 'provider':'Learning Institute', 'mode':'online', 'country':'MY', 'start_date':'2026-01-01', 'city':None, 'source_url':'https://example.org/course', 'source_text':quote, 'points':2, 'credit_label':'CPD', 'evidence':{key:quote for key in ['title','provider','mode','country','start_date','points','credit_label']}}


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+self.folder.name+'/test.db',connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.Session=sessionmaker(bind=self.engine)
        def dependency():
            with self.Session() as db:
                yield db
        app.dependency_overrides[get_db]=dependency
        self.env=patch.dict(os.environ,{'APP_ENV':'test','DEMO_MODE':'false','SCRAPER_SERVICE_TOKEN':'test-service-token','ALLOW_SIGNUP':'true','DAILY_SCRAPE_ENABLED':'false','DIGEST_ENABLED':'false'})
        self.env.start()
        self.scraper_ready=patch(
            'main._scraper_service_status',
            return_value={'status': 'ready', 'reachable': True, 'tavily_configured': True, 'model_ready': True},
        )
        self.scraper_ready.start()
        self.client=TestClient(app,headers={'X-Care-Client':'1','Origin':'http://127.0.0.1:3000'})
        with self.Session() as db:
            a=Account(email='a@example.com',name='Doctor A',password_hash=HASH,role='operator')
            b=Account(email='b@example.com',name='Doctor B',password_hash=HASH)
            data=sample()
            course=fill_course(Course(source_key='sample'), data)
            db.add_all([a,b,course]);db.commit()
            self.a,self.b,self.course=a.id,b.id,course.id
            self.slug=a.public_slug
        self.login()

    def tearDown(self):
        self.client.close();app.dependency_overrides.clear();self.scraper_ready.stop();self.env.stop();self.engine.dispose();self.folder.cleanup()

    def login(self,email='a@example.com'):
        result=self.client.post('/api/v1/auth/login',json={'email':email,'password':PASSWORD})
        self.assertEqual(result.status_code,200,result.text)
        return result

    def save(self,**updates):
        body={'signed_up':True,'attended':True,'attended_on':today().isoformat(),'points':3,'credit_label':'CPD','notes':'PRIVATE NOTE','public':True,'version':0,**updates}
        return self.client.put('/api/v1/me/trainings/'+self.course,json=body)

    def test_authentication_csrf_and_logout(self):
        cookie = self.login().headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertRegex(cookie, r'(?i)samesite=lax')
        evil=self.client.post('/api/v1/auth/logout',headers={'Origin':'https://evil.example'})
        self.assertEqual(evil.status_code,403)
        evil_body=evil.json()['error']
        self.assertEqual(evil_body['code'],'forbidden')
        self.assertIn('message', evil_body)
        self.assertIn('request_id', evil_body)
        bare=TestClient(app,headers={'X-Care-Client':'1'})
        bare.cookies.update(self.client.cookies)
        bare_denied=bare.post('/api/v1/auth/logout')
        self.assertEqual(bare_denied.status_code,403)
        self.assertEqual(bare_denied.json()['error']['code'],'forbidden')
        no_client=TestClient(app,headers={'Origin':'http://127.0.0.1:3000'})
        no_client.cookies.update(self.client.cookies)
        no_client_denied=no_client.post('/api/v1/auth/logout')
        self.assertEqual(no_client_denied.status_code,403)
        self.assertEqual(no_client_denied.json()['error']['code'],'forbidden')
        # Extra Next instances on :3020–:3040 must be able to mutate with Origin + X-Care-Client.
        for port in (3020, 3021, 3030, 3040):
            with self.subTest(port=port):
                alt = TestClient(app, headers={'X-Care-Client': '1', 'Origin': f'http://127.0.0.1:{port}'})
                alt.cookies.update(self.client.cookies)
                allowed = alt.post('/api/v1/auth/logout')
                self.assertEqual(allowed.status_code, 200, allowed.text)
                self.login()
        # Trailing slash on Origin or allowlist entry must not block a real browser origin.
        from main import origin_allowed

        self.assertTrue(origin_allowed('http://127.0.0.1:3000/', ['http://127.0.0.1:3000']))
        self.assertTrue(origin_allowed('http://127.0.0.1:3000', ['http://127.0.0.1:3000/']))
        # Scheme/host casefold (RFC 6454) so mixed-case Origin or allowlist still mutates.
        self.assertTrue(origin_allowed('HTTP://127.0.0.1:3000', ['http://127.0.0.1:3000']))
        self.assertTrue(origin_allowed('http://127.0.0.1:3000', ['HTTP://127.0.0.1:3000']))
        self.assertFalse(origin_allowed('null', ['null', 'http://127.0.0.1:3000']))
        self.assertFalse(origin_allowed('NULL', ['null', 'http://127.0.0.1:3000']))
        self.assertFalse(origin_allowed('', ['http://127.0.0.1:3000']))
        slash = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'http://127.0.0.1:3000/'})
        slash.cookies.update(self.client.cookies)
        slash_out = slash.post('/api/v1/auth/logout')
        self.assertEqual(slash_out.status_code, 200, slash_out.text)
        self.login()
        # Proxy-padded X-Care-Client must still mutate (strip like Origin).
        padded_client = TestClient(app, headers={'X-Care-Client': ' 1 ', 'Origin': 'http://127.0.0.1:3000'})
        padded_client.cookies.update(self.client.cookies)
        padded_out = padded_client.post('/api/v1/auth/logout')
        self.assertEqual(padded_out.status_code, 200, padded_out.text)
        self.login()
        case_origin = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'HTTP://127.0.0.1:3000'})
        case_origin.cookies.update(self.client.cookies)
        case_out = case_origin.post('/api/v1/auth/logout')
        self.assertEqual(case_out.status_code, 200, case_out.text)
        # Case-origin logout already cleared the session; opaque CSRF still 403 without a re-login
        # (keeps this test under the login-email throttle budget).
        opaque = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'null'})
        opaque.cookies.update(self.client.cookies)
        self.assertEqual(opaque.post('/api/v1/auth/logout').status_code, 403)
        me=self.client.get('/api/v1/me')
        self.assertEqual(me.status_code,401)
        self.assertEqual(me.json()['error']['code'],'unauthenticated')
        # Logout clears both session and leftover Google oauth_state cookies.
        self.login()
        self.client.cookies.set('oauth_state', 'stale-oauth-state')
        cleared = self.client.post('/api/v1/auth/logout')
        self.assertEqual(cleared.status_code, 200, cleared.text)
        set_cookie = cleared.headers.get('set-cookie') or ''
        self.assertIn('oauth_state', set_cookie.lower())
        # Production Secure flags must be present on set and matching delete for both cookies.
        # Padded / mixed-case APP_ENV uses the same strip+casefold production_env path.
        from main import production_env, _session_cookie_kwargs, _oauth_state_cookie_kwargs

        for env_value in ('Production', ' production ', 'PRODUCTION'):
            with self.subTest(app_env=env_value), patch.dict(os.environ, {'APP_ENV': env_value}):
                self.assertTrue(production_env())
                self.assertTrue(_session_cookie_kwargs()['secure'])
                self.assertTrue(_oauth_state_cookie_kwargs()['secure'])
        with patch.dict(os.environ, {'APP_ENV': ' Production '}):
            secure_login = self.client.post('/api/v1/auth/login', json={'email': 'a@example.com', 'password': PASSWORD})
            self.assertEqual(secure_login.status_code, 200, secure_login.text)
            secure_set = secure_login.headers.get('set-cookie') or ''
            self.assertRegex(secure_set, r'(?i)httponly')
            self.assertRegex(secure_set, r'(?i)samesite=lax')
            self.assertRegex(secure_set, r'(?i);\s*secure')
            self.client.cookies.set('oauth_state', 'prod-oauth-state')
            secure_out = self.client.post('/api/v1/auth/logout')
            self.assertEqual(secure_out.status_code, 200, secure_out.text)
            secure_clear = secure_out.headers.get('set-cookie') or ''
            self.assertRegex(secure_clear, r'(?i);\s*secure')
            self.assertRegex(secure_clear, r'(?i)samesite=lax')
            self.assertRegex(secure_clear, r'(?i)httponly')
        self.assertEqual(self.client.get('/users/').status_code,404)
        self.assertEqual(self.client.get('/internal/v1/catalogue/connect').status_code,403)

    def test_login_without_peer_address_still_authenticates(self):
        from starlette.requests import Request
        from main import client_host

        scope = {
            'type': 'http',
            'asgi': {'spec_version': '2.3', 'version': '3.0'},
            'http_version': '1.1',
            'method': 'POST',
            'scheme': 'http',
            'path': '/api/v1/auth/login',
            'raw_path': b'/api/v1/auth/login',
            'query_string': b'',
            'headers': [],
            'client': None,
            'server': ('127.0.0.1', 8000),
        }
        self.assertEqual(client_host(Request(scope)), 'unknown')
        with patch('main.client_host', return_value='unknown'):
            result = self.client.post('/api/v1/auth/login', json={'email': 'a@example.com', 'password': PASSWORD})
        self.assertEqual(result.status_code, 200, result.text)

    def test_login_rotates_presented_session_cookie(self):
        first = self.login()
        prior = self.client.cookies.get('care_session')
        self.assertTrue(prior)
        with self.Session() as db:
            self.assertIsNotNone(db.get(LoginSession, digest(prior)))
        second = self.client.post('/api/v1/auth/login', json={'email': 'b@example.com', 'password': PASSWORD})
        self.assertEqual(second.status_code, 200, second.text)
        nxt = self.client.cookies.get('care_session')
        self.assertTrue(nxt)
        self.assertNotEqual(prior, nxt)
        with self.Session() as db:
            self.assertIsNone(db.get(LoginSession, digest(prior)))
            self.assertIsNotNone(db.get(LoginSession, digest(nxt)))
        me = self.client.get('/api/v1/me')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()['email'], 'b@example.com')
        # First cookie header still shows httponly rotation path for the initial login.
        self.assertIn('HttpOnly', first.headers.get('set-cookie', ''))

    def test_login_clears_leftover_oauth_state(self):
        """Password login drops leftover Google CSRF state (parity with OAuth callback success)."""
        self.client.cookies.set('oauth_state', 'stale-after-abandoned-google')
        result = self.client.post('/api/v1/auth/login', json={'email': 'a@example.com', 'password': PASSWORD})
        self.assertEqual(result.status_code, 200, result.text)
        set_cookie = result.headers.get('set-cookie') or ''
        self.assertIn('oauth_state', set_cookie.lower())
        self.assertIn('care_session', set_cookie.lower())

    def test_two_user_isolation_and_roles(self):
        first = self.save()
        self.assertEqual(first.status_code,200)
        # Correction history is written on update; ensure owner has rows before asserting isolation.
        corrected = self.save(signup_status='signed_up', attended=True, attended_on=today().isoformat(), points=4, version=1)
        self.assertEqual(corrected.status_code, 200, corrected.text)
        owner_history = self.client.get('/api/v1/me/trainings/' + self.course + '/history')
        self.assertEqual(owner_history.status_code, 200, owner_history.text)
        self.assertGreaterEqual(len(owner_history.json()['items']), 1)
        self.login('b@example.com')
        self.assertEqual(self.client.get('/api/v1/me/trainings').json()['items'],[])
        self.assertIsNone(self.client.get('/api/v1/trainings/'+self.course).json()['record'])
        self.assertEqual(self.client.get('/api/v1/admin/candidates').status_code,403)
        self.assertEqual(self.client.post('/internal/v1/jobs/claim').status_code,403)
        self.assertNotIn('PRIVATE NOTE', self.client.get('/api/v1/me/export/csv').text)
        self.assertEqual(self.client.get('/api/v1/me/progress').json()['attended'], 0)
        self.assertEqual(self.client.get('/api/v1/me/trainings/' + self.course + '/history').json()['items'], [])
        self.assertEqual(self.client.get('/api/v1/admin/audit').status_code, 403)
        own = self.client.get('/api/v1/me/audit').json()
        self.assertEqual(own['items'], [])
        self.assertEqual(self.client.get('/api/v1/me/digest').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/me/suggestions').status_code, 200)
        self.assertEqual(self.client.post('/api/v1/me/certificates', json={'year': 2026}).status_code, 201)
        self.assertNotIn('PRIVATE NOTE', self.client.get('/api/v1/me/progress').text)
        self.login('a@example.com')
        still_owner = self.client.get('/api/v1/me/trainings/' + self.course + '/history')
        self.assertGreaterEqual(len(still_owner.json()['items']), 1)

    def test_personal_notes_stay_out_of_logs_and_audit(self):
        import io
        import logging

        from observe import setup

        setup()
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        log = logging.getLogger('carecredits')
        log.addHandler(handler)
        try:
            self.assertEqual(self.save().status_code, 200)
            self.assertNotIn('PRIVATE NOTE', buffer.getvalue())
        finally:
            log.removeHandler(handler)
        with self.Session() as db:
            dumped = ' '.join(str(row.changed) for row in db.query(Audit).all())
            self.assertNotIn('PRIVATE NOTE', dumped)
        mine = self.client.get('/api/v1/me/audit').json()
        self.assertGreaterEqual(mine['total'], 1)
        self.assertNotIn('PRIVATE NOTE', str(mine))
        admin = self.client.get('/api/v1/admin/audit').json()
        self.assertGreaterEqual(admin['total'], 1)
        self.assertTrue(all('notes' not in (item.get('changed') or {}) for item in admin['items']))
        self.assertEqual(self.client.get('/api/v1/me/audit?page=0').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/me/audit?page_size=51').status_code, 422)
        paged = self.client.get('/api/v1/admin/audit?page=1&page_size=1').json()
        self.assertEqual(paged['page'], 1)
        self.assertEqual(paged['page_size'], 1)
        self.assertEqual(len(paged['items']), 1)

    def test_record_idempotency_and_points_corrections(self):
        first=self.save();self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.save().json()['version'],1)
        progress=self.client.get('/api/v1/me/progress').json()
        self.assertEqual((progress['points'],progress['attended']),(3,1))
        self.assertEqual(self.save(points=4,version=0).status_code,409)
        self.assertEqual(self.save(points=4,version=1).status_code,200)
        self.assertEqual(self.client.get('/api/v1/me/progress').json()['points'],4)
        self.assertEqual(self.save(attended=False,version=2).status_code,200)
        self.assertEqual(self.client.get('/api/v1/me/progress').json()['points'],0)

    def test_record_points_reject_bool(self):
        """JSON true/false must not become 1.0/0.0 recorded CPD points."""
        first = self.save()
        self.assertEqual(first.status_code, 200, first.text)
        for value in (True, False):
            blocked = self.client.put(
                '/api/v1/me/trainings/' + self.course,
                json={
                    'signed_up': True,
                    'signup_status': 'signed_up',
                    'attended': True,
                    'attendance_status': 'attended',
                    'attended_on': today().isoformat(),
                    'points': value,
                    'credit_label': 'CPD',
                    'notes': '',
                    'public': False,
                    'version': 1,
                },
            )
            self.assertEqual(blocked.status_code, 422, blocked.text)

    def test_future_and_unknown_credits(self):
        self.assertEqual(self.save(attended_on=(today()+timedelta(days=1)).isoformat()).status_code,422)
        future_start=(today()+timedelta(days=7)).isoformat()
        with self.Session() as db:
            course=db.get(Course,self.course)
            fill_course(course,{**course.data,'start_date':future_start})
            db.commit()
        # Future sessions cannot be marked attended: completion before start, or a future attended_on, both reject.
        self.assertEqual(self.save(attended_on=today().isoformat()).status_code,422)
        self.assertEqual(self.save(attended_on=future_start).status_code,422)
        with self.Session() as db:
            course=db.get(Course,self.course)
            fill_course(course,{**course.data,'start_date':'2026-01-01'})
            db.commit()
        self.assertEqual(self.save(points=None,credit_label='CME').status_code,200)
        p=self.client.get('/api/v1/me/progress').json();self.assertEqual((p['points'],p['excluded']),(0,1))
        self.assertEqual(p['excluded_reasons'][0]['reason'],'unknown_points')
        self.assertEqual(self.save(points=2,credit_label='CME',version=1).status_code,200)
        p=self.client.get('/api/v1/me/progress').json()
        self.assertEqual((p['points'],p['excluded']),(0,1))
        self.assertEqual(p['excluded_reasons'][0]['reason'],'unmapped_credit_label')

    def test_public_opt_in_and_revocation(self):
        self.save()
        url='/api/v1/public/'+self.slug
        self.assertEqual(self.client.get(url).status_code,404)
        body={'name':'Doctor A','city':'KL','bio':'Learning','public_enabled':True}
        self.assertEqual(self.client.patch('/api/v1/me',json=body).status_code,200)
        public=self.client.get(url)
        self.assertEqual(len(public.json()['items']),1)
        for private in ['PRIVATE NOTE','a@example.com','password_hash','signed_up','points']:
            self.assertNotIn(private,public.text)
        self.assertEqual(public.headers['cache-control'],'no-store')
        self.client.patch('/api/v1/me',json={**body,'public_enabled':False})
        self.assertEqual(self.client.get(url).status_code,404)

    def test_public_profile_omits_unsafe_source_url(self):
        self.save()
        with self.Session() as db:
            course=db.get(Course,self.course)
            data=dict(course.data or {})
            data['source_url']='javascript:alert(1)'
            course.data=data
            db.commit()
        self.client.patch('/api/v1/me',json={'name':'Doctor A','city':'KL','bio':'Learning','public_enabled':True})
        public=self.client.get('/api/v1/public/'+self.slug)
        self.assertEqual(public.status_code,200,public.text)
        self.assertIsNone(public.json()['items'][0]['source_url'])
        self.assertNotIn('javascript:', public.text)

    def test_public_profile_honours_attendance_status_when_bool_drifts(self):
        self.save()
        self.client.patch('/api/v1/me', json={'name': 'Doctor A', 'city': 'KL', 'bio': 'Learning', 'public_enabled': True})
        with self.Session() as db:
            record = db.query(Record).filter_by(account_id=self.a, course_id=self.course).one()
            record.attended = False
            record.attendance_status = 'attended'
            record.public = True
            db.commit()
        public = self.client.get('/api/v1/public/' + self.slug)
        self.assertEqual(public.status_code, 200, public.text)
        self.assertEqual(len(public.json()['items']), 1)
        self.assertIn('Self-reported', public.json()['evidence_status'])
        for private in ['PRIVATE NOTE', 'a@example.com', 'password_hash', 'points']:
            self.assertNotIn(private, public.text)

    def test_training_detail_omits_unsafe_source_urls(self):
        with self.Session() as db:
            course=db.get(Course,self.course)
            data=dict(course.data or {})
            data['source_url']='javascript:alert(1)'
            data['registration_url']='javascript:alert(2)'
            course.data=data
            db.commit()
        detail=self.client.get('/api/v1/trainings/'+self.course)
        self.assertEqual(detail.status_code,200,detail.text)
        body=detail.json()
        self.assertIsNone(body.get('source_url'))
        self.assertIsNone(body.get('registration_url'))
        self.assertNotIn('javascript:', detail.text)

    def test_export_is_download_only_and_neutralizes_formulas(self):
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'=HYPERLINK("evil")'})
            data=dict(c.data or {})
            data['source_url']='javascript:alert(1)'
            c.data=data
            db.commit()
        self.save()
        csv=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'=HYPERLINK",csv.text)
        self.assertNotIn('javascript:',csv.text)
        # Completeness: session date + status columns; private notes still omitted.
        self.assertIn('Session date', csv.text)
        self.assertIn('Signup status', csv.text)
        self.assertIn('Attendance status', csv.text)
        self.assertIn('signed_up', csv.text)
        self.assertIn('attended', csv.text)
        self.assertNotIn('PRIVATE NOTE', csv.text)
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'\u200b=HYPERLINK("evil")','provider':'\ufeff+cmd'})
            db.commit()
        zwsp=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'\u200b=HYPERLINK",zwsp.text)
        self.assertIn("'\ufeff+cmd",zwsp.text)
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'\u00a0=CMD|calc','provider':'\u3000@SUM(1)'})
            db.commit()
        nbsp=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'\u00a0=CMD|calc",nbsp.text)
        self.assertIn("'\u3000@SUM(1)",nbsp.text)
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'\u2028=LINE','provider':'\uff1dFULL'})
            db.commit()
        residual=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'\u2028=LINE", residual.text)
        self.assertIn("'\uff1dFULL", residual.text)
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'\u2212SUM(1)','provider':'\ufe63CMD'})
            db.commit()
        unicode_minus=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'\u2212SUM(1)", unicode_minus.text)
        self.assertIn("'\ufe63CMD", unicode_minus.text)
        # Bidi overrides/marks must not hide formula starters from neutralization.
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'\u202e=CMD|calc','provider':'\u200e@SUM(1)'})
            db.commit()
        bidi=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'\u202e=CMD|calc", bidi.text)
        self.assertIn("'\u200e@SUM(1)", bidi.text)
        # Soft hyphen / CGJ / Arabic letter mark must not hide formula starters.
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'title':'\u00ad=CMD|calc','provider':'\u034f@SUM(1)'})
            record=db.query(Record).filter_by(account_id=self.a, course_id=self.course).one()
            record.credit_label='\u061c-1+1'
            db.commit()
        soft=self.client.get('/api/v1/me/export/csv')
        self.assertIn("'\u00ad=CMD|calc", soft.text)
        self.assertIn("'\u034f@SUM(1)", soft.text)
        self.assertIn("'\u061c-1+1", soft.text)
        # Year filter matches PROG-01 (attended_on for attended; start_date otherwise).
        year_csv=self.client.get('/api/v1/me/export/csv?year=1999')
        self.assertEqual(year_csv.status_code,200,year_csv.text)
        self.assertIn('Session date', year_csv.text)
        self.assertEqual(year_csv.text.count('\n'),1)  # header only — honest empty export
        self.assertIn('carecredits-record-1999.csv', year_csv.headers.get('content-disposition',''))
        empty_eml=self.client.get('/api/v1/me/export/eml?year=1999')
        self.assertEqual(empty_eml.status_code,200,empty_eml.text)
        self.assertIn('No attended records for 1999', empty_eml.text)
        self.assertEqual(self.client.get('/api/v1/me/export/csv?year=18').status_code,422)
        # year=0 must not falsy-coerce (parity with progress/certificates).
        self.assertEqual(self.client.get('/api/v1/me/export/csv?year=0').status_code, 422)
        # Completed-on / credit label formula prefixes are neutralized like title/provider.
        with self.Session() as db:
            record = db.query(Record).filter_by(account_id=self.a, course_id=self.course).one()
            record.attended_on = '=CMD|calc'
            record.credit_label = '@SUM(1)'
            db.commit()
        formula_csv = self.client.get('/api/v1/me/export/csv')
        self.assertEqual(formula_csv.status_code, 200, formula_csv.text)
        self.assertIn("'=CMD|calc", formula_csv.text)
        self.assertIn("'@SUM(1)", formula_csv.text)
        # Cancelled signup must not look open in Signed up when legacy signed_up bool drifted.
        with self.Session() as db:
            record = db.query(Record).filter_by(account_id=self.a, course_id=self.course).one()
            record.signup_status = 'cancelled'
            record.signed_up = True
            record.attendance_status = 'not_recorded'
            record.attended = False
            db.commit()
        cancelled_csv = self.client.get('/api/v1/me/export/csv')
        self.assertEqual(cancelled_csv.status_code, 200, cancelled_csv.text)
        self.assertIn(',False,cancelled,', cancelled_csv.text.replace(' ', ''))
        self.assertIn('cancelled', cancelled_csv.text)
        eml=self.client.get('/api/v1/me/export/eml')
        self.assertIn('X-Unsent: 1',eml.text)
        self.assertNotIn('\nTo:',eml.text)

    def test_ingestion_job_max_results_reject_bool(self):
        """JSON true must not coerce to max_results=1 and invent a paid Search size."""
        header = {'Idempotency-Key': 'bool-max-results'}
        blocked = self.client.post(
            '/api/v1/admin/ingestion-jobs',
            json={'query': 'GP bool max results', 'max_results': True},
            headers=header,
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)

    def test_job_idempotency_leases_and_completion(self):
        header={'Idempotency-Key':'test-unique-key'}
        first=self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP course'},headers=header)
        self.assertEqual(first.status_code,202,first.text)
        job=first.json()
        self.assertEqual(job['job_id'], job['id'])
        replay=self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP course'},headers=header)
        self.assertEqual(replay.status_code,202,replay.text)
        self.assertEqual(replay.json()['id'],job['id'])
        self.assertEqual(replay.json()['job_id'],job['job_id'])
        self.assertEqual(replay.json()['query'],'GP course')
        self.assertEqual(self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'different'},headers=header).status_code,409)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        self.assertEqual(self.client.post('/internal/v1/jobs/claim',headers=service).status_code,204)
        empty = self.client.post('/internal/v1/jobs/claim',headers=service)
        self.assertEqual(empty.status_code,204)
        self.assertEqual(empty.headers.get('x-care-claim-reason'), 'empty')
        payload={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[sample()]}
        complete='/internal/v1/jobs/'+claim['id']+'/complete'
        self.assertEqual(self.client.post(complete,json=payload,headers=service).status_code,200)
        with self.Session() as db:
            row=db.get(Job, claim['id'])
            self.assertEqual(row.status, 'succeeded')
            self.assertIsNone(row.lease_token)
            self.assertIsNone(row.lease_until)
            self.assertIsNone(row.started_at)
        # Idempotent retry stays 200 even after lease fields are cleared.
        self.assertEqual(self.client.post(complete,json=payload,headers=service).status_code,200)
        queue=self.client.get('/api/v1/admin/candidates').json()['items'];self.assertEqual(len(queue),1)
        review=self.client.post('/api/v1/admin/candidates/'+queue[0]['id']+'/review',json={'action':'publish','version':1})
        self.assertEqual(review.status_code,200,review.text)
        self.assertEqual(self.client.get('/api/v1/admin/candidates').json()['items'],[])

    def test_concurrent_complete_does_not_duplicate_candidates(self):
        from concurrent.futures import ThreadPoolExecutor
        header={'Idempotency-Key':'concurrent-complete-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP concurrent complete'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        payload={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[sample('Concurrent GP')]}
        url='/internal/v1/jobs/'+claim['id']+'/complete'
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.submit(self.client.post, url, json=payload, headers=service), pool.submit(self.client.post, url, json=payload, headers=service)
            codes=sorted([first.result().status_code, second.result().status_code])
        self.assertTrue(all(code in (200, 409) for code in codes))
        self.assertEqual(len(self.client.get('/api/v1/admin/candidates').json()['items']),1)

    def test_job_completion_keeps_tavily_sources(self):
        header={'Idempotency-Key':'tavily-sources-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP Tavily sources'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        payload={
            'lease_token':claim['lease_token'],'status':'partial','candidates':[],
            'warnings':['Configure an open-weight model. Tavily sources were saved for review.'],
            'sources':[{
                'url':'https://example.org/afpm',
                'title':'Primary Care Update',
                'snippet':'CPD workshop in Kuala Lumpur',
                'extraction_status':'success',
                'verification_status':'unverified',
                'retrieved_at':'2026-10-03T03:00:00+00:00',
            }],
        }
        self.assertEqual(self.client.post('/internal/v1/jobs/'+claim['id']+'/complete',json=payload,headers=service).status_code,200)
        stored=self.client.get('/api/v1/admin/ingestion-jobs').json()['items'][0]
        self.assertEqual(stored['status'],'partial')
        self.assertEqual(stored['result']['sources'][0]['title'],'Primary Care Update')
        self.assertEqual(stored['result']['sources'][0]['retrieved_at'],'2026-10-03T03:00:00+00:00')
        self.assertEqual(stored['result']['candidate_count'],0)
        from portal_models import SourceDocument, retrieved_stamp
        with self.Session() as db:
            rows = db.query(SourceDocument).filter_by(canonical_url='https://example.org/afpm').all()
            self.assertEqual(len(rows), 1)
            stamp = retrieved_stamp({'retrieved_at': '2026-10-03T03:00:00+00:00'})
            self.assertEqual(rows[0].retrieved_at, stamp)
            # UTC ISO must not skew by local timezone (mktime bug).
            self.assertEqual(stamp, 1790996400.0)
        detail=self.client.get('/api/v1/admin/ingestion-jobs/'+claim['id'])
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertEqual(detail.json()['id'],claim['id'])
        self.assertEqual(detail.json()['result']['sources'][0]['url'],'https://example.org/afpm')
        self.assertEqual(self.client.get('/api/v1/admin/ingestion-jobs/missing-job').status_code,404)
        self.login('b@example.com')
        self.assertEqual(self.client.get('/api/v1/admin/ingestion-jobs/'+claim['id']).status_code,403)

    def test_job_completion_stores_reported_usage_or_null(self):
        from main import normalize_job_usage
        self.assertEqual(
            normalize_job_usage({'tavily_credits': '2.5', 'model_tokens': '40', 'catalogue_saved': 1}),
            {'tavily_credits': 2.5, 'model_tokens': 40, 'catalogue_saved': 1},
        )
        self.assertEqual(
            normalize_job_usage({'tavily_credits': 'nope', 'model_tokens': -1}),
            {'tavily_credits': None, 'model_tokens': None},
        )
        self.assertEqual(
            normalize_job_usage({'tavily_credits': float('inf'), 'model_tokens': float('nan')}),
            {'tavily_credits': None, 'model_tokens': None},
        )
        # int(inf) raises OverflowError — must fail closed like scraper reported_model_tokens.
        self.assertEqual(
            normalize_job_usage({'model_tokens': float('inf'), 'catalogue_saved': float('-inf')}),
            {'tavily_credits': None, 'model_tokens': None},
        )
        # JSON booleans must not invent spend (True→1 / False→0 via int/float).
        self.assertEqual(
            normalize_job_usage({'tavily_credits': True, 'model_tokens': False, 'catalogue_saved': True}),
            {'tavily_credits': None, 'model_tokens': None},
        )
        self.assertEqual(normalize_job_usage({}), {'tavily_credits': None, 'model_tokens': None})
        header = {'Idempotency-Key': 'usage-null-key'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP usage null'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        empty = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'failed', 'candidates': [], 'sources': [], 'usage': {}},
            headers=service,
        )
        self.assertEqual(empty.status_code, 200, empty.text)
        stored = self.client.get('/api/v1/admin/ingestion-jobs/' + claim['id']).json()
        self.assertEqual(stored['result']['usage'], {'tavily_credits': None, 'model_tokens': None})
        header2 = {'Idempotency-Key': 'usage-reported-key'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP usage reported'}, headers=header2)
        claim2 = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        reported = self.client.post(
            '/internal/v1/jobs/' + claim2['id'] + '/complete',
            json={
                'lease_token': claim2['lease_token'],
                'status': 'succeeded',
                'candidates': [],
                'sources': [],
                'usage': {'tavily_credits': 3, 'model_tokens': 120, 'junk': 'ignore'},
            },
            headers=service,
        )
        self.assertEqual(reported.status_code, 200, reported.text)
        body = self.client.get('/api/v1/admin/ingestion-jobs/' + claim2['id']).json()
        self.assertEqual(body['result']['usage'], {'tavily_credits': 3.0, 'model_tokens': 120})
        # Dirty historical usage is re-normalized on read so the UI cannot invent spend.
        with self.Session() as db:
            dirty = db.get(Job, claim2['id'])
            dirty.result = {
                **(dirty.result or {}),
                'usage': {'tavily_credits': 'nope', 'model_tokens': -3, 'junk': 1},
            }
            db.commit()
        cleaned = self.client.get('/api/v1/admin/ingestion-jobs/' + claim2['id']).json()
        self.assertEqual(cleaned['result']['usage'], {'tavily_credits': None, 'model_tokens': None})
        self.assertEqual(cleaned['job_id'], claim2['id'])

    def test_job_sources_omit_unsafe_urls(self):
        header={'Idempotency-Key':'unsafe-job-source-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP unsafe source'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        payload={
            'lease_token':claim['lease_token'],'status':'partial','candidates':[],
            'sources':[
                {'url':'javascript:alert(1)','title':'Unsafe source','snippet':'Do not link this','extraction_status':'failed','verification_status':'unverified'},
                {'url':'https://example.org/afpm','title':'Primary Care Update','snippet':'CPD workshop in Kuala Lumpur','extraction_status':'success','verification_status':'unverified'},
            ],
        }
        self.assertEqual(self.client.post('/internal/v1/jobs/'+claim['id']+'/complete',json=payload,headers=service).status_code,200)
        stored=self.client.get('/api/v1/admin/ingestion-jobs/'+claim['id'])
        self.assertEqual(stored.status_code,200,stored.text)
        sources=stored.json()['result']['sources']
        self.assertEqual(sources[0]['title'],'Unsafe source')
        self.assertIsNone(sources[0]['url'])
        self.assertEqual(sources[1]['url'],'https://example.org/afpm')
        self.assertNotIn('javascript:', stored.text)
        with self.Session() as db:
            rows=db.query(SourceDocument).filter_by(job_id=claim['id']).all()
            self.assertEqual([row.canonical_url for row in rows],['https://example.org/afpm'])

    def test_expired_lease_complete_does_not_publish(self):
        header={'Idempotency-Key':'expired-lease-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP lease timeout'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        with self.Session() as db:
            job=db.get(Job, claim['id'])
            job.lease_until=1
            # Simulate mid-job spend already recorded before the lease died.
            job.result={'usage':{'tavily_credits':2,'model_tokens':40},'sources':[{'url':'https://example.org/afpm'}],'warnings':['partial extract']}
            db.commit()
        complete=self.client.post(
            '/internal/v1/jobs/'+claim['id']+'/complete',
            json={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[sample('Late crash')]},
            headers=service,
        )
        self.assertEqual(complete.status_code,409)
        listed=self.client.get('/api/v1/trainings?period=all&q=Late%20crash').json()
        self.assertEqual(listed['total'],0)
        stored=self.client.get('/api/v1/admin/ingestion-jobs/'+claim['id']).json()
        self.assertEqual(stored['status'],'interrupted')
        self.assertEqual(stored['result']['usage'],{'tavily_credits':2.0,'model_tokens':40})
        self.assertEqual(stored['result']['sources'][0]['url'],'https://example.org/afpm')
        self.assertTrue(any('lease expired' in w.lower() for w in stored['result']['warnings']))
        with self.Session() as db:
            row=db.get(Job, claim['id'])
            self.assertIsNone(row.lease_token)
            self.assertIsNone(row.lease_until)
            self.assertIsNone(row.started_at)

    def test_heartbeat_extends_lease(self):
        header={'Idempotency-Key':'heartbeat-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP heartbeat'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        with self.Session() as db:
            job=db.get(Job, claim['id'])
            before=job.lease_until
            job.lease_until=before - 60
            db.commit()
            shortened=before - 60
        beat=self.client.post('/internal/v1/jobs/'+claim['id']+'/heartbeat',json={'lease_token':claim['lease_token']},headers=service)
        self.assertEqual(beat.status_code,200,beat.text)
        with self.Session() as db:
            after=db.get(Job, claim['id']).lease_until
        self.assertGreater(after, shortened)
        self.assertGreaterEqual(after, before)
        stale=self.client.post('/internal/v1/jobs/'+claim['id']+'/heartbeat',json={'lease_token':'wrong'},headers=service)
        self.assertEqual(stale.status_code,409)

    def test_expire_jobs_loses_to_fresher_lease_between_select_and_update(self):
        """Conditional expire UPDATE must not interrupt a lease extended after the SELECT snapshot."""
        import time
        from unittest.mock import patch
        from main import expire_jobs
        from sqlalchemy import update as sa_update

        header={'Idempotency-Key':'expire-race-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP expire race'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        with self.Session() as db:
            job=db.get(Job, claim['id'])
            job.lease_until=time.time() - 5
            db.commit()
            job_id=job.id
            token=job.lease_token
        with self.Session() as db:
            snapshot=[db.get(Job, job_id)]

            class SnapshotQuery:
                def filter(self, *args, **kwargs):
                    return self

                def all(self):
                    # Concurrent winner extends the lease after expire's SELECT.
                    db.execute(sa_update(Job).where(Job.id == job_id).values(lease_until=time.time() + 120))
                    db.commit()
                    return snapshot

            with patch.object(db, 'query', return_value=SnapshotQuery()):
                expire_jobs(db)
            row=db.get(Job, job_id)
            self.assertEqual(row.status, 'running')
            self.assertEqual(row.lease_token, token)
            self.assertGreater(row.lease_until, time.time())

    def test_complete_upserts_pending_candidate_same_source_key(self):
        from main import source_key as make_source_key
        payload=sample('Upsert Complete GP')
        key=make_source_key(payload)
        with self.Session() as db:
            first=Job(account_id=self.a,request_key='upsert-complete-1',query='GP upsert one',status='succeeded')
            db.add(first);db.flush()
            pending=Candidate(job_id=first.id,source_key=key,data=payload,status='pending')
            db.add(pending)
            db.commit()
            first_id, pending_id = first.id, pending.id
        header={'Idempotency-Key':'upsert-complete-2'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP upsert two'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        complete=self.client.post(
            '/internal/v1/jobs/'+claim['id']+'/complete',
            json={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[payload]},
            headers=service,
        )
        self.assertEqual(complete.status_code,200,complete.text)
        queue=self.client.get('/api/v1/admin/candidates').json()['items']
        matches=[item for item in queue if item['data']['title']=='Upsert Complete GP']
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['status'],'pending')
        # Refresh must not reassign job_id onto the completing job (UniqueConstraint collision risk).
        with self.Session() as db:
            row = db.get(Candidate, pending_id)
            self.assertEqual(row.job_id, first_id)
            self.assertNotEqual(row.job_id, claim['id'])

    def test_complete_preserves_judgment_and_holds_uncertain(self):
        payload = sample('Judgment Hold GP')
        payload['_judgment'] = {
            'decision': 'uncertain',
            'confidence': 0.0,
            'probabilities': {'exists': 0.0, 'new': 0.0, 'uncertain': 1.0},
            'warning': 'Decide endpoint unavailable; held for review.',
        }
        header = {'Idempotency-Key': 'judgment-hold-complete'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP judgment'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'partial', 'candidates': [payload], 'warnings': ['save failed']},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        queue = self.client.get('/api/v1/admin/candidates?status=held').json()['items']
        matches = [item for item in queue if item['data']['title'] == 'Judgment Hold GP']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['status'], 'held')
        self.assertEqual(matches[0]['data']['_judgment']['decision'], 'uncertain')
        # Refresh without judgment must keep the prior Jev payload.
        claim2_header = {'Idempotency-Key': 'judgment-hold-refresh'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP judgment two'}, headers=claim2_header)
        claim2 = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        bare = {key: value for key, value in payload.items() if key != '_judgment'}
        refresh = self.client.post(
            '/internal/v1/jobs/' + claim2['id'] + '/complete',
            json={'lease_token': claim2['lease_token'], 'status': 'succeeded', 'candidates': [bare]},
            headers=service,
        )
        self.assertEqual(refresh.status_code, 200, refresh.text)
        held = self.client.get('/api/v1/admin/candidates?status=held').json()['items']
        again = [item for item in held if item['data']['title'] == 'Judgment Hold GP']
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]['data']['_judgment']['decision'], 'uncertain')

    def test_complete_reopens_rejected_candidate_same_source_key(self):
        """Cross-job complete must reopen a rejected identity instead of forking a second review card."""
        from main import source_key as make_source_key
        payload = sample('Reopen Rejected GP')
        key = make_source_key(payload)
        with self.Session() as db:
            prior = Job(account_id=self.a, request_key='reopen-rejected-1', query='GP', status='succeeded')
            db.add(prior)
            db.flush()
            rejected = Candidate(
                job_id=prior.id,
                source_key=key,
                data=payload,
                status='rejected',
                review_reason='Not a Malaysia GP session',
                reviewed_by='operator',
                reviewed_at=1.0,
                version=3,
            )
            db.add(rejected)
            db.commit()
            prior_id, rejected_id, prior_version = prior.id, rejected.id, 3
        header = {'Idempotency-Key': 'reopen-rejected-2'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP reopen'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [payload]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        queue = self.client.get('/api/v1/admin/candidates').json()['items']
        matches = [item for item in queue if item['data']['title'] == 'Reopen Rejected GP']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['status'], 'pending')
        self.assertEqual(matches[0]['id'], rejected_id)
        with self.Session() as db:
            rows = db.query(Candidate).filter_by(source_key=key).all()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row.job_id, prior_id)
            self.assertEqual(row.review_reason, '')
            self.assertIsNone(row.reviewed_by)
            self.assertIsNone(row.reviewed_at)
            self.assertGreater(row.version, prior_version)

    def test_complete_reopens_held_candidate_to_pending(self):
        """Cross-job complete with decision=new must reopen held→pending (bare refresh keeps held)."""
        from main import source_key as make_source_key
        payload = sample('Reopen Held GP')
        key = make_source_key(payload)
        with self.Session() as db:
            prior = Job(account_id=self.a, request_key='reopen-held-1', query='GP', status='succeeded')
            db.add(prior)
            db.flush()
            held = Candidate(
                job_id=prior.id,
                source_key=key,
                data={**payload, '_judgment': {'decision': 'uncertain', 'confidence': 0.3}},
                status='held',
                review_reason='Jev uncertain: needs operator review',
                reviewed_by='operator',
                reviewed_at=1.0,
                version=2,
            )
            db.add(held)
            db.commit()
            prior_id, held_id, prior_version = prior.id, held.id, 2
        header = {'Idempotency-Key': 'reopen-held-2'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP reopen held'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        renewed = {
            **payload,
            '_judgment': {'decision': 'new', 'confidence': 0.9, 'probabilities': {'new': 0.9}},
        }
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [renewed]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        queue = self.client.get('/api/v1/admin/candidates').json()['items']
        matches = [item for item in queue if item['data']['title'] == 'Reopen Held GP']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['status'], 'pending')
        self.assertEqual(matches[0]['id'], held_id)
        with self.Session() as db:
            rows = db.query(Candidate).filter_by(source_key=key).all()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row.job_id, prior_id)
            self.assertEqual(row.status, 'pending')
            self.assertEqual(row.review_reason, '')
            self.assertIsNone(row.reviewed_by)
            self.assertIsNone(row.reviewed_at)
            self.assertGreater(row.version, prior_version)
            self.assertEqual((row.data or {}).get('_judgment', {}).get('decision'), 'new')

    def test_complete_does_not_500_when_job_already_has_rejected_same_key(self):
        from main import source_key as make_source_key
        payload = sample('Rejected Same Job GP')
        key = make_source_key(payload)
        with self.Session() as db:
            other = Job(account_id=self.a, request_key='rejected-other', query='GP', status='succeeded')
            running = Job(account_id=self.a, request_key='rejected-running', query='GP', status='queued')
            db.add_all([other, running])
            db.flush()
            db.add(Candidate(job_id=other.id, source_key=key, data=payload, status='pending'))
            db.add(Candidate(job_id=running.id, source_key=key, data=payload, status='rejected'))
            db.commit()
            running_id = running.id
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        self.assertEqual(claim['id'], running_id)
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [payload]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        with self.Session() as db:
            rows = db.query(Candidate).filter_by(source_key=key).all()
            self.assertEqual(len(rows), 2)
            # Prefer the earlier open sibling; do not reopen this job's rejected into a second pending.
            open_rows = [row for row in rows if row.status in ('pending', 'held')]
            self.assertEqual(len(open_rows), 1)
            self.assertNotEqual(open_rows[0].job_id, running_id)
            same_job = [row for row in rows if row.job_id == running_id][0]
            self.assertEqual(same_job.status, 'rejected')

    def test_complete_holds_refresh_when_source_key_already_published(self):
        """Bare complete against a published identity must hold a refresh, not fork a pending."""
        from main import source_key as make_source_key
        payload = sample('Published Complete Refresh GP')
        key = make_source_key(payload)
        with self.Session() as db:
            course = fill_course(Course(source_key=key), payload)
            db.add(course)
            db.commit()
            course_id = course.id
        header = {'Idempotency-Key': 'published-complete-refresh'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP published'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [payload]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        queue = self.client.get('/api/v1/admin/candidates?status=held').json()['items']
        matches = [item for item in queue if item['data']['title'] == 'Published Complete Refresh GP']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['status'], 'held')
        self.assertEqual(matches[0]['data'].get('_matched_course_id'), course_id)
        with self.Session() as db:
            rows = db.query(Candidate).filter_by(source_key=key).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, 'held')

    def test_complete_bare_refresh_keeps_operator_hold_on_new(self):
        """Bare soft-refresh must not reopen an operator hold when prior judgment is decision=new."""
        from main import source_key as make_source_key
        payload = sample('Operator Hold Soft Refresh GP')
        key = make_source_key(payload)
        with self.Session() as db:
            prior = Job(account_id=self.a, request_key='op-hold-soft-1', query='GP', status='succeeded')
            db.add(prior)
            db.flush()
            held = Candidate(
                job_id=prior.id,
                source_key=key,
                data={**payload, '_judgment': {'decision': 'new', 'confidence': 0.9}},
                status='held',
                review_reason='Need MMC confirmation',
                reviewed_by='operator',
                reviewed_at=1.0,
                version=2,
            )
            db.add(held)
            db.commit()
            held_id, prior_version = held.id, 2
        header = {'Idempotency-Key': 'op-hold-soft-2'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP operator hold soft'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [payload]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        with self.Session() as db:
            row = db.get(Candidate, held_id)
            self.assertEqual(row.status, 'held')
            self.assertEqual(row.review_reason, 'Need MMC confirmation')
            self.assertEqual(row.reviewed_by, 'operator')
            self.assertEqual(row.reviewed_at, 1.0)
            self.assertGreater(row.version, prior_version)
            self.assertEqual((row.data or {}).get('_judgment', {}).get('decision'), 'new')

    def test_complete_bare_refresh_keeps_exists_refresh_diff(self):
        """Second bare soft-refresh of a held exists row must keep/recompute published-vs-proposed diff."""
        from main import source_key as make_source_key
        payload = sample('Exists Soft Refresh Diff GP')
        key = make_source_key(payload)
        with self.Session() as db:
            course = fill_course(Course(source_key=key), payload)
            course.fee = None
            db.add(course)
            prior = Job(account_id=self.a, request_key='exists-soft-1', query='GP', status='succeeded')
            db.add(prior)
            db.flush()
            held = Candidate(
                job_id=prior.id,
                source_key=key,
                data={
                    **payload,
                    'fee': 120,
                    'currency': 'MYR',
                    '_judgment': {'decision': 'exists', 'confidence': 1, 'matched_session_id': course.id},
                    '_matched_course_id': course.id,
                    '_refresh_diff': [
                        {'field': 'fee', 'published': None, 'proposed': 120},
                        {'field': 'currency', 'published': None, 'proposed': 'MYR'},
                    ],
                },
                status='held',
                resulting_course_id=course.id,
                review_reason='Jev marked exists; review refresh before overwriting published fields.',
                version=2,
            )
            db.add(held)
            db.commit()
            course_id, held_id, prior_version = course.id, held.id, 2
        header = {'Idempotency-Key': 'exists-soft-2'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP exists soft'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        refreshed = {
            **payload,
            'fee': 180,
            'currency': 'MYR',
            'evidence': {**payload['evidence'], 'fee': payload['source_text'], 'currency': payload['source_text']},
        }
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [refreshed]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        queue = self.client.get('/api/v1/admin/candidates?status=held').json()['items']
        matches = [item for item in queue if item['id'] == held_id]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['status'], 'held')
        self.assertEqual(matches[0]['data']['_judgment']['decision'], 'exists')
        self.assertEqual(matches[0]['data'].get('_matched_course_id'), course_id)
        diff = {row['field']: row for row in matches[0]['data'].get('_refresh_diff') or []}
        self.assertEqual(diff['fee']['published'], None)
        self.assertEqual(diff['fee']['proposed'], 180)
        with self.Session() as db:
            row = db.get(Candidate, held_id)
            self.assertGreater(row.version, prior_version)

    def test_complete_pending_refresh_bumps_version(self):
        from main import source_key as make_source_key
        payload = sample('Pending Refresh Version GP')
        key = make_source_key(payload)
        with self.Session() as db:
            prior = Job(account_id=self.a, request_key='pending-refresh-1', query='GP', status='succeeded')
            db.add(prior)
            db.flush()
            pending = Candidate(
                job_id=prior.id,
                source_key=key,
                data=payload,
                status='pending',
                version=2,
            )
            db.add(pending)
            db.commit()
            pending_id, prior_version = pending.id, pending.version
        header = {'Idempotency-Key': 'pending-refresh-2'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP pending refresh'}, headers=header)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        refreshed = {**payload, 'description': 'Updated evidence for remount'}
        complete = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': claim['lease_token'], 'status': 'succeeded', 'candidates': [refreshed]},
            headers=service,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        with self.Session() as db:
            row = db.get(Candidate, pending_id)
            self.assertEqual(row.status, 'pending')
            self.assertGreater(row.version, prior_version)
            self.assertEqual(row.data.get('description'), 'Updated evidence for remount')

    def test_invalid_evidence_cannot_publish(self):
        with self.Session() as db:
            j=Job(account_id=self.a,request_key='j',query='GP');db.add(j);db.flush()
            c=Candidate(job_id=j.id,source_key='fake',data={**sample(),'evidence':{'title':'invented'}});db.add(c);db.commit();cid=c.id
        self.assertEqual(self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':1}).status_code,422)

    def test_non_malaysia_candidate_cannot_publish(self):
        quote = 'Singapore seminar by Learning Institute in Singapore. Online. 2026-01-01. CPD points 2.'
        payload = {
            **sample('Singapore seminar'),
            'country': 'SG',
            'city': 'Singapore',
            'source_text': quote,
            'evidence': {key: quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']},
        }
        with self.Session() as db:
            j = Job(account_id=self.a, request_key='sg-pub', query='SG')
            db.add(j)
            db.flush()
            c = Candidate(job_id=j.id, source_key='sg-source', data=payload)
            db.add(c)
            db.commit()
            cid = c.id
        blocked = self.client.post('/api/v1/admin/candidates/' + cid + '/review', json={'action': 'publish', 'version': 1})
        self.assertEqual(blocked.status_code, 422)
        titles = [item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']]
        self.assertNotIn('Singapore seminar', titles)

    def test_review_corrections_require_source_excerpts(self):
        quote='Corrected GP Day by Learning Institute in Malaysia Kuala Lumpur online. 2026-01-01. CPD points 2.'
        payload={**sample('Wrong title'),'source_text':quote,'evidence':{key:quote for key in ['title','provider','mode','country','start_date','points','credit_label']}}
        with self.Session() as db:
            j=Job(account_id=self.a,request_key='corr',query='GP');db.add(j);db.flush()
            c=Candidate(job_id=j.id,source_key='corr-source',data=payload);db.add(c);db.commit();cid=c.id
        missing=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':1,'corrections':{'title':'Corrected GP Day'}})
        self.assertEqual(missing.status_code,422)
        published=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':1,'corrections':{'title':'Corrected GP Day'},'evidence':{'title':quote}})
        self.assertEqual(published.status_code,200,published.text)
        found=self.client.get('/api/v1/trainings?period=all&q=Corrected').json()['items']
        self.assertEqual(found[0]['title'],'Corrected GP Day')

    def test_review_corrections_reject_whitespace_only_source_text(self):
        quote = 'Whitespace GP by Learning Institute in Malaysia online. 2026-01-01. CPD points 2.'
        payload = {
            **sample('Whitespace title'),
            'source_text': '   ',
            'evidence': {key: quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']},
        }
        with self.Session() as db:
            j = Job(account_id=self.a, request_key='ws-source', query='GP')
            db.add(j)
            db.flush()
            c = Candidate(job_id=j.id, source_key='ws-source', data=payload)
            db.add(c)
            db.commit()
            cid = c.id
        blocked = self.client.post(
            '/api/v1/admin/candidates/' + cid + '/review',
            json={
                'action': 'publish',
                'version': 1,
                'corrections': {'title': 'Fixed title'},
                'evidence': {'title': quote},
            },
        )
        self.assertEqual(blocked.status_code, 422)
        self.assertIn('Source text is missing', blocked.json()['error']['message'])

    def test_review_cannot_publish_unsafe_registration_url(self):
        quote='Clinic day javascript:alert(1) by Learning Institute in Malaysia Kuala Lumpur online. 2026-01-01. CPD points 2.'
        payload={**sample('Unsafe link'),'source_text':quote,'evidence':{key:quote for key in ['title','provider','mode','country','start_date','points','credit_label']}}
        with self.Session() as db:
            j=Job(account_id=self.a,request_key='unsafe-url',query='GP');db.add(j);db.flush()
            c=Candidate(job_id=j.id,source_key='unsafe-source',data=payload);db.add(c);db.commit();cid=c.id
        result=self.client.post(
            '/api/v1/admin/candidates/'+cid+'/review',
            json={'action':'publish','version':1,'corrections':{'registration_url':'javascript:alert(1)'},'evidence':{'registration_url':'javascript:alert(1)'}},
        )
        self.assertEqual(result.status_code,422)
        titles=[item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']]
        self.assertNotIn('Unsafe link', titles)

    def test_hold_requires_reason_and_stays_out_of_catalogue(self):
        with self.Session() as db:
            j=Job(account_id=self.a,request_key='hold-job',query='GP');db.add(j);db.flush()
            c=Candidate(job_id=j.id,source_key='hold-source',data=sample('Held GP session'));db.add(c);db.commit();cid=c.id
        self.assertEqual(self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'hold','version':1}).status_code,422)
        self.assertEqual(self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','version':1}).status_code,422)
        self.assertEqual(
            self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'hold','version':1,'reason':'ab'}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','version':1,'reason':'ab'}).status_code,
            422,
        )
        held=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'hold','version':1,'reason':'Need MMC confirmation'})
        self.assertEqual(held.status_code,200,held.text)
        self.assertEqual(held.json()['status'],'held')
        queue=self.client.get('/api/v1/admin/candidates').json()['items']
        self.assertEqual([(item['id'],item['status'],item['reason']) for item in queue],[(cid,'held','Need MMC confirmation')])
        titles=[item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']]
        self.assertNotIn('Held GP session',titles)
        published=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':2,'reason':'Source confirmed on the provider page'})
        self.assertEqual(published.status_code,200,published.text)
        self.assertEqual(self.client.get('/api/v1/admin/candidates').json()['items'],[])
        titles=[item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']]
        self.assertIn('Held GP session',titles)

    def test_reject_requires_reason_and_stays_out_of_catalogue(self):
        with self.Session() as db:
            j=Job(account_id=self.a,request_key='reject-job',query='GP');db.add(j);db.flush()
            c=Candidate(job_id=j.id,source_key='reject-source',data=sample('Rejected GP session'));db.add(c);db.commit();cid=c.id
        self.assertEqual(self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','version':1}).status_code,422)
        rejected=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','version':1,'reason':'Not a Malaysia CPD event'})
        self.assertEqual(rejected.status_code,200,rejected.text)
        self.assertEqual(rejected.json()['status'],'rejected')
        self.assertEqual(self.client.get('/api/v1/admin/candidates').json()['items'],[])
        titles=[item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']]
        self.assertNotIn('Rejected GP session',titles)
        # Hold → reject → hold → publish on the same candidate (happy-path state machine).
        reheld=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'hold','version':2,'reason':'Reopened after source check'})
        self.assertEqual(reheld.status_code,200,reheld.text)
        self.assertEqual(reheld.json()['status'],'held')
        queue=self.client.get('/api/v1/admin/candidates').json()['items']
        self.assertEqual([(item['id'],item['status']) for item in queue if item['id']==cid],[(cid,'held')])
        published=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':3,'reason':'Source confirmed after reopen'})
        self.assertEqual(published.status_code,200,published.text)
        self.assertEqual(published.json()['status'],'published')
        titles=[item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']]
        self.assertIn('Rejected GP session',titles)
        blocked=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','version':4,'reason':'Too late'})
        self.assertEqual(blocked.status_code,409)

    def test_doctor_cannot_review_candidates(self):
        with self.Session() as db:
            j=Job(account_id=self.a,request_key='doc-review',query='GP');db.add(j);db.flush()
            c=Candidate(job_id=j.id,source_key='doc-review-source',data=sample('Doctor blocked review'));db.add(c);db.commit();cid=c.id
        self.login('b@example.com')
        denied=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':1})
        self.assertEqual(denied.status_code,403)
        self.login('a@example.com')

    def add_course(self, key, **fields):
        data={**sample(fields.pop('title', 'GP training')), **fields}
        with self.Session() as db:
            course=Course(source_key=key)
            fill_course(course, data)
            db.add(course)
            db.commit()
            return course.id

    def test_filter_semantics(self):
        with self.Session() as db:
            c=db.get(Course,self.course);fill_course(c,{**c.data,'fee':None,'currency':None,'mode':'in_person','city':'Kuala Lumpur','state':'Wilayah Persekutuan','latitude':3.139,'longitude':101.687});db.commit()
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&city=Kuala').json()['total'],1)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&max_fee=0').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&max_fee_myr=0').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&latitude=3.139&longitude=101.687&radius_km=25').json()['total'],1)
        self.assertEqual(self.client.get('/api/v1/trainings?latitude=3').status_code,422)
        self.assertEqual(self.client.get('/api/v1/trainings?latitude=3.139&longitude=101.687&radius_km=15').status_code,422)
        # Radius without coordinates is fail-closed (SDD §10); invalid radius alone is the same contract.
        self.assertEqual(self.client.get('/api/v1/trainings?radius_km=25').status_code,422)
        self.assertEqual(self.client.get('/api/v1/trainings?radius_km=15').status_code,422)
        # Coords without radius default to 25 km nearby.
        defaulted = self.client.get('/api/v1/trainings?period=all&latitude=3.139&longitude=101.687')
        self.assertEqual(defaulted.status_code, 200)
        self.assertEqual(defaulted.json()['applied_filters']['radius_km'], 25)
        self.assertEqual(self.client.get('/api/v1/trainings?page=0').status_code,422)
        self.assertEqual(self.client.get('/api/v1/trainings?page_size=0').status_code,422)
        self.assertEqual(self.client.get('/api/v1/trainings?page_size=51').status_code,422)
        self.assertEqual(self.client.get('/api/v1/me/trainings?page_size=0').status_code,422)
        self.assertEqual(self.client.get('/api/v1/me/trainings?page_size=51').status_code,422)

    def test_catalogue_paginates_and_hides_non_malaysia_or_cancelled(self):
        extra=self.add_course('page-two', title='Second GP seminar', start_date='2026-02-01')
        foreign=self.add_course('sg-event', title='Singapore seminar', country='SG', start_date='2026-03-01')
        first=self.client.get('/api/v1/trainings?period=all&page=1&page_size=1').json()
        second=self.client.get('/api/v1/trainings?period=all&page=2&page_size=1').json()
        self.assertEqual(first['page_size'],1)
        self.assertGreaterEqual(first['total'],2)
        self.assertEqual(len(first['items']),1)
        self.assertEqual(len(second['items']),1)
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        titles={item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']}
        self.assertNotIn('Singapore seminar', titles)
        self.assertEqual(self.client.get('/api/v1/trainings/'+foreign).json()['country'],'SG')
        cancel=self.client.post('/api/v1/admin/trainings/'+extra+'/cancel')
        self.assertEqual(cancel.status_code,200,cancel.text)
        hidden={item['id'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']}
        self.assertNotIn(extra, hidden)
        detail=self.client.get('/api/v1/trainings/'+extra)
        self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.json()['publication_status'],'cancelled')
        self.login('b@example.com')
        self.assertEqual(self.client.post('/api/v1/admin/trainings/'+extra+'/cancel').status_code,403)

    def test_publish_relists_cancelled_session_and_identity_conflict(self):
        from main import source_key
        quote = 'Relist GP Day by Learning Institute in Malaysia Kuala Lumpur online. 2026-04-01. CPD points 2.'
        payload = {
            **sample('Relist GP Day'),
            'start_date': '2026-04-01',
            'source_url': 'https://example.org/relist-gp',
            'source_text': quote,
            'evidence': {key: quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']},
        }
        key = source_key(payload)
        with self.Session() as db:
            course = fill_course(Course(source_key=key), payload)
            course.publication_status = 'cancelled'
            course.cancellation_status = 'cancelled'
            j = Job(account_id=self.a, request_key='relist-job', query='GP')
            db.add_all([course, j])
            db.flush()
            c = Candidate(job_id=j.id, source_key=key, data=payload, resulting_course_id=course.id)
            db.add(c)
            db.commit()
            cid, course_id = c.id, course.id
        hidden = {item['id'] for item in self.client.get('/api/v1/trainings?period=all').json()['items']}
        self.assertNotIn(course_id, hidden)
        published = self.client.post('/api/v1/admin/candidates/' + cid + '/review', json={'action': 'publish', 'version': 1})
        self.assertEqual(published.status_code, 200, published.text)
        listed = self.client.get('/api/v1/trainings?period=all&q=Relist').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['publication_status'], 'published')
        reviewed = self.client.get('/api/v1/trainings?period=all&verification_status=source_reviewed&q=Relist').json()
        self.assertEqual(reviewed['total'], 1)
        self.assertEqual(
            self.client.get('/api/v1/trainings?period=all&publication_status=cancelled').status_code,
            422,
        )
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&mode=webinar').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&difficulty=hard').status_code, 422)
        self.assertEqual(
            self.client.get('/api/v1/trainings?period=all&verification_status=approved').status_code,
            422,
        )
        # Identity conflict: corrections that collide with another listed session's digest key.
        other_quote = 'Other identity by Learning Institute in Malaysia Kuala Lumpur online. 2026-05-01. CPD points 2.'
        other_payload = {
            **sample('Other identity'),
            'start_date': '2026-05-01',
            'source_url': 'https://example.org/other-identity',
            'source_text': other_quote,
            'evidence': {key: other_quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']},
        }
        other_key = source_key(other_payload)
        with self.Session() as db:
            other_course = fill_course(Course(source_key=other_key), other_payload)
            j2 = Job(account_id=self.a, request_key='identity-clash', query='GP')
            db.add_all([other_course, j2])
            db.flush()
            pending = Candidate(
                job_id=j2.id,
                source_key='pending-clash',
                data={**other_payload, 'title': 'Pending clash', 'source_text': other_quote, 'evidence': other_payload['evidence']},
            )
            db.add(pending)
            db.commit()
            pending_id = pending.id
        conflict = self.client.post(
            '/api/v1/admin/candidates/' + pending_id + '/review',
            json={
                'action': 'publish',
                'version': 1,
                'corrections': {'title': 'Other identity'},
                'evidence': {'title': other_quote},
            },
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()['error']['code'], 'conflict')
        self.assertIn('identity', conflict.json()['error']['message'].lower())
        self.assertIn('refresh', conflict.json()['error']['message'].lower())

    def test_publish_relists_cancelled_session_without_matched_course_id(self):
        """Corrections that realign to a cancelled identity re-list it (no resulting_course_id)."""
        from main import source_key
        quote = 'Relist Drift GP by Learning Institute in Malaysia Kuala Lumpur online. 2026-04-02. CPD points 2.'
        cancelled_payload = {
            **sample('Relist Drift GP'),
            'start_date': '2026-04-02',
            'source_url': 'https://example.org/relist-drift',
            'source_text': quote,
            'evidence': {key: quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']},
        }
        cancelled_key = source_key(cancelled_payload)
        pending_payload = {
            **cancelled_payload,
            'title': 'Drifted pending title',
            'evidence': {**cancelled_payload['evidence'], 'title': quote},
        }
        with self.Session() as db:
            course = fill_course(Course(source_key=cancelled_key), cancelled_payload)
            course.publication_status = 'cancelled'
            course.cancellation_status = 'cancelled'
            j = Job(account_id=self.a, request_key='relist-drift-job', query='GP')
            db.add_all([course, j])
            db.flush()
            # No resulting_course_id / matched id — identity comes only from corrections.
            c = Candidate(job_id=j.id, source_key='pending-drift-key', data=pending_payload)
            db.add(c)
            db.commit()
            cid, course_id = c.id, course.id
        published = self.client.post(
            '/api/v1/admin/candidates/' + cid + '/review',
            json={
                'action': 'publish',
                'version': 1,
                'corrections': {'title': 'Relist Drift GP'},
                'evidence': {'title': quote},
            },
        )
        self.assertEqual(published.status_code, 200, published.text)
        listed = self.client.get('/api/v1/trainings?period=all&q=Relist%20Drift').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['id'], course_id)
        self.assertEqual(listed['items'][0]['publication_status'], 'published')

    def test_publish_relists_cancellation_status_drift(self):
        """cancellation_status=cancelled with published publication_status must re-list (listed_filter parity)."""
        from main import source_key
        quote = (
            'Drift Relist GP by Learning Institute in Malaysia Kuala Lumpur online. '
            '2026-07-01. CPD points 2.'
        )
        payload = {
            **sample('Drift Relist GP'),
            'start_date': '2026-07-01',
            'source_url': 'https://example.org/drift-relist-gp',
            'source_text': quote,
            'evidence': {
                key: quote
                for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']
            },
        }
        key = source_key(payload)
        with self.Session() as db:
            course = fill_course(Course(source_key=key), payload)
            course.publication_status = 'published'
            course.cancellation_status = 'cancelled'
            j = Job(account_id=self.a, request_key='drift-relist-job', query='GP')
            db.add_all([course, j])
            db.flush()
            c = Candidate(job_id=j.id, source_key=key, data=payload, resulting_course_id=course.id)
            db.add(c)
            db.commit()
            cid, course_id = c.id, course.id
        hidden = self.client.get('/api/v1/trainings?period=all&q=Drift%20Relist').json()
        self.assertEqual(hidden['total'], 0)
        published = self.client.post(
            '/api/v1/admin/candidates/' + cid + '/review',
            json={'action': 'publish', 'version': 1},
        )
        self.assertEqual(published.status_code, 200, published.text)
        listed = self.client.get('/api/v1/trainings?period=all&q=Drift%20Relist').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['id'], course_id)
        self.assertEqual(listed['items'][0]['publication_status'], 'published')
        self.assertEqual(listed['items'][0]['cancellation_status'], 'active')

    def test_publish_matched_course_relists_cancelled_identity_conflict(self):
        """Matched-course publish that drifts onto a cancelled identity must re-list it (not 409)."""
        from main import source_key
        matched_quote = (
            'Matched Relist GP by Learning Institute in Malaysia Kuala Lumpur online. '
            '2026-06-01. CPD points 2. Also Cancelled Target GP on 2026-06-02.'
        )
        cancelled_quote = matched_quote
        shared_url = 'https://example.org/shared-relist-page'
        matched_payload = {
            **sample('Matched Relist GP'),
            'start_date': '2026-06-01',
            'source_url': shared_url,
            'source_text': matched_quote,
            'evidence': {
                key: matched_quote
                for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']
            },
        }
        cancelled_payload = {
            **sample('Cancelled Target GP'),
            'start_date': '2026-06-02',
            'source_url': shared_url,
            'source_text': cancelled_quote,
            'evidence': {
                key: cancelled_quote
                for key in ['title', 'provider', 'mode', 'country', 'start_date', 'points', 'credit_label']
            },
        }
        matched_key = source_key(matched_payload)
        cancelled_key = source_key(cancelled_payload)
        with self.Session() as db:
            matched = fill_course(Course(source_key=matched_key), matched_payload)
            cancelled = fill_course(Course(source_key=cancelled_key), cancelled_payload)
            cancelled.publication_status = 'cancelled'
            cancelled.cancellation_status = 'cancelled'
            j = Job(account_id=self.a, request_key='matched-cancel-relist', query='GP')
            db.add_all([matched, cancelled, j])
            db.flush()
            # Held against the live matched course; corrections realign to the cancelled identity.
            c = Candidate(
                job_id=j.id,
                source_key=matched_key,
                data={
                    **matched_payload,
                    '_matched_course_id': matched.id,
                },
                status='held',
                resulting_course_id=matched.id,
                version=1,
            )
            db.add(c)
            db.commit()
            cid, matched_id, cancelled_id = c.id, matched.id, cancelled.id
        published = self.client.post(
            '/api/v1/admin/candidates/' + cid + '/review',
            json={
                'action': 'publish',
                'version': 1,
                'corrections': {
                    'title': 'Cancelled Target GP',
                    'start_date': '2026-06-02',
                },
                'evidence': {
                    'title': 'Cancelled Target GP',
                    'start_date': '2026-06-02',
                },
            },
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()['resulting_course_id'], cancelled_id)
        listed = self.client.get('/api/v1/trainings?period=all&q=Cancelled%20Target').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['id'], cancelled_id)
        self.assertEqual(listed['items'][0]['publication_status'], 'published')
        with self.Session() as db:
            row = db.get(Candidate, cid)
            self.assertEqual(row.source_key, cancelled_key)
            self.assertEqual(row.resulting_course_id, cancelled_id)
            # Matched live row stays published under its original identity (not overwritten).
            prior = db.get(Course, matched_id)
            self.assertEqual(prior.source_key, matched_key)
            self.assertEqual(prior.publication_status, 'published')

    def test_nearby_keeps_city_matches_without_coordinates(self):
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'mode':'in_person','city':'Kuala Lumpur','state':'Wilayah Persekutuan','latitude':3.139,'longitude':101.687})
            db.commit()
        self.add_course('no-coords', title='Clinic workshop', mode='in_person', city='Kuala Lumpur', state='Wilayah Persekutuan', latitude=None, longitude=None, start_date='2026-01-01')
        nearby=self.client.get('/api/v1/trainings?period=all&city=Kuala&latitude=3.139&longitude=101.687&radius_km=25').json()
        self.assertEqual(nearby['total'], 2)
        untitled={item['title']: item['distance_km'] for item in nearby['items']}
        self.assertIsNotNone(untitled['GP training'])
        self.assertIsNone(untitled['Clinic workshop'])

    def test_nearby_sorts_by_distance_when_coordinates_present(self):
        # Farther venue starts earlier so date-only order would put it first; near-me must prefer distance.
        with self.Session() as db:
            c = db.get(Course, self.course)
            fill_course(
                c,
                {
                    **c.data,
                    'title': 'Far KL hall',
                    'mode': 'in_person',
                    'city': 'Kuala Lumpur',
                    'state': 'Wilayah Persekutuan',
                    'latitude': 3.20,
                    'longitude': 101.70,
                    'start_date': '2026-01-01',
                },
            )
            db.commit()
        self.add_course(
            'near-venue',
            title='Near KL clinic',
            mode='in_person',
            city='Kuala Lumpur',
            state='Wilayah Persekutuan',
            latitude=3.140,
            longitude=101.688,
            start_date='2026-06-01',
        )
        self.add_course(
            'city-only',
            title='City match no coords',
            mode='in_person',
            city='Kuala Lumpur',
            state='Wilayah Persekutuan',
            latitude=None,
            longitude=None,
            start_date='2026-02-01',
        )
        nearby = self.client.get(
            '/api/v1/trainings?period=all&city=Kuala&latitude=3.139&longitude=101.687&radius_km=25&page_size=10'
        ).json()
        titles = [item['title'] for item in nearby['items']]
        self.assertEqual(titles[0], 'Near KL clinic')
        self.assertEqual(titles[1], 'Far KL hall')
        self.assertEqual(titles[-1], 'City match no coords')
        self.assertLess(nearby['items'][0]['distance_km'], nearby['items'][1]['distance_km'])
        self.assertIsNone(nearby['items'][-1]['distance_km'])

    def test_nearby_includes_online_only_when_mode_allows_it(self):
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'mode':'online','city':None,'latitude':None,'longitude':None})
            db.commit()
        in_person=self.client.get('/api/v1/trainings?period=all&mode=in_person&latitude=3.139&longitude=101.687&radius_km=25').json()
        any_mode=self.client.get('/api/v1/trainings?period=all&mode=online&latitude=3.139&longitude=101.687&radius_km=25').json()
        self.assertEqual(in_person['total'], 0)
        self.assertEqual(any_mode['total'], 1)
        self.assertIsNone(any_mode['items'][0]['distance_km'])
        # Empty mode is "Any format": Near me still includes online (online/hybrid inclusion via Any).
        any_format=self.client.get('/api/v1/trainings?period=all&latitude=3.139&longitude=101.687&radius_km=25').json()
        self.assertEqual(any_format['total'], 1)
        self.assertIsNone(any_format['items'][0]['distance_km'])
        # Hybrid + Near me includes online (SDD §8 / Discover and /live copy); hybrid alone does not.
        self.add_course(
            'hybrid-near-venue',
            title='Hybrid KL day',
            mode='hybrid',
            city='Kuala Lumpur',
            latitude=3.140,
            longitude=101.688,
            start_date='2026-06-01',
        )
        hybrid_near = self.client.get(
            '/api/v1/trainings?period=all&mode=hybrid&latitude=3.139&longitude=101.687&radius_km=25'
        ).json()
        hybrid_near_titles = {item['title'] for item in hybrid_near['items']}
        self.assertIn('GP training', hybrid_near_titles)
        self.assertIn('Hybrid KL day', hybrid_near_titles)
        online_row = next(item for item in hybrid_near['items'] if item['title'] == 'GP training')
        self.assertIsNone(online_row['distance_km'])
        hybrid_only = self.client.get('/api/v1/trainings?period=all&mode=hybrid').json()
        hybrid_only_titles = {item['title'] for item in hybrid_only['items']}
        self.assertNotIn('GP training', hybrid_only_titles)
        self.assertIn('Hybrid KL day', hybrid_only_titles)
        # Discover/workspace often keep profile city with Near me; city must not hide pure online.
        hybrid_near_city = self.client.get(
            '/api/v1/trainings?period=all&mode=hybrid&city=Kuala&latitude=3.139&longitude=101.687&radius_km=25'
        ).json()
        hybrid_near_city_titles = {item['title'] for item in hybrid_near_city['items']}
        self.assertIn('GP training', hybrid_near_city_titles)
        self.assertIn('Hybrid KL day', hybrid_near_city_titles)
        any_near_city = self.client.get(
            '/api/v1/trainings?period=all&city=Kuala&latitude=3.139&longitude=101.687&radius_km=25'
        ).json()
        self.assertIn('GP training', {item['title'] for item in any_near_city['items']})
        # City without Near me still filters online by city (null city stays out).
        hybrid_city_only = self.client.get('/api/v1/trainings?period=all&mode=hybrid&city=Kuala').json()
        self.assertNotIn('GP training', {item['title'] for item in hybrid_city_only['items']})

    def test_unknown_dates_and_fees_need_explicit_inclusion(self):
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'start_date':None,'fee':None,'currency':None,'mode':'online'})
            db.commit()
        upcoming=self.client.get('/api/v1/trainings?period=upcoming').json()
        included=self.client.get('/api/v1/trainings?period=upcoming&include_unknown=true').json()
        fee_filter=self.client.get('/api/v1/trainings?period=all&max_fee_myr=100').json()
        fee_with_unknown=self.client.get('/api/v1/trainings?period=all&max_fee_myr=100&include_unknown=true').json()
        self.assertEqual(upcoming['total'], 0)
        self.assertEqual(included['total'], 1)
        self.assertEqual(fee_filter['total'], 0)
        self.assertEqual(fee_with_unknown['total'], 1)

    def test_min_points_respects_include_unknown(self):
        with self.Session() as db:
            known=db.get(Course,self.course)
            fill_course(known,{**known.data,'points':5,'credit_label':'CPD','mode':'online','start_date':'2026-06-01','fee':50,'currency':'MYR'})
            db.commit()
        self.add_course(
            'demo-unknown-points',
            title='Unknown points clinic day',
            points=None,
            credit_label=None,
            start_date='2026-06-02',
            mode='online',
            fee=40,
            currency='MYR',
            source_url='https://example.org/unknown-points',
        )
        strict=self.client.get('/api/v1/trainings?period=all&min_points=3').json()
        with_unknown=self.client.get('/api/v1/trainings?period=all&min_points=3&include_unknown=true').json()
        self.assertEqual(strict['total'], 1)
        self.assertEqual(strict['items'][0]['points'], 5)
        self.assertEqual(strict['applied_filters']['min_points'], 3)
        self.assertEqual(with_unknown['total'], 2)
        self.assertTrue(with_unknown['applied_filters']['include_unknown'])

    def test_myr_fee_filter_excludes_other_currencies(self):
        with self.Session() as db:
            c = db.get(Course, self.course)
            fill_course(c, {**c.data, 'fee': 80, 'currency': 'SGD', 'mode': 'online', 'start_date': '2026-01-01'})
            db.commit()
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&max_fee_myr=200').json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&max_fee_myr=200&include_unknown=true').json()['total'], 0)
        with self.Session() as db:
            c = db.get(Course, self.course)
            fill_course(c, {**c.data, 'fee': 80, 'currency': 'MYR'})
            db.commit()
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&max_fee_myr=200').json()['total'], 1)

    def test_state_and_date_range_filters_and_applied_filters(self):
        with self.Session() as db:
            c=db.get(Course,self.course)
            fill_course(c,{**c.data,'city':'Petaling Jaya','state':'Selangor','start_date':'2026-03-15','mode':'in_person'})
            db.commit()
        missed=self.client.get('/api/v1/trainings?period=all&state=Penang').json()
        matched=self.client.get('/api/v1/trainings?period=all&state=Selangor&date_from=2026-03-01&date_to=2026-03-31').json()
        outside=self.client.get('/api/v1/trainings?period=all&date_from=2026-04-01&date_to=2026-04-30').json()
        self.assertEqual(missed['total'], 0)
        self.assertEqual(matched['total'], 1)
        self.assertEqual(outside['total'], 0)
        self.assertEqual(matched['applied_filters']['state'], 'Selangor')
        self.assertEqual(matched['applied_filters']['date_from'], '2026-03-01')

    def test_schema_upgrade_backfills_filter_columns(self):
        with self.Session() as db:
            db.add(SchemaVersion(version=1))
            course=db.get(Course,self.course)
            course.title=''
            course.city=None
            course.data={**course.data,'title':'Backfilled GP','city':'Johor Bahru'}
            db.commit()
        with self.Session() as db:
            migrate_schema(db)
            stored=db.get(Course,self.course)
            self.assertEqual((stored.title, stored.city), ('Backfilled GP','Johor Bahru'))
            self.assertEqual(max(v.version for v in db.query(SchemaVersion).all()), 17)
            self.assertIn('identity_issuer', {c['name'] for c in inspect(db.get_bind()).get_columns('accounts')})
            self.assertIn('verification_status', {c['name'] for c in inspect(db.get_bind()).get_columns('courses')})
            self.assertIn('publication_status', {c['name'] for c in inspect(db.get_bind()).get_columns('courses')})
            self.assertIn('end_date', {c['name'] for c in inspect(db.get_bind()).get_columns('courses')})
            self.assertIn('review_reason', {c['name'] for c in inspect(db.get_bind()).get_columns('course_candidates')})
            self.assertIn('signup_status', {c['name'] for c in inspect(db.get_bind()).get_columns('doctor_records')})
            self.assertIn('state', {c['name'] for c in inspect(db.get_bind()).get_columns('accounts')})
            self.assertIn('max_results', {c['name'] for c in inspect(db.get_bind()).get_columns('ingestion_jobs')})
            self.assertIn('attempt', {c['name'] for c in inspect(db.get_bind()).get_columns('ingestion_jobs')})
            self.assertIn('version', {c['name'] for c in inspect(db.get_bind()).get_columns('course_candidates')})
            self.assertIn('attendance_status', {c['name'] for c in inspect(db.get_bind()).get_columns('doctor_records')})
            self.assertIn('latitude', {c['name'] for c in inspect(db.get_bind()).get_columns('accounts')})
            self.assertIn('location_consent_at', {c['name'] for c in inspect(db.get_bind()).get_columns('accounts')})
            self.assertIn('created_at', {c['name'] for c in inspect(db.get_bind()).get_columns('accounts')})
            self.assertIn('event_count', {c['name'] for c in inspect(db.get_bind()).get_columns('digest_sends')})
            self.assertIn('resulting_course_id', {c['name'] for c in inspect(db.get_bind()).get_columns('course_candidates')})
            self.assertIn('schema_version', {c['name'] for c in inspect(db.get_bind()).get_columns('course_candidates')})
            self.assertIn('source_document_id', {c['name'] for c in inspect(db.get_bind()).get_columns('field_evidence')})
            tables = inspect(db.get_bind()).get_table_names()
            self.assertIn('fail_count', {c['name'] for c in inspect(db.get_bind()).get_columns('digest_preferences')})
            self.assertIn('digest_preferences', tables)
            self.assertIn('affiliation_certificates', tables)
            self.assertIn('record_history', tables)
            self.assertIn('field_evidence', tables)
            self.assertIn('source_documents', tables)

    def test_catalogue_filters_use_columns_not_json(self):
        with self.Session() as db:
            course=db.get(Course,self.course)
            course.data={**course.data,'city':'Penang','state':'Penang','mode':'in_person','start_date':'2026-01-01'}
            course.title='GP training'
            course.provider='Learning Institute'
            course.city='Ipoh'
            course.state='Perak'
            course.mode='in_person'
            course.start_date='2026-03-15'
            db.commit()
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&city=Ipoh').json()['total'],1)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&city=Penang').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/trainings?period=all&state=Perak&date_from=2026-03-01&date_to=2026-03-31').json()['total'],1)

    def test_publish_stores_filter_columns(self):
        header={'Idempotency-Key':'publish-columns-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP course'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        quote='Ipoh clinic day by Learning Institute in Malaysia Ipoh Perak in person. 2026-06-01. CPD points 2.'
        payload=sample('Ipoh clinic day')
        payload.update(source_text=quote, mode='in_person', city='Ipoh', state='Perak', start_date='2026-06-01', evidence={key:quote for key in ['title','provider','mode','country','start_date','points','credit_label','city','state']})
        self.client.post('/internal/v1/jobs/'+claim['id']+'/complete',json={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[payload]},headers=service)
        cid=self.client.get('/api/v1/admin/candidates').json()['items'][0]['id']
        self.assertEqual(self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':1}).status_code,200)
        found=self.client.get('/api/v1/trainings?period=all&city=Ipoh').json()
        self.assertGreaterEqual(found['total'],1)
        self.assertTrue(any(item['title']=='Ipoh clinic day' and item['city']=='Ipoh' for item in found['items']))
        with self.Session() as db:
            stored=db.query(Course).filter(Course.title=='Ipoh clinic day').one()
            self.assertEqual((stored.city, stored.state, stored.mode), ('Ipoh','Perak','in_person'))

    def test_interrupted_job_requires_explicit_retry(self):

        header={'Idempotency-Key':'retry-job-key'}
        job=self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP course'},headers=header).json()
        with self.Session() as db:
            stored=db.get(Job, job['id'])
            stored.status='interrupted'
            stored.lease_token='stale'
            stored.lease_until=0
            stored.result={'usage':{'tavily_credits':3,'model_tokens':90},'warnings':['stale attempt']}
            db.commit()
        service={'Authorization':'Bearer test-service-token'}
        self.assertEqual(self.client.post('/internal/v1/jobs/claim',headers=service).status_code,204)
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': False, 'reachable': True, 'status': 'ready'}):
            blocked=self.client.post('/api/v1/admin/ingestion-jobs/'+job['id']+'/retry')
        self.assertEqual(blocked.status_code,409,blocked.text)
        self.assertEqual(
            blocked.json()['error']['message'],
            'Live discovery stays off until Tavily and the open-weight model are ready.',
        )
        retry=self.client.post('/api/v1/admin/ingestion-jobs/'+job['id']+'/retry')
        self.assertEqual(retry.status_code,202,retry.text)
        self.assertEqual(retry.json()['status'],'queued')
        self.assertEqual(retry.json()['attempt'],2)
        self.assertIsNone(retry.json().get('result'))
        claim=self.client.post('/internal/v1/jobs/claim',headers=service)
        self.assertEqual(claim.status_code,200)
        self.assertEqual(claim.json()['id'], job['id'])

    def test_complete_rejects_blank_lease_and_failed_with_candidates(self):
        service = {'Authorization': 'Bearer test-service-token'}
        header = {'Idempotency-Key': 'complete-validate-key'}
        self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP complete validate'}, headers=header)
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        blank = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': '   ', 'status': 'failed', 'candidates': [], 'sources': []},
            headers=service,
        )
        self.assertEqual(blank.status_code, 422, blank.text)
        failed_with_candidates = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={
                'lease_token': claim['lease_token'],
                'status': 'failed',
                'candidates': [sample('Must stay partial')],
                'sources': [],
            },
            headers=service,
        )
        self.assertEqual(failed_with_candidates.status_code, 422, failed_with_candidates.text)
        with self.Session() as db:
            row = db.get(Job, claim['id'])
            row.lease_token = None
            db.commit()
        empty_stored = self.client.post(
            '/internal/v1/jobs/' + claim['id'] + '/complete',
            json={'lease_token': '', 'status': 'failed', 'candidates': [], 'sources': []},
            headers=service,
        )
        # Blank body token is 422; empty stored token cannot match even if validation were skipped.
        self.assertIn(empty_stored.status_code, (409, 422), empty_stored.text)

    def test_cancelled_signup_keeps_attendance_and_history(self):
        first = self.save(signup_status='signed_up')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['signup_status'], 'signed_up')
        cancelled = self.save(signup_status='cancelled', attended=True, attended_on=today().isoformat(), version=1)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        body = cancelled.json()
        self.assertEqual(body['signup_status'], 'cancelled')
        self.assertFalse(body['signed_up'])
        self.assertTrue(body['attended'])
        self.assertEqual(body['attendance_status'], 'attended')
        history = self.client.get('/api/v1/me/trainings/' + self.course + '/history')
        self.assertEqual(history.status_code, 200, history.text)
        self.assertGreaterEqual(len(history.json()['items']), 1)
        progress = self.client.get('/api/v1/me/progress').json()
        self.assertEqual(progress['attended'], 1)
        self.assertEqual(progress['signed_up'], 0)

    def test_cancelled_signup_requires_prior_signed_up(self):
        blocked = self.client.put(
            '/api/v1/me/trainings/' + self.course,
            json={'signup_status': 'cancelled', 'attended': False, 'attendance_status': 'not_recorded', 'version': 0},
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertIn('Cancel sign-up only after', blocked.json()['error']['message'])
        created = self.client.put(
            '/api/v1/me/trainings/' + self.course,
            json={'signup_status': 'not_recorded', 'attended': False, 'attendance_status': 'not_recorded', 'version': 0},
        )
        self.assertEqual(created.status_code, 200, created.text)
        still = self.client.put(
            '/api/v1/me/trainings/' + self.course,
            json={'signup_status': 'cancelled', 'attended': False, 'attendance_status': 'not_recorded', 'version': 1},
        )
        self.assertEqual(still.status_code, 422, still.text)

    def test_omitted_signup_status_does_not_invent_cancel(self):
        """PUT without signup_status must not invent cancel when signed_up defaults false."""
        first = self.save(signup_status='signed_up', attended=False, attended_on=None, points=None)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['signup_status'], 'signed_up')
        # Omit signup_status; pydantic defaults signed_up=false — clear to not_recorded, never cancel.
        cleared = self.client.put(
            '/api/v1/me/trainings/' + self.course,
            json={
                'attended': False,
                'attendance_status': 'not_recorded',
                'credit_label': 'CPD',
                'version': first.json()['version'],
            },
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()['signup_status'], 'not_recorded')
        self.assertFalse(cleared.json()['signed_up'])
        # Explicit cancel still works after a real signed_up.
        again = self.save(signup_status='signed_up', attended=False, attended_on=None, points=None, version=cleared.json()['version'])
        self.assertEqual(again.status_code, 200, again.text)
        cancelled = self.save(
            signup_status='cancelled',
            attended=False,
            attended_on=None,
            points=None,
            version=again.json()['version'],
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()['signup_status'], 'cancelled')

    def test_personal_notes_reject_over_max_length(self):
        too_long = 'n' * 5001
        blocked = self.save(notes=too_long)
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertEqual(blocked.json()['error']['code'], 'invalid')
        ok = self.save(notes='n' * 5000)
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(len(ok.json()['notes']), 5000)

    def test_profile_city_state_and_me_fields(self):
        body={'name':'Doctor A','city':'Petaling Jaya','state':'Selangor','bio':'Family medicine','public_enabled':False}
        saved=self.client.patch('/api/v1/me',json=body)
        self.assertEqual(saved.status_code,200,saved.text)
        me=self.client.get('/api/v1/me').json()
        self.assertEqual((me['city'],me['state']),('Petaling Jaya','Selangor'))
        self.assertNotIn('password_hash',me)
        blank_name=self.client.patch('/api/v1/me',json={**body,'name':'  '})
        self.assertEqual(blank_name.status_code,422)
        padded=self.client.patch('/api/v1/me',json={**body,'name':'  Doctor A  ','city':'  Petaling Jaya  ','public_enabled':True})
        self.assertEqual(padded.status_code,200,padded.text)
        self.assertEqual(padded.json()['name'],'Doctor A')
        self.assertEqual(padded.json()['city'],'Petaling Jaya')
        self.assertTrue(padded.json()['public_enabled'])
        half=self.client.patch('/api/v1/me',json={**body,'latitude':3.139})
        self.assertEqual(half.status_code,422)
        # JSON booleans must not invent near-me coordinates (True→1.0 / False→0.0).
        for lat, lon in ((True, True), (False, False), (True, 101.687), (3.139, False)):
            invent = self.client.patch('/api/v1/me', json={**body, 'latitude': lat, 'longitude': lon})
            self.assertEqual(invent.status_code, 422, invent.text)
        located=self.client.patch('/api/v1/me',json={**body,'latitude':3.139,'longitude':101.687})
        self.assertEqual(located.status_code,200,located.text)
        self.assertEqual(located.json()['latitude'],3.139)
        self.assertTrue(located.json()['location_consent_at'])
        cleared=self.client.patch('/api/v1/me',json=body)
        self.assertEqual(cleared.json()['latitude'],None)
        self.assertIsNone(cleared.json()['location_consent_at'])

    def test_two_sessions_on_one_page_stay_distinct(self):
        from main import source_key
        page='https://example.org/afpm-weekend'
        first={**sample('Saturday workshop'),'start_date':'2026-08-01','source_url':page}
        second={**sample('Sunday workshop'),'start_date':'2026-08-02','source_url':page}
        self.assertNotEqual(source_key(first),source_key(second))
        header={'Idempotency-Key':'two-sessions-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'AFPM weekend'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        quote='Saturday workshop Sunday workshop by Learning Institute in Malaysia Kuala Lumpur online. 2026-08-01. 2026-08-02. CPD points 2.'
        first['source_text']=second['source_text']=quote
        first['evidence']=second['evidence']={key:quote for key in ['title','provider','mode','country','start_date','points','credit_label']}
        complete=self.client.post('/internal/v1/jobs/'+claim['id']+'/complete',json={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[first,second]},headers=service)
        self.assertEqual(complete.status_code,200,complete.text)
        queue=self.client.get('/api/v1/admin/candidates').json()['items']
        self.assertEqual(len(queue),2)
        for item in queue:
            self.assertEqual(self.client.post('/api/v1/admin/candidates/'+item['id']+'/review',json={'action':'publish','version':1}).status_code,200)
        titles=sorted(item['title'] for item in self.client.get('/api/v1/trainings?period=all').json()['items'] if 'workshop' in item['title'])
        self.assertEqual(titles,['Saturday workshop','Sunday workshop'])

    def test_opening_detail_does_not_create_a_record(self):
        before = self.client.get('/api/v1/me/trainings').json()['items']
        detail = self.client.get('/api/v1/trainings/' + self.course)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIsNone(detail.json()['record'])
        self.assertNotIn('source_text', detail.json())
        self.assertNotIn('model_license_url', detail.json())
        after = self.client.get('/api/v1/me/trainings').json()['items']
        self.assertEqual(len(before), len(after))

    def test_progress_year_boundary(self):
        with self.Session() as db:
            course = db.get(Course, self.course)
            fill_course(course, {**course.data, 'start_date': '2025-12-01'})
            db.commit()
        self.assertEqual(self.save(attended_on='2025-12-31').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/me/progress?year=2025').json()['attended'], 1)
        self.assertEqual(self.client.get('/api/v1/me/progress?year=2026').json()['attended'], 0)
        # year=0 must not falsy-coerce into the current calendar year (match certificates/CSV).
        self.assertEqual(self.client.get('/api/v1/me/progress?year=0').status_code, 422)

    def test_progress_signed_up_scopes_to_course_year(self):
        with self.Session() as db:
            course = db.get(Course, self.course)
            fill_course(course, {**course.data, 'start_date': '2025-06-01'})
            db.commit()
        self.assertEqual(self.save(signup_status='signed_up', attended=False, attended_on=None, points=None).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/me/progress?year=2025').json()['signed_up'], 1)
        self.assertEqual(self.client.get('/api/v1/me/progress?year=2026').json()['signed_up'], 0)

    def test_progress_signed_up_ignores_cancelled_when_bool_drifts(self):
        """Open signed_up totals must not count cancelled rows if legacy signed_up bool drifted."""
        with self.Session() as db:
            course = db.get(Course, self.course)
            fill_course(course, {**course.data, 'start_date': '2025-06-01'})
            db.commit()
        first = self.save(signup_status='signed_up', attended=False, attended_on=None, points=None)
        self.assertEqual(first.status_code, 200, first.text)
        cancelled = self.save(signup_status='cancelled', attended=False, attended_on=None, points=None, version=1)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        with self.Session() as db:
            record = db.query(Record).filter_by(account_id=self.a, course_id=self.course).one()
            record.signed_up = True
            record.signup_status = 'cancelled'
            db.commit()
        self.assertEqual(self.client.get('/api/v1/me/progress?year=2025').json()['signed_up'], 0)
        self.assertEqual(self.client.get('/api/v1/me/progress?year=2026').json()['signed_up'], 0)

    def test_radius_boundary_excludes_far_venues(self):
        with self.Session() as db:
            c = db.get(Course, self.course)
            fill_course(c, {**c.data, 'mode': 'in_person', 'city': 'Kuala Lumpur', 'latitude': 3.139, 'longitude': 101.687})
            db.commit()
        self.add_course(
            'far-venue',
            title='Far clinic day',
            mode='in_person',
            city='Kuantan',
            latitude=3.807,
            longitude=103.326,
            start_date='2026-01-01',
        )
        inside = self.client.get('/api/v1/trainings?period=all&mode=in_person&latitude=3.139&longitude=101.687&radius_km=25').json()
        titles = [item['title'] for item in inside['items']]
        self.assertIn('GP training', titles)
        self.assertNotIn('Far clinic day', titles)

    def test_operator_integrations_omit_secrets(self):
        blank = {
            'MODEL_ID': '',
            'MODEL_PUBLISHER': '',
            'MODEL_HOST': '',
            'MODEL_WEIGHTS_URL': '',
            'MODEL_LICENSE_URL': '',
            'MODEL_MAX_INPUT_CHARS': '',
            'MODEL_MAX_OUTPUT_TOKENS': '',
            'MODEL_API_KEY': '',
            'MODEL_OPEN_WEIGHT_CONFIRMED': 'false',
        }
        with patch.dict(os.environ, blank, clear=False):
            result=self.client.get('/api/v1/admin/integrations')
        self.assertEqual(result.status_code,200,result.text)
        body=result.json()
        self.assertEqual(body['model_id'], 'nvidia/nemotron-3-super-120b-a12b')
        self.assertEqual(body['model_publisher'], 'NVIDIA')
        self.assertEqual(body['model_host'], 'Nebius Token Factory')
        self.assertTrue(body['model_identity_provisional'])
        self.assertTrue(body['model_publisher_provisional'])
        self.assertTrue(body['model_host_provisional'])
        self.assertTrue(body['model_caps_configured'])
        self.assertTrue(body['model_caps_provisional'])
        self.assertTrue(body['model_weights_provisional'])
        self.assertTrue(body['model_license_provisional'])
        self.assertEqual(body['model_max_input_chars'], 12000)
        self.assertEqual(body['model_max_output_tokens'], 4000)
        self.assertFalse(body['model_open_weight_confirmed'])
        self.assertFalse(body['model_key_configured'])
        self.assertIn('model_key_configured', body)
        self.assertIn('model_caps_configured', body)
        self.assertIn('model_publisher', body)
        self.assertIn('model_host', body)
        self.assertIn('model_max_input_chars', body)
        self.assertIn('model_max_output_tokens', body)
        self.assertIn('catalogue_auto_publish_new', body)
        self.assertFalse(body['catalogue_auto_publish_new'])
        with patch.dict(os.environ, {**blank, 'MODEL_ID': 'Qwen/owner-chosen'}, clear=False):
            owned = self.client.get('/api/v1/admin/integrations').json()
        self.assertEqual(owned['model_id'], 'Qwen/owner-chosen')
        self.assertFalse(owned['model_identity_provisional'])
        self.assertTrue(owned['model_publisher_provisional'])
        self.assertTrue(owned['model_host_provisional'])
        with patch.dict(os.environ, {**blank, 'MODEL_PUBLISHER': 'Owner Press', 'MODEL_HOST': 'Owner Host'}, clear=False):
            branded = self.client.get('/api/v1/admin/integrations').json()
        self.assertFalse(branded['model_publisher_provisional'])
        self.assertFalse(branded['model_host_provisional'])
        with patch.dict(os.environ, {**blank, 'MODEL_MAX_INPUT_CHARS': '8000', 'MODEL_MAX_OUTPUT_TOKENS': '2000'}, clear=False):
            capped = self.client.get('/api/v1/admin/integrations').json()
        self.assertFalse(capped['model_caps_provisional'])
        self.assertEqual(capped['model_max_input_chars'], 8000)
        with patch.dict(os.environ, {**blank, 'MODEL_WEIGHTS_URL': 'https://example.org/weights', 'MODEL_LICENSE_URL': 'https://example.org/license'}, clear=False):
            linked = self.client.get('/api/v1/admin/integrations').json()
        self.assertFalse(linked['model_weights_provisional'])
        self.assertFalse(linked['model_license_provisional'])
        self.assertEqual(linked['model_weights_url'], 'https://example.org/weights')
        with patch.dict(os.environ, {**blank, 'MODEL_WEIGHTS_URL': 'http://127.0.0.1/weights', 'MODEL_LICENSE_URL': 'javascript:alert(1)'}, clear=False):
            unsafe = self.client.get('/api/v1/admin/integrations').json()
        self.assertIsNone(unsafe['model_weights_url'])
        self.assertIsNone(unsafe['model_license_url'])
        blob=result.text
        self.assertNotIn('TAVILY_API_KEY', blob)
        self.assertNotIn('MODEL_API_KEY', blob)
        self.assertNotIn('TYPESAFE_API_KEY', blob)
        self.assertNotIn('test-service-token', blob)
        self.login('b@example.com')
        self.assertEqual(self.client.get('/api/v1/admin/integrations').status_code,403)

    def test_operator_services_report_database_owner_without_secrets(self):
        self.scraper_ready.stop()
        try:
            with patch.dict(os.environ, {'SCRAPER_HEALTH_URL': ''}, clear=False):
                result = self.client.get('/api/v1/admin/services')
        finally:
            self.scraper_ready.start()
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body['backend'], 'ready')
        self.assertEqual(body['database'], 'ready')
        self.assertEqual(body['database_owner'], 'backend')
        self.assertEqual(body['scraper']['status'], 'unconfigured')
        self.assertFalse(body['scraper']['reachable'])
        self.assertFalse(body['paid_scrape_ready'])
        self.assertNotIn('TAVILY_API_KEY', result.text)
        self.assertNotIn('MODEL_API_KEY', result.text)
        self.assertNotIn('test-service-token', result.text)
        self.login('b@example.com')
        self.assertEqual(self.client.get('/api/v1/admin/services').status_code, 403)

    def test_operator_services_read_scraper_ready_flags(self):
        class FakeResponse:
            def read(self):
                return b'{"status":"ready","tavily_configured":true,"model_ready":false,"missing":["SECRET"]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        self.scraper_ready.stop()
        try:
            with patch.dict(os.environ, {'SCRAPER_HEALTH_URL': 'http://127.0.0.1:8002'}, clear=False), patch(
                'main.urlopen', return_value=FakeResponse()
            ):
                self.login()
                body = self.client.get('/api/v1/admin/services').json()
        finally:
            self.scraper_ready.start()
        self.assertEqual(body['scraper']['status'], 'ready')
        self.assertTrue(body['scraper']['reachable'])
        self.assertTrue(body['scraper']['tavily_configured'])
        self.assertFalse(body['scraper']['model_ready'])
        self.assertFalse(body['paid_scrape_ready'])
        self.assertNotIn('SECRET', str(body))
        self.assertNotIn('missing', body['scraper'])

        class ModelOnlyResponse:
            def read(self):
                return b'{"status":"ready","tavily_configured":false,"model_ready":true}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        self.scraper_ready.stop()
        try:
            with patch.dict(os.environ, {'SCRAPER_HEALTH_URL': 'http://127.0.0.1:8002'}, clear=False), patch(
                'main.urlopen', return_value=ModelOnlyResponse()
            ):
                model_only = self.client.get('/api/v1/admin/services').json()
                blocked = self.client.post(
                    '/api/v1/admin/ingestion-jobs',
                    json={'query': 'model-only must not spend', 'max_results': 1},
                    headers={'Idempotency-Key': 'model-only-spend-gate'},
                )
        finally:
            self.scraper_ready.start()
        self.assertTrue(model_only['scraper']['model_ready'])
        self.assertFalse(model_only['scraper']['tavily_configured'])
        self.assertFalse(model_only['paid_scrape_ready'])
        self.assertEqual(blocked.status_code, 409, blocked.text)

        class LiveReadyResponse:
            def read(self):
                return b'{"status":"ready","tavily_configured":true,"model_ready":true}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        self.scraper_ready.stop()
        try:
            with patch.dict(os.environ, {'SCRAPER_HEALTH_URL': 'http://127.0.0.1:8002'}, clear=False), patch(
                'main.urlopen', return_value=LiveReadyResponse()
            ):
                ready = self.client.get('/api/v1/admin/services').json()
        finally:
            self.scraper_ready.start()
        self.assertTrue(ready['paid_scrape_ready'])
        self.assertNotIn('missing', body['scraper'])

    def test_public_config_is_login_flags_only(self):
        body = self.client.get('/api/v1/config').json()
        self.assertEqual(set(body), {'demo', 'signup_enabled', 'oauth_google'})

    def test_publish_stores_source_review_and_field_evidence(self):
        from portal_models import FieldEvidence
        header={'Idempotency-Key':'evidence-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP evidence'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        payload=sample('Reviewed clinic')
        self.client.post('/internal/v1/jobs/'+claim['id']+'/complete',json={'lease_token':claim['lease_token'],'status':'succeeded','candidates':[payload],'sources':[{'url':payload['source_url'],'title':payload['title'],'snippet':payload['source_text'][:200],'extraction_status':'success','verification_status':'unverified'}]},headers=service)
        cid=self.client.get('/api/v1/admin/candidates').json()['items'][0]['id']
        published=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'publish','version':1})
        self.assertEqual(published.status_code,200)
        found=self.client.get('/api/v1/trainings?period=all&q=Reviewed').json()['items'][0]
        self.assertEqual(published.json()['resulting_course_id'],found['id'])
        self.assertEqual(found['verification_status'],'source_reviewed')
        self.assertIsNotNone(found['reviewed_at'])
        with self.Session() as db:
            rows=db.query(FieldEvidence).filter_by(course_id=found['id']).all()
            self.assertGreaterEqual(len(rows),4)
            self.assertTrue(all(row.reviewed_by and row.reviewed_at for row in rows))
            self.assertTrue(all(row.source_document_id for row in rows))
        detail=self.client.get('/api/v1/trainings/'+found['id']).json()
        self.assertGreaterEqual(len(detail.get('field_evidence') or []),4)
        self.assertTrue(all(item.get('excerpt') for item in detail['field_evidence']))

    def test_signed_up_at_and_points_origin(self):
        saved=self.save(signup_status='signed_up')
        self.assertEqual(saved.status_code,200,saved.text)
        body=saved.json()
        self.assertEqual(body['points_origin'],'self_reported')
        self.assertTrue(body['signed_up_at'])

    def test_my_trainings_are_paginated(self):
        self.assertEqual(self.save().status_code,200)
        page=self.client.get('/api/v1/me/trainings?page=1&page_size=1&attended=true')
        self.assertEqual(page.status_code,200,page.text)
        self.assertEqual(page.json()['page_size'],1)
        self.assertEqual(page.json()['total'],1)
        self.assertEqual(len(page.json()['items']),1)
        empty=self.client.get('/api/v1/me/trainings?attendance_status=not_recorded')
        self.assertEqual(empty.json()['total'],0)
        attended=self.client.get('/api/v1/me/trainings?attendance_status=attended')
        self.assertEqual(attended.json()['total'],1)

    def test_my_trainings_legacy_attended_honours_attendance_status_drift(self):
        """Legacy attended= filter must honour attendance_status when the bool drifts."""
        first = self.save(signup_status='signed_up', attended=True, attended_on=today().isoformat())
        self.assertEqual(first.status_code, 200, first.text)
        with self.Session() as db:
            record = db.query(Record).filter_by(course_id=self.course).one()
            record.attended = False
            record.attendance_status = 'attended'
            db.commit()
        found = self.client.get('/api/v1/me/trainings?attended=true')
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()['total'], 1)
        missing = self.client.get('/api/v1/me/trainings?attended=false')
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertEqual(missing.json()['total'], 0)

    def test_my_trainings_attendance_status_filter_honours_bool_drift(self):
        """UI attendance_status=attended must match progress OR-semantics when the bool drifts."""
        first = self.save(signup_status='signed_up', attended=True, attended_on=today().isoformat())
        self.assertEqual(first.status_code, 200, first.text)
        with self.Session() as db:
            record = db.query(Record).filter_by(course_id=self.course).one()
            # Reverse drift: legacy bool true while status stayed not_recorded.
            record.attended = True
            record.attendance_status = 'not_recorded'
            db.commit()
        found = self.client.get('/api/v1/me/trainings?attendance_status=attended')
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()['total'], 1)
        missing = self.client.get('/api/v1/me/trainings?attendance_status=not_recorded')
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertEqual(missing.json()['total'], 0)

    def test_my_trainings_signup_status_filter_honours_bool_drift(self):
        """UI signup_status=signed_up must honour legacy bool; cancelled still wins over drift."""
        first = self.save(signup_status='signed_up')
        self.assertEqual(first.status_code, 200, first.text)
        with self.Session() as db:
            record = db.query(Record).filter_by(course_id=self.course).one()
            record.signed_up = True
            record.signup_status = 'not_recorded'
            db.commit()
        found = self.client.get('/api/v1/me/trainings?signup_status=signed_up')
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()['total'], 1)
        missing = self.client.get('/api/v1/me/trainings?signup_status=not_recorded')
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertEqual(missing.json()['total'], 0)
        with self.Session() as db:
            record = db.query(Record).filter_by(course_id=self.course).one()
            record.signed_up = True
            record.signup_status = 'cancelled'
            db.commit()
        cancelled = self.client.get('/api/v1/me/trainings?signup_status=cancelled')
        self.assertEqual(cancelled.json()['total'], 1)
        open_signed = self.client.get('/api/v1/me/trainings?signup_status=signed_up')
        self.assertEqual(open_signed.json()['total'], 0)

    def test_cancel_signup_honours_legacy_signed_up_bool_drift(self):
        """Cancel must work when signed_up bool drifted true while status stayed not_recorded."""
        created = self.save(signup_status='not_recorded', attended=False)
        self.assertEqual(created.status_code, 200, created.text)
        with self.Session() as db:
            record = db.query(Record).filter_by(course_id=self.course).one()
            record.signed_up = True
            record.signup_status = 'not_recorded'
            db.commit()
        cancelled = self.save(signup_status='cancelled', attended=False, version=1)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()['signup_status'], 'cancelled')
        self.assertFalse(cancelled.json()['signed_up'])

    def test_save_record_heals_status_bool_drift(self):
        """PUT must not wipe attended/signed_up when status stayed not_recorded but bool drifted true."""
        created = self.save(signup_status='not_recorded', attended=False)
        self.assertEqual(created.status_code, 200, created.text)
        with self.Session() as db:
            record = db.query(Record).filter_by(course_id=self.course).one()
            record.signed_up = True
            record.signup_status = 'not_recorded'
            record.attended = True
            record.attendance_status = 'not_recorded'
            record.attended_on = today().isoformat()
            db.commit()
            version = record.version
        healed = self.client.put(
            '/api/v1/me/trainings/' + self.course,
            json={
                'signup_status': 'not_recorded',
                'signed_up': True,
                'attended': True,
                'attendance_status': 'not_recorded',
                'attended_on': today().isoformat(),
                'credit_label': 'CPD',
                'version': version,
            },
        )
        self.assertEqual(healed.status_code, 200, healed.text)
        body = healed.json()
        self.assertEqual(body['signup_status'], 'signed_up')
        self.assertTrue(body['signed_up'])
        self.assertEqual(body['attendance_status'], 'attended')
        self.assertTrue(body['attended'])

    def test_concurrent_claim_gives_one_owner(self):
        import threading
        header={'Idempotency-Key':'concurrent-claim-key'}
        self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP concurrent'},headers=header)
        service={'Authorization':'Bearer test-service-token'}
        codes=[]
        def claim():
            codes.append(self.client.post('/internal/v1/jobs/claim',headers=service).status_code)
        workers=[threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sorted(codes),[200,204])

    def test_concurrent_claim_two_queued_jobs_both_owned(self):
        import threading
        for index in range(2):
            created=self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query':'GP dual claim '+str(index)},
                headers={'Idempotency-Key':'dual-claim-key-'+str(index)},
            )
            self.assertEqual(created.status_code,202,created.text)
        service={'Authorization':'Bearer test-service-token'}
        owned=[]
        lock=threading.Lock()
        def claim():
            response=self.client.post('/internal/v1/jobs/claim',headers=service)
            with lock:
                owned.append((response.status_code, response.json().get('id') if response.status_code==200 else None))
        workers=[threading.Thread(target=claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sorted(code for code, _ in owned),[200,200])
        ids=[job_id for code, job_id in owned if code==200]
        self.assertEqual(len(set(ids)),2)

    def test_claim_walks_past_lost_first_row_to_next_job(self):
        """OPS-01: when the first queued row loses the conditional update, claim the next job (or 204)."""
        from sqlalchemy.orm import Session
        from sqlalchemy.sql.dml import Update

        first = self.client.post(
            '/api/v1/admin/ingestion-jobs',
            json={'query': 'GP lost claim first'},
            headers={'Idempotency-Key': 'lost-claim-first'},
        )
        second = self.client.post(
            '/api/v1/admin/ingestion-jobs',
            json={'query': 'GP lost claim second'},
            headers={'Idempotency-Key': 'lost-claim-second'},
        )
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        first_id = first.json()['id']
        second_id = second.json()['id']
        service = {'Authorization': 'Bearer test-service-token'}
        lost_once = {'done': False}
        real_execute = Session.execute

        def execute(self, statement, *args, **kwargs):
            result = real_execute(self, statement, *args, **kwargs)
            # Claim SET is status + lease_token (no result). expire_jobs interrupt sets result;
            # idle leftover-lease clear sets lease_token=None without SET status.
            rendered = str(statement)
            if (
                not lost_once['done']
                and isinstance(statement, Update)
                and getattr(statement.table, 'name', None) == 'ingestion_jobs'
                and 'lease_token' in rendered
                and 'result' not in rendered
                and 'SET status' in rendered
            ):
                # Apply the winner's update in DB, but report a lost race to the claimer so the
                # walk continues to the next queued job instead of returning 204 early.
                lost_once['done'] = True

                class Lost:
                    rowcount = 0

                return Lost()
            return result

        with patch.object(Session, 'execute', execute):
            claimed = self.client.post('/internal/v1/jobs/claim', headers=service)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertTrue(lost_once['done'])
        self.assertEqual(claimed.json()['id'], second_id)
        with self.Session() as db:
            self.assertEqual(db.get(Job, first_id).status, 'running')
            self.assertEqual(db.get(Job, second_id).status, 'running')
        self.assertEqual(self.client.post('/internal/v1/jobs/claim', headers=service).status_code, 204)

    def test_claim_lost_only_queued_row_returns_204(self):
        from sqlalchemy.orm import Session
        from sqlalchemy.sql.dml import Update

        created = self.client.post(
            '/api/v1/admin/ingestion-jobs',
            json={'query': 'GP lone lost claim'},
            headers={'Idempotency-Key': 'lost-claim-lone'},
        )
        self.assertEqual(created.status_code, 202, created.text)
        job_id = created.json()['id']
        service = {'Authorization': 'Bearer test-service-token'}
        lost_once = {'done': False}
        real_execute = Session.execute

        def execute(self, statement, *args, **kwargs):
            result = real_execute(self, statement, *args, **kwargs)
            rendered = str(statement)
            if (
                not lost_once['done']
                and isinstance(statement, Update)
                and getattr(statement.table, 'name', None) == 'ingestion_jobs'
                and 'lease_token' in rendered
                and 'result' not in rendered
                and 'SET status' in rendered
            ):
                lost_once['done'] = True

                class Lost:
                    rowcount = 0

                return Lost()
            return result

        with patch.object(Session, 'execute', execute):
            empty = self.client.post('/internal/v1/jobs/claim', headers=service)
        self.assertEqual(empty.status_code, 204, empty.text)
        self.assertEqual(empty.headers.get('x-care-claim-reason'), 'lost_lease')
        self.assertTrue(lost_once['done'])
        with self.Session() as db:
            self.assertEqual(db.get(Job, job_id).status, 'running')

    def test_concurrent_worker_stress_does_not_duplicate(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        service={'Authorization':'Bearer test-service-token'}
        job_ids=[]
        for i in range(8):
            created=self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query':'GP stress topic '+str(i)+' extra'},
                headers={'Idempotency-Key':'stress-key-'+str(i)},
            )
            self.assertEqual(created.status_code,202,created.text)
            job_ids.append(created.json()['id'])

        def worker():
            owned=[]
            while True:
                response=self.client.post('/internal/v1/jobs/claim',headers=service)
                if response.status_code==204:
                    break
                self.assertEqual(response.status_code,200,response.text)
                job=response.json()
                complete=self.client.post(
                    '/internal/v1/jobs/'+job['id']+'/complete',
                    json={'lease_token':job['lease_token'],'status':'succeeded','candidates':[sample('Stress GP '+job['id'][:8])]},
                    headers=service,
                )
                self.assertEqual(complete.status_code,200,complete.text)
                owned.append(job['id'])
            return owned

        with ThreadPoolExecutor(8) as pool:
            owned=[item for future in as_completed([pool.submit(worker) for _ in range(8)]) for item in future.result()]
        self.assertEqual(sorted(owned),sorted(job_ids))
        self.assertEqual(len(set(owned)),8)
        items=self.client.get('/api/v1/admin/candidates').json()['items']
        self.assertEqual(len(items),8)
        self.assertEqual(len({item['data']['title'] for item in items}),8)
        statuses={row['id']:row['status'] for row in self.client.get('/api/v1/admin/ingestion-jobs').json()['items'] if row['id'] in job_ids}
        self.assertEqual(set(statuses.values()),{'succeeded'})

    def test_signup_and_password_validation(self):
        r=self.client.post('/api/v1/auth/register',json={'email':'new@example.com','password':PASSWORD,'name':'New Doctor'})
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(self.client.post('/api/v1/auth/register',json={'email':'bad','password':'short'}).status_code,422)
        # Weak password below the 12-character floor is rejected before create.
        self.assertEqual(self.client.post('/api/v1/auth/register',json={'email':'weak@example.com','password':'shortpass','name':'Weak'}).status_code,422)
        dup=self.client.post('/api/v1/auth/register',json={'email':'new@example.com','password':PASSWORD,'name':'Dup Doctor'})
        self.assertEqual(dup.status_code,409,dup.text)
        self.assertEqual(dup.json()['error']['code'],'conflict')
        self.assertEqual(self.client.post('/api/v1/auth/register',json={'email':'space@example.com','password':PASSWORD,'name':'  '}).status_code,422)
        self.assertEqual(self.client.post('/api/v1/auth/register',json={'email':'pad@example.com','password':PASSWORD,'name':'  Padded Name  '}).status_code,201)
        self.assertEqual(self.client.post('/api/v1/auth/login',json={'email':'new@example.com','password':'wrong-password-long'}).status_code,401)
        self.assertEqual(self.client.post('/api/v1/auth/login',json={'email':'new@example.com','password':PASSWORD}).status_code,200)
        self.login('pad@example.com')
        me=self.client.get('/api/v1/me').json()
        self.assertEqual(me['name'],'Padded Name')
        self.login('a@example.com')

    def test_job_max_results_and_source_documents(self):
        from portal_models import SourceDocument
        header={'Idempotency-Key':'max-results-key'}
        created=self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP source pages','max_results':3},headers=header)
        self.assertEqual(created.status_code,202,created.text)
        self.assertEqual(created.json()['max_results'],3)
        self.assertEqual(self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP source pages','max_results':2},headers=header).status_code,409)
        self.assertEqual(self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP source pages','max_results':6},headers=header).status_code,422)
        service={'Authorization':'Bearer test-service-token'}
        claim=self.client.post('/internal/v1/jobs/claim',headers=service).json()
        self.assertEqual(claim['max_results'],3)
        payload={
            'lease_token':claim['lease_token'],'status':'partial','candidates':[],
            'sources':[{'url':'https://example.org/afpm#section','title':'Primary Care Update','snippet':'CPD workshop in Kuala Lumpur','extraction_status':'success','verification_status':'unverified'}],
        }
        self.assertEqual(self.client.post('/internal/v1/jobs/'+claim['id']+'/complete',json=payload,headers=service).status_code,200)
        with self.Session() as db:
            rows=db.query(SourceDocument).all()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].canonical_url,'https://example.org/afpm')
            self.assertEqual(rows[0].job_id,claim['id'])
        created=self.client.get('/api/v1/admin/ingestion-jobs/'+claim['id'])
        self.assertEqual(created.json()['attempt'],1)

    def test_candidates_are_paginated_and_review_is_versioned(self):
        with self.Session() as db:
            job=Job(account_id=self.a,request_key='review-page',query='GP')
            other=Job(account_id=self.a,request_key='review-page-other',query='Other GP')
            db.add_all([job, other]);db.flush()
            first=Candidate(job_id=job.id,source_key='one',data=sample('First queue item'))
            second=Candidate(job_id=job.id,source_key='two',data=sample('Second queue item'))
            other_row=Candidate(job_id=other.id,source_key='other',data=sample('Other job item'))
            db.add_all([first,second,other_row]);db.commit()
            cid=first.id
            job_id=job.id
            other_id=other.id
        page=self.client.get('/api/v1/admin/candidates?page=1&page_size=1')
        self.assertEqual(page.status_code,200,page.text)
        self.assertEqual(page.json()['total'],3)
        self.assertEqual(page.json()['page_size'],1)
        self.assertEqual(len(page.json()['items']),1)
        self.assertEqual(page.json()['items'][0]['version'],1)
        self.assertEqual(page.json()['items'][0]['schema_version'],1)
        self.assertEqual(page.json()['status'],['pending','held'])
        self.assertIsNone(page.json()['job_id'])
        self.assertTrue(page.json()['items'][0]['job_id'])
        by_job=self.client.get('/api/v1/admin/candidates?job_id='+job_id)
        self.assertEqual(by_job.status_code,200,by_job.text)
        self.assertEqual(by_job.json()['total'],2)
        self.assertEqual(by_job.json()['job_id'],job_id)
        self.assertTrue(all(item['job_id']==job_id for item in by_job.json()['items']))
        self.assertEqual(self.client.get('/api/v1/admin/candidates?job_id='+other_id).json()['total'],1)
        self.assertEqual(self.client.get('/api/v1/admin/candidates?status=published').status_code,422)
        stale=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'hold','reason':'Need MMC confirmation','version':99})
        self.assertEqual(stale.status_code,409)
        self.assertEqual(stale.json()['error']['code'],'conflict')
        held=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'hold','reason':'Need MMC confirmation','version':1})
        self.assertEqual(held.status_code,200,held.text)
        self.assertEqual(held.json()['version'],2)
        # Stale version after a successful review must not clobber the new state.
        again=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','reason':'Wrong provider page','version':1})
        self.assertEqual(again.status_code,409)
        # Default version 0 must not bypass locking once the candidate is past v1.
        zero=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','reason':'Wrong provider page','version':0})
        self.assertEqual(zero.status_code,409)
        held_row=next(item for item in self.client.get('/api/v1/admin/candidates').json()['items'] if item['id']==cid)
        self.assertEqual(held_row['status'],'held')
        self.assertEqual(held_row['version'],2)
        rejected=self.client.post('/api/v1/admin/candidates/'+cid+'/review',json={'action':'reject','reason':'Wrong provider page','version':2})
        self.assertEqual(rejected.status_code,200,rejected.text)
        # Rejected rows leave the default awaiting queue but stay reachable via status filter.
        self.assertFalse(any(item['id']==cid for item in self.client.get('/api/v1/admin/candidates').json()['items']))
        rejected_queue=self.client.get('/api/v1/admin/candidates?status=rejected')
        self.assertEqual(rejected_queue.status_code,200,rejected_queue.text)
        self.assertEqual(rejected_queue.json()['status'],['rejected'])
        self.assertEqual([(item['id'],item['status']) for item in rejected_queue.json()['items']],[(cid,'rejected')])

    def test_operator_job_list_status_filter_and_pagination(self):
        for index in range(3):
            created = self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query': f'GP job filter {index}', 'max_results': 1},
                headers={'Idempotency-Key': f'job-filter-{index}-{secrets.token_hex(4)}'},
            )
            self.assertEqual(created.status_code, 202, created.text)
        listed = self.client.get('/api/v1/admin/ingestion-jobs?page=1&page_size=2')
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertGreaterEqual(body['total'], 3)
        self.assertEqual(body['page'], 1)
        self.assertEqual(body['page_size'], 2)
        self.assertEqual(len(body['items']), 2)
        self.assertIsNone(body['status'])
        queued = self.client.get('/api/v1/admin/ingestion-jobs?status=queued')
        self.assertEqual(queued.status_code, 200, queued.text)
        self.assertEqual(queued.json()['status'], ['queued'])
        self.assertTrue(all(item['status'] == 'queued' for item in queued.json()['items']))
        self.assertEqual(self.client.get('/api/v1/admin/ingestion-jobs?status=published').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/admin/ingestion-jobs?page=0').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/admin/ingestion-jobs?page_size=51').status_code, 422)

    def test_scraper_token_cannot_read_personal_data(self):
        self.save()
        self.client.cookies.clear()
        headers={'Authorization':'Bearer test-service-token'}
        self.assertEqual(self.client.get('/api/v1/me',headers=headers).status_code,401)
        self.assertEqual(self.client.get('/api/v1/me/trainings',headers=headers).status_code,401)
        self.assertEqual(self.client.get('/api/v1/me/export/csv',headers=headers).status_code,401)
        self.assertEqual(self.client.get('/api/v1/admin/candidates',headers=headers).status_code,401)
        self.assertEqual(self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP scrape'},headers={**headers,'Idempotency-Key':'scraper-admin'}).status_code,401)
        self.assertEqual(self.client.get('/api/v1/admin/integrations',headers=headers).status_code,401)

    def test_scraper_auth_rejects_missing_mismatch_and_blank_tokens(self):
        # Raw token without Bearer scheme is rejected; padded Bearer still matches after strip.
        self.assertEqual(self.client.post('/internal/v1/jobs/claim').status_code, 403)
        self.assertEqual(
            self.client.post('/internal/v1/jobs/claim', headers={'Authorization': 'test-service-token'}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post('/internal/v1/jobs/claim', headers={'Authorization': 'Bearer wrong-token'}).status_code,
            403,
        )
        padded = self.client.post(
            '/internal/v1/jobs/claim',
            headers={'Authorization': 'Bearer test-service-token '},
        )
        self.assertEqual(padded.status_code, 204, padded.text)
        with patch.dict(os.environ, {'SCRAPER_SERVICE_TOKEN': '   '}, clear=False):
            blank = self.client.post(
                '/internal/v1/jobs/claim',
                headers={'Authorization': 'Bearer    '},
            )
            self.assertEqual(blank.status_code, 503)
            self.assertEqual(blank.json()['error']['code'], 'unavailable')
        with patch.dict(os.environ, {'SCRAPER_SERVICE_TOKEN': ''}, clear=False):
            missing = self.client.post(
                '/internal/v1/jobs/claim',
                headers={'Authorization': 'Bearer test-service-token'},
            )
            self.assertEqual(missing.status_code, 503)

    def test_operator_job_hourly_limit(self):
        for i in range(10):
            result=self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP CPD topic '+str(i)+' extra'},headers={'Idempotency-Key':'limit-key-'+str(i)})
            self.assertEqual(result.status_code,202,result.text)
        blocked=self.client.post('/api/v1/admin/ingestion-jobs',json={'query':'GP CPD extra topic overflow'},headers={'Idempotency-Key':'limit-key-10'})
        self.assertEqual(blocked.status_code,429)
        body = blocked.json()['error']
        self.assertEqual(body['code'], 'throttled')
        self.assertTrue(body['request_id'])
        self.assertEqual(blocked.headers.get('x-request-id'), body['request_id'])
        self.assertIn('Too many requests', body['message'])

    def test_operator_digest_run_is_throttled(self):
        for i in range(20):
            result = self.client.post('/api/v1/admin/digests/run')
            self.assertEqual(result.status_code, 200, result.text)
        blocked = self.client.post('/api/v1/admin/digests/run')
        self.assertEqual(blocked.status_code, 429)
        body = blocked.json()['error']
        self.assertEqual(body['code'], 'throttled')
        self.assertTrue(body['request_id'])

    def test_login_email_is_throttled(self):
        """Pre-fill the login-email bucket so AUTH throttle returns 429 without scrypt loops."""
        email = 'throttle@example.com'
        window = 300
        bucket = digest('login-email:' + email) + ':' + str(int(time.time()) // window)
        with self.Session() as db:
            db.add(Throttle(key=bucket, count=10))
            db.commit()
        blocked = self.client.post(
            '/api/v1/auth/login',
            json={'email': email, 'password': 'CareCredits-demo-2026'},
        )
        self.assertEqual(blocked.status_code, 429)
        body = blocked.json()['error']
        self.assertEqual(body['code'], 'throttled')
        self.assertTrue(body['request_id'])
        self.assertIn('Too many requests', body['message'])

    def test_register_ip_is_throttled(self):
        """AUTH-01 register throttle returns the same 429 envelope as login/jobs (beyond login-email)."""
        peer = 'register-throttle-peer'
        bucket = digest('register:' + peer) + ':' + str(int(time.time()) // 3600)
        with self.Session() as db:
            db.add(Throttle(key=bucket, count=10))
            db.commit()
        with patch('main.client_host', return_value=peer):
            blocked = self.client.post(
                '/api/v1/auth/register',
                json={
                    'email': 'register-throttle@example.com',
                    'password': 'CareCredits-demo-2026',
                    'name': 'Throttle Doctor',
                },
            )
        self.assertEqual(blocked.status_code, 429)
        body = blocked.json()['error']
        self.assertEqual(body['code'], 'throttled')
        self.assertTrue(body['request_id'])
        self.assertIn('Too many requests', body['message'])

    def test_expired_source_documents_are_purged(self):
        with self.Session() as db:
            old=SourceDocument(canonical_url='https://example.org/old',content_hash='abc',retrieved_at=1,snippet='old page')
            kept=SourceDocument(canonical_url='https://example.org/kept',content_hash='def',retrieved_at=1,snippet='reviewed page')
            # Non-positive retrieved_at is fail-closed as expired (legacy/corrupt stamp).
            zero_stamp=SourceDocument(canonical_url='https://example.org/zero-stamp',content_hash='ghi',retrieved_at=0,snippet='zero stamp page')
            db.add(old)
            db.add(kept)
            db.add(zero_stamp)
            db.flush()
            db.add(FieldEvidence(course_id=self.course, source_document_id=kept.id, field_name='title', excerpt='reviewed excerpt'))
            job=Job(account_id=self.a,request_key='old-raw',query='GP',created_at=1,result={'sources':[{'url':'https://example.org/old','snippet':'job page'}]})
            fresh=Job(account_id=self.a,request_key='fresh-raw',query='GP',result={'sources':[{'url':'https://example.org/fresh','snippet':'fresh job page'}]})
            db.add(job)
            db.add(fresh)
            db.flush()
            candidate=Candidate(job_id=job.id,source_key='old-raw',data={**sample(),'source_text':'candidate page'})
            recent=Candidate(job_id=fresh.id,source_key='fresh-raw',data={**sample('Fresh GP'),'source_text':'recent candidate page'})
            db.add(candidate)
            db.add(recent)
            course=db.get(Course,self.course)
            fill_course(course,{**course.data,'source_text':'course page','retrieved_at':'2000-01-01T00:00:00'})
            db.commit()
            old_id=old.id
            kept_id=kept.id
            zero_id=zero_stamp.id
            candidate_id=candidate.id
            recent_id=recent.id
            job_id=job.id
            fresh_id=fresh.id
            # Orphan / unparseable stamps still fail closed.
            orphan=Candidate(
                job_id='missing-job-id',
                source_key='orphan-raw',
                data={**sample('Orphan GP'), 'source_text': 'orphan page', 'retrieved_at': 'fixture'},
            )
            db.add(orphan)
            # In-flight job still inside the retention window keeps source text / snippets
            # even when the page retrieved_at is old (re-scrape of an aged listing).
            flying=Job(
                account_id=self.a,
                request_key='flying-raw',
                query='GP',
                status='running',
                created_at=time.time(),
                result={'sources':[{'url':'https://example.org/flying','snippet':'flying job page'}]},
            )
            db.add(flying)
            db.flush()
            flying_cand=Candidate(
                job_id=flying.id,
                source_key='flying-raw',
                data={**sample('Flying GP'), 'source_text':'flying candidate page', 'retrieved_at':'2000-01-01T00:00:00'},
            )
            flying_doc=SourceDocument(
                job_id=flying.id,
                canonical_url='https://example.org/flying',
                content_hash='fly',
                retrieved_at=1,
                snippet='flying source page',
            )
            db.add(flying_cand)
            db.add(flying_doc)
            db.commit()
            orphan_id=orphan.id
            flying_id=flying.id
            flying_cand_id=flying_cand.id
            flying_doc_id=flying_doc.id
            purge_expired_source_text(db, now=time.time(), batch_size=2)
            self.assertIsNone(db.get(SourceDocument, old_id))
            self.assertIsNone(db.get(SourceDocument, zero_id))
            remaining=db.get(SourceDocument, kept_id)
            self.assertIsNotNone(remaining)
            self.assertEqual(remaining.snippet,'')
            self.assertEqual((db.get(Candidate, candidate_id).data or {}).get('source_text'),'')
            self.assertEqual((db.get(Candidate, candidate_id).data or {}).get('evidence')['title'],sample()['evidence']['title'])
            self.assertEqual((db.get(Candidate, recent_id).data or {}).get('source_text'),'recent candidate page')
            self.assertEqual((db.get(Candidate, orphan_id).data or {}).get('source_text'),'')
            self.assertEqual((db.get(Course, self.course).data or {}).get('source_text'),'')
            self.assertEqual((db.get(Job, job_id).result or {}).get('sources')[0]['snippet'],'')
            self.assertEqual((db.get(Job, fresh_id).result or {}).get('sources')[0]['snippet'],'fresh job page')
            self.assertEqual((db.get(Candidate, flying_cand_id).data or {}).get('source_text'),'flying candidate page')
            self.assertEqual((db.get(Job, flying_id).result or {}).get('sources')[0]['snippet'],'flying job page')
            self.assertEqual(db.get(SourceDocument, flying_doc_id).snippet,'flying source page')
            excerpt=db.query(FieldEvidence).filter_by(source_document_id=kept_id).first()
            self.assertEqual(excerpt.excerpt,'reviewed excerpt')

    def test_aged_queued_jobs_purge_while_fresh_queued_keep_text(self):
        """Aged never-claimed queued rows purge; still-fresh queued keep snippets mid-wait."""
        with self.Session() as db:
            aged = Job(
                account_id=self.a,
                request_key='aged-queued-raw',
                query='GP',
                status='queued',
                created_at=1,
                result={'sources': [{'url': 'https://example.org/aged-queued', 'snippet': 'aged queued page'}]},
            )
            fresh = Job(
                account_id=self.a,
                request_key='fresh-queued-raw',
                query='GP',
                status='queued',
                created_at=time.time(),
                result={'sources': [{'url': 'https://example.org/fresh-queued', 'snippet': 'fresh queued page'}]},
            )
            db.add_all([aged, fresh])
            db.flush()
            aged_cand = Candidate(
                job_id=aged.id,
                source_key='aged-queued',
                data={**sample('Aged Queued'), 'source_text': 'aged queued candidate', 'retrieved_at': '2000-01-01T00:00:00'},
            )
            fresh_cand = Candidate(
                job_id=fresh.id,
                source_key='fresh-queued',
                data={**sample('Fresh Queued'), 'source_text': 'fresh queued candidate', 'retrieved_at': '2000-01-01T00:00:00'},
            )
            aged_doc = SourceDocument(
                job_id=aged.id,
                canonical_url='https://example.org/aged-queued',
                content_hash='aged-q',
                retrieved_at=1,
                snippet='aged queued source',
            )
            fresh_doc = SourceDocument(
                job_id=fresh.id,
                canonical_url='https://example.org/fresh-queued',
                content_hash='fresh-q',
                retrieved_at=1,
                snippet='fresh queued source',
            )
            db.add_all([aged_cand, fresh_cand, aged_doc, fresh_doc])
            db.commit()
            aged_id, fresh_id = aged.id, fresh.id
            aged_cand_id, fresh_cand_id = aged_cand.id, fresh_cand.id
            aged_doc_id, fresh_doc_id = aged_doc.id, fresh_doc.id
            purge_expired_source_text(db, now=time.time(), batch_size=2)
            self.assertEqual((db.get(Candidate, aged_cand_id).data or {}).get('source_text'), '')
            self.assertEqual((db.get(Job, aged_id).result or {}).get('sources')[0]['snippet'], '')
            self.assertIsNone(db.get(SourceDocument, aged_doc_id))
            self.assertEqual((db.get(Candidate, fresh_cand_id).data or {}).get('source_text'), 'fresh queued candidate')
            self.assertEqual((db.get(Job, fresh_id).result or {}).get('sources')[0]['snippet'], 'fresh queued page')
            self.assertEqual(db.get(SourceDocument, fresh_doc_id).snippet, 'fresh queued source')

    def test_purge_normalizes_whitespace_only_source_text(self):
        with self.Session() as db:
            job = Job(account_id=self.a, request_key='ws-purge', query='GP', created_at=1)
            db.add(job)
            db.flush()
            cand = Candidate(
                job_id=job.id,
                source_key='ws-purge',
                data={**sample('WS Purge'), 'source_text': '   ', 'retrieved_at': '2000-01-01T00:00:00'},
            )
            db.add(cand)
            db.commit()
            cand_id = cand.id
            purge_expired_source_text(db, now=time.time(), batch_size=2)
            self.assertEqual((db.get(Candidate, cand_id).data or {}).get('source_text'), '')

    def test_retrieved_stamp_parses_utc_iso(self):
        from portal_models import retrieved_stamp

        self.assertEqual(retrieved_stamp({'retrieved_at': '2026-10-03T03:00:00+00:00'}), 1790996400.0)
        self.assertEqual(retrieved_stamp({'retrieved_at': '2026-10-03T03:00:00Z'}), 1790996400.0)
        self.assertEqual(retrieved_stamp({'retrieved_at': '2026-10-03T03:00:00'}), 1790996400.0)
        self.assertIsNone(retrieved_stamp({'retrieved_at': 'fixture'}))
        self.assertIsNone(retrieved_stamp({}))

    def test_complete_missing_retrieved_at_fail_closes_as_expired(self):
        """Missing scraper stamps must not invent complete-time freshness for retention."""
        header = {'Idempotency-Key': 'missing-stamp'}
        created = self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP no stamp'}, headers=header)
        self.assertEqual(created.status_code, 202, created.text)
        service = {'Authorization': 'Bearer test-service-token'}
        claim = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        payload = {
            'lease_token': claim['lease_token'],
            'status': 'partial',
            'candidates': [],
            'warnings': ['blank page'],
            'usage': {'tavily_credits': 0, 'model_tokens': 0},
            'sources': [{
                'url': 'https://example.org/no-stamp',
                'title': 'No Stamp',
                'snippet': 'page',
                'extraction_status': 'failed',
                'verification_status': 'unverified',
            }],
        }
        self.assertEqual(
            self.client.post('/internal/v1/jobs/' + claim['id'] + '/complete', json=payload, headers=service).status_code,
            200,
        )
        with self.Session() as db:
            row = db.query(SourceDocument).filter_by(canonical_url='https://example.org/no-stamp').one()
            self.assertEqual(row.retrieved_at, 0)

    def test_aged_stuck_running_null_started_at_expires(self):
        """running + future lease_until + null started_at cannot complete; expire then purge."""
        from main import expire_jobs

        with self.Session() as db:
            stuck = Job(
                account_id=self.a,
                request_key='stuck-null-started',
                query='GP',
                status='running',
                created_at=1,
                lease_until=time.time() + 3600,
                started_at=None,
                result={'sources': [{'url': 'https://example.org/null-started', 'snippet': 'stuck page'}]},
            )
            db.add(stuck)
            db.flush()
            cand = Candidate(
                job_id=stuck.id,
                source_key='stuck-null-started',
                data={**sample('Null Started'), 'source_text': 'stuck candidate', 'retrieved_at': '2000-01-01T00:00:00'},
            )
            doc = SourceDocument(
                job_id=stuck.id,
                canonical_url='https://example.org/null-started',
                content_hash='null-started',
                retrieved_at=1,
                snippet='stuck source',
            )
            db.add(cand)
            db.add(doc)
            db.commit()
            stuck_id, cand_id, doc_id = stuck.id, cand.id, doc.id
            expire_jobs(db)
            row = db.get(Job, stuck_id)
            self.assertEqual(row.status, 'interrupted')
            self.assertIsNone(row.lease_until)
            purge_expired_source_text(db, now=time.time(), batch_size=2)
            self.assertEqual((db.get(Candidate, cand_id).data or {}).get('source_text'), '')
            self.assertIsNone(db.get(SourceDocument, doc_id))

    def test_expire_jobs_honours_started_at_deadline_with_future_lease(self):
        """Heartbeat/complete refuse started_at older than 5 minutes; expire must match."""
        from main import expire_jobs

        with self.Session() as db:
            stuck = Job(
                account_id=self.a,
                request_key='stuck-old-started',
                query='GP',
                status='running',
                lease_token='dead-lease',
                lease_until=time.time() + 60,
                started_at=time.time() - 301,
            )
            db.add(stuck)
            db.commit()
            stuck_id = stuck.id
            expire_jobs(db)
            row = db.get(Job, stuck_id)
            self.assertEqual(row.status, 'interrupted')
            self.assertIsNone(row.lease_token)
            self.assertIsNone(row.lease_until)
            self.assertIsNone(row.started_at)

    def test_expire_jobs_clears_leftover_lease_on_idle_rows(self):
        """Idle/terminal rows (including queued) must not keep lease fields after expire sweep."""
        from main import expire_jobs

        with self.Session() as db:
            idle = Job(
                account_id=self.a,
                request_key='idle-leftover-lease',
                query='GP',
                status='interrupted',
                lease_token='stale-lease',
                lease_until=1.0,
                started_at=1.0,
            )
            terminal = Job(
                account_id=self.a,
                request_key='terminal-leftover-lease',
                query='GP',
                status='succeeded',
                lease_token='ghost-lease',
                lease_until=9.0,
                started_at=9.0,
            )
            queued = Job(
                account_id=self.a,
                request_key='queued-leftover-lease',
                query='GP',
                status='queued',
                lease_token='queued-ghost',
                lease_until=2.0,
                started_at=2.0,
            )
            live = Job(
                account_id=self.a,
                request_key='running-keep-lease',
                query='GP',
                status='running',
                lease_token='live-lease',
                lease_until=time.time() + 60,
                started_at=time.time(),
            )
            db.add(idle)
            db.add(terminal)
            db.add(queued)
            db.add(live)
            db.commit()
            idle_id, terminal_id, queued_id, live_id = idle.id, terminal.id, queued.id, live.id
            live_token = live.lease_token
            expire_jobs(db)
            idle_row = db.get(Job, idle_id)
            terminal_row = db.get(Job, terminal_id)
            queued_row = db.get(Job, queued_id)
            live_row = db.get(Job, live_id)
            self.assertEqual(idle_row.status, 'interrupted')
            self.assertIsNone(idle_row.lease_token)
            self.assertIsNone(idle_row.lease_until)
            self.assertIsNone(idle_row.started_at)
            self.assertEqual(terminal_row.status, 'succeeded')
            self.assertIsNone(terminal_row.lease_token)
            self.assertIsNone(terminal_row.lease_until)
            self.assertIsNone(terminal_row.started_at)
            self.assertEqual(queued_row.status, 'queued')
            self.assertIsNone(queued_row.lease_token)
            self.assertIsNone(queued_row.lease_until)
            self.assertIsNone(queued_row.started_at)
            # Leftover clear must not touch a live running lease.
            self.assertEqual(live_row.status, 'running')
            self.assertEqual(live_row.lease_token, live_token)
            self.assertIsNotNone(live_row.lease_until)
            self.assertIsNotNone(live_row.started_at)

    def test_claim_not_ready_still_expires_dead_leases(self):
        """Worker polls claim while model/Tavily are down; do not leave zombie running rows."""
        with self.Session() as db:
            stuck = Job(
                account_id=self.a,
                request_key='not-ready-expire',
                query='GP',
                status='running',
                lease_token='dead-lease',
                lease_until=time.time() - 10,
                started_at=time.time() - 400,
            )
            db.add(stuck)
            db.commit()
            stuck_id = stuck.id
        service = {'Authorization': 'Bearer test-service-token'}
        with patch(
            'main._scraper_service_status',
            return_value={'tavily_configured': True, 'model_ready': False, 'reachable': True, 'status': 'ready'},
        ):
            claim = self.client.post('/internal/v1/jobs/claim', headers=service)
        self.assertEqual(claim.status_code, 204)
        self.assertEqual(claim.headers.get('x-care-claim-reason'), 'not_ready')
        with self.Session() as db:
            row = db.get(Job, stuck_id)
            self.assertEqual(row.status, 'interrupted')
            self.assertIsNone(row.lease_token)
            self.assertIsNone(row.lease_until)
            self.assertIsNone(row.started_at)

    def test_aged_stuck_running_null_lease_expires_then_purges(self):
        """running + null lease_until is aged-stuck: expire_jobs then retention can blank snippets."""
        from main import expire_jobs

        with self.Session() as db:
            stuck = Job(
                account_id=self.a,
                request_key='stuck-null-lease',
                query='GP',
                status='running',
                created_at=1,
                lease_until=None,
                result={'sources': [{'url': 'https://example.org/stuck', 'snippet': 'stuck job page'}]},
            )
            db.add(stuck)
            db.flush()
            cand = Candidate(
                job_id=stuck.id,
                source_key='stuck-null-lease',
                data={**sample('Stuck GP'), 'source_text': 'stuck candidate page', 'retrieved_at': '2000-01-01T00:00:00'},
            )
            doc = SourceDocument(
                job_id=stuck.id,
                canonical_url='https://example.org/stuck',
                content_hash='stuck',
                retrieved_at=1,
                snippet='stuck source page',
            )
            db.add(cand)
            db.add(doc)
            db.commit()
            stuck_id, cand_id, doc_id = stuck.id, cand.id, doc.id
            expire_jobs(db)
            row = db.get(Job, stuck_id)
            self.assertEqual(row.status, 'interrupted')
            self.assertIsNone(row.lease_until)
            purge_expired_source_text(db, now=time.time(), batch_size=2)
            self.assertEqual((db.get(Candidate, cand_id).data or {}).get('source_text'), '')
            self.assertEqual((db.get(Job, stuck_id).result or {}).get('sources')[0]['snippet'], '')
            self.assertIsNone(db.get(SourceDocument, doc_id))

    def test_end_date_cannot_precede_start(self):
        with self.assertRaises(ValueError):
            fill_course(Course(source_key='bad-dates'), {**sample(), 'end_date':'2025-01-01'})

    def test_session_schedule_fields_persist(self):
        quote=sample()['source_text']+' Ends 2026-01-02 at Menara venue Asia/Kuala_Lumpur.'
        cid=self.add_course(
            'scheduled',
            title='Scheduled GP',
            start_date='2026-01-01',
            end_date='2026-01-02',
            timezone='Asia/Kuala_Lumpur',
            venue='Menara',
            source_text=quote,
            evidence={key:quote for key in ['title','provider','mode','country','start_date','end_date','timezone','venue']},
        )
        detail=self.client.get('/api/v1/trainings/'+cid).json()
        self.assertEqual(detail['end_date'],'2026-01-02')
        self.assertEqual(detail['timezone'],'Asia/Kuala_Lumpur')
        self.assertEqual(detail['venue'],'Menara')

    def test_demo_seed_exposes_provider_registration_urls(self):
        from seed_demo import seed, DEMO_PASSWORD
        from security import password_hash, password_matches
        from portal_models import Candidate, Record
        with self.Session() as db:
            seed(db)
            rows=db.query(Course).filter(Course.source_key.like('demo-%')).all()
            self.assertGreaterEqual(len(rows),6)
            for row in rows:
                url=(row.data or {}).get('registration_url')
                self.assertTrue(url and url.startswith('https://example.org/carecredits-demo-') and url.endswith('/register'), row.source_key)
            pending=db.query(Candidate).filter(Candidate.status=='pending', Candidate.source_key.like('demo-candidate-%')).all()
            self.assertGreaterEqual(len(pending),2)
            for cand in pending:
                self.assertIn('Demonstration source only', (cand.data or {}).get('source_text',''))
                self.assertTrue((cand.data or {}).get('_fixture'))
                self.assertEqual((cand.data or {}).get('retrieved_at'), 'fixture')
                self.assertIn('registration_url', (cand.data or {}).get('evidence') or {})
                reg=(cand.data or {}).get('registration_url') or ''
                self.assertIn(reg, (cand.data or {}).get('source_text',''))
            from portal_models import Job
            job=db.query(Job).filter_by(request_key='demo-review-queue').one()
            self.assertEqual((job.result or {}).get('extraction_status'), 'fixture')
            self.assertEqual((job.result or {}).get('usage'), {'tavily_credits': None, 'model_tokens': None})
            sources = (job.result or {}).get('sources') or []
            self.assertTrue(all((item.get('retrieved_at') == 'fixture') for item in sources))
            self.assertIn(
                'https://example.org/carecredits-demo-candidate-queue',
                {item.get('url') for item in sources},
            )
            self.assertEqual((job.result or {}).get('candidate_count'), 3)
            self.assertEqual(job.max_results, 3)
            doctor=db.query(Account).filter_by(email='doctor@carecredits.local').one()
            operator=db.query(Account).filter_by(email='demo@carecredits.local').one()
            self.assertGreaterEqual(db.query(Record).filter_by(account_id=doctor.id).count(),2)
            self.assertGreaterEqual(db.query(Record).filter_by(account_id=operator.id).count(),2)
            fixture_id=pending[0].id
            # Offline DEMO-01 steps 3–4: fixture candidates must publish with demo labelling.
            login=self.client.post('/api/v1/auth/login',json={'email':'demo@carecredits.local','password':DEMO_PASSWORD})
            self.assertEqual(login.status_code,200,login.text)
            published=self.client.post(
                '/api/v1/admin/candidates/'+fixture_id+'/review',
                json={'action':'publish','version':1,'reason':'Publish fictional fixture for offline DEMO-01'},
            )
            self.assertEqual(published.status_code,200,published.text)
            self.assertEqual(published.json()['status'],'published')
            course_id=published.json()['resulting_course_id']
            detail=self.client.get('/api/v1/trainings/'+course_id).json()
            self.assertTrue(detail.get('demo'))
            self.assertTrue((detail.get('registration_url') or '').endswith('/register'))
            first=rows[0]
            first.data={**(first.data or {}), 'registration_url': None}
            demo=db.query(Account).filter_by(email='demo@carecredits.local').one()
            demo.password_hash=password_hash('Wrong-demo-password-999')
            db.commit()
            seed(db)
            refreshed=db.get(Course, first.id)
            self.assertTrue((refreshed.data or {}).get('registration_url', '').endswith('/register'))
            demo=db.query(Account).filter_by(email='demo@carecredits.local').one()
            self.assertTrue(password_matches('CareCredits-demo-2026', demo.password_hash))
            # Reseed keeps remaining pending fixtures; published fixtures stay published.
            self.assertEqual(
                db.query(Candidate).filter(Candidate.status=='pending', Candidate.source_key.like('demo-candidate-%')).count(),
                1,
            )
            self.assertEqual(
                db.query(Candidate).filter(Candidate.status=='published', Candidate.source_key.like('demo-candidate-%')).count(),
                1,
            )
            # Rejected fixtures reopen as pending on DEMO_MODE reseed so offline review stays rehearsable.
            remaining = (
                db.query(Candidate)
                .filter(Candidate.status == 'pending', Candidate.source_key.like('demo-candidate-%'))
                .one()
            )
            prior_version = remaining.version
            remaining.status = 'rejected'
            remaining.review_reason = 'Rejected during offline DEMO-01 rehearsal'
            remaining.reviewed_at = 1.0
            db.commit()
            seed(db)
            restored = db.get(Candidate, remaining.id)
            self.assertEqual(restored.status, 'pending')
            self.assertEqual(restored.review_reason, '')
            self.assertIsNone(restored.reviewed_at)
            self.assertTrue((restored.data or {}).get('_fixture'))
            self.assertEqual((restored.data or {}).get('retrieved_at'), 'fixture')
            self.assertGreater(restored.version, prior_version)
            self.assertEqual(
                db.query(Candidate).filter(Candidate.status == 'published', Candidate.source_key.like('demo-candidate-%')).count(),
                1,
            )
            # Pending/held evidence refresh also bumps version for CandidateCard remount.
            pending_refresh = (
                db.query(Candidate)
                .filter(Candidate.status == 'pending', Candidate.source_key.like('demo-candidate-%'))
                .one()
            )
            pending_version = pending_refresh.version
            seed(db)
            self.assertGreater(db.get(Candidate, pending_refresh.id).version, pending_version)
            # Cancelled fixture personal records restore on DEMO_MODE reseed (offline step 7).
            doctor = db.query(Account).filter_by(email='doctor@carecredits.local').one()
            signed_up_course = db.query(Course).filter_by(source_key='demo-2').one()
            personal = (
                db.query(Record)
                .filter_by(account_id=doctor.id, course_id=signed_up_course.id)
                .one()
            )
            personal.signup_status = 'cancelled'
            personal.signed_up = False
            prior_record_version = personal.version
            db.commit()
            seed(db)
            restored_record = db.get(Record, personal.id)
            self.assertEqual(restored_record.signup_status, 'signed_up')
            self.assertTrue(restored_record.signed_up)
            self.assertGreater(restored_record.version, prior_record_version)
            # Attended fixture rows also clear public/notes drift on DEMO_MODE reseed.
            attended_course = db.query(Course).filter_by(source_key='demo-3').one()
            attended_record = (
                db.query(Record)
                .filter_by(account_id=doctor.id, course_id=attended_course.id)
                .one()
            )
            attended_record.public = True
            attended_record.notes = 'private rehearsal note'
            prior_attended_version = attended_record.version
            db.commit()
            seed(db)
            restored_attended = db.get(Record, attended_record.id)
            self.assertFalse(restored_attended.public)
            self.assertEqual(restored_attended.notes, '')
            self.assertEqual(restored_attended.attendance_status, 'attended')
            self.assertGreater(restored_attended.version, prior_attended_version)
            # Cancelled demo-* catalogue sessions re-list on DEMO_MODE reseed.
            demo_course = db.query(Course).filter_by(source_key='demo-0').one()
            demo_course.publication_status = 'cancelled'
            demo_course.cancellation_status = 'cancelled'
            db.commit()
            seed(db)
            restored_course = db.get(Course, demo_course.id)
            self.assertEqual(restored_course.publication_status, 'published')
            self.assertEqual(restored_course.cancellation_status, 'active')
            # Published fixture candidates' resulting courses (non demo-* keys) also re-list on reseed.
            published_fixture = (
                db.query(Candidate)
                .filter(
                    Candidate.source_key.like('demo-candidate-%'),
                    Candidate.status == 'published',
                )
                .first()
            )
            self.assertIsNotNone(published_fixture)
            self.assertTrue(published_fixture.resulting_course_id)
            fixture_course = db.get(Course, published_fixture.resulting_course_id)
            self.assertIsNotNone(fixture_course)
            fixture_course.publication_status = 'cancelled'
            fixture_course.cancellation_status = 'cancelled'
            # Fixture review job must not keep leftover lease fields after DEMO_MODE reseed.
            fixture_job = db.query(Job).filter_by(request_key='demo-review-queue').one()
            fixture_job.lease_token = 'stale-fixture-lease'
            fixture_job.lease_until = 1.0
            fixture_job.started_at = 1.0
            db.commit()
            seed(db)
            restored_fixture_course = db.get(Course, fixture_course.id)
            self.assertEqual(restored_fixture_course.publication_status, 'published')
            self.assertEqual(restored_fixture_course.cancellation_status, 'active')
            self.assertTrue(restored_fixture_course.demo)
            cleared_job = db.query(Job).filter_by(request_key='demo-review-queue').one()
            self.assertEqual(cleared_job.status, 'succeeded')
            self.assertIsNone(cleared_job.lease_token)
            self.assertIsNone(cleared_job.lease_until)
            self.assertIsNone(cleared_job.started_at)
            # When asthma+vaccine are both published, reseed keeps a pending Fixture review slot.
            for cand in db.query(Candidate).filter(Candidate.source_key.like('demo-candidate-%')).all():
                if cand.status != 'published':
                    cand.status = 'published'
                    cand.resulting_course_id = restored_course.id
            db.commit()
            seed(db)
            self.assertGreaterEqual(
                db.query(Candidate)
                .filter(
                    Candidate.source_key.like('demo-candidate-%'),
                    Candidate.status == 'pending',
                )
                .count(),
                1,
            )
            # Publishing that queue slot then reseeding must cancel its catalogue row (no orphan
            # listing / no 409 on the next publish of the same identity).
            queue = db.query(Candidate).filter_by(source_key='demo-candidate-queue').one()
            self.assertEqual(queue.status, 'pending')
            # Steady-state pending/held queue must refresh evidence on later reseeds (not only when
            # reviewable == 0 creates the slot).
            queue.status = 'held'
            queue.review_reason = 'Need offline confirmation'
            queue.data = {**(queue.data or {}), 'retrieved_at': 'STALE', 'title': 'STALE QUEUE TITLE'}
            stale_version = queue.version
            db.commit()
            seed(db)
            refreshed_queue = db.query(Candidate).filter_by(source_key='demo-candidate-queue').one()
            self.assertEqual(refreshed_queue.status, 'held')
            self.assertEqual((refreshed_queue.data or {}).get('retrieved_at'), 'fixture')
            self.assertEqual((refreshed_queue.data or {}).get('title'), 'Offline review queue (demo)')
            self.assertGreater(refreshed_queue.version, stale_version)
            refreshed_queue.status = 'pending'
            refreshed_queue.review_reason = ''
            db.commit()
            queue = refreshed_queue
            published_queue = self.client.post(
                '/api/v1/admin/candidates/' + queue.id + '/review',
                json={'action': 'publish', 'version': queue.version, 'reason': 'Publish queue slot for reseed cancel'},
            )
            self.assertEqual(published_queue.status_code, 200, published_queue.text)
            queue_course_id = published_queue.json()['resulting_course_id']
            self.assertTrue(queue_course_id)
            # Client publish committed on another connection — drop identity-map stale pending rows.
            db.expire_all()
            seed(db)
            reopened = db.query(Candidate).filter_by(source_key='demo-candidate-queue').one()
            self.assertEqual(reopened.status, 'pending')
            self.assertIsNone(reopened.resulting_course_id)
            cancelled_queue_course = db.get(Course, queue_course_id)
            self.assertEqual(cancelled_queue_course.publication_status, 'cancelled')
            self.assertEqual(cancelled_queue_course.cancellation_status, 'cancelled')
            listed_queue = self.client.get('/api/v1/trainings?period=all&q=Offline%20review%20queue').json()
            self.assertEqual(listed_queue.get('total'), 0)
            republished = self.client.post(
                '/api/v1/admin/candidates/' + reopened.id + '/review',
                json={
                    'action': 'publish',
                    'version': reopened.version,
                    'reason': 'Re-publish queue slot after reseed cancel',
                },
            )
            self.assertEqual(republished.status_code, 200, republished.text)
            self.assertEqual(republished.json()['resulting_course_id'], queue_course_id)
            # Offline DEMO-01 doctor path: catalogue + progress without Tavily/model spend.
            self.client.post('/api/v1/auth/logout')
            doctor_login = self.client.post(
                '/api/v1/auth/login',
                json={'email': 'doctor@carecredits.local', 'password': DEMO_PASSWORD},
            )
            self.assertEqual(doctor_login.status_code, 200, doctor_login.text)
            catalogue = self.client.get('/api/v1/trainings?page=1&page_size=20')
            self.assertEqual(catalogue.status_code, 200, catalogue.text)
            demo_rows = [row for row in catalogue.json().get('items') or [] if row.get('demo')]
            self.assertGreaterEqual(len(demo_rows), 1)
            progress = self.client.get('/api/v1/me/progress?year=' + str(__import__('datetime').date.today().year))
            self.assertEqual(progress.status_code, 200, progress.text)
            self.assertGreaterEqual(progress.json().get('attended') or 0, 1)
            suggestions = self.client.get('/api/v1/me/suggestions')
            self.assertEqual(suggestions.status_code, 200, suggestions.text)
            blocked_job = self.client.post(
                '/api/v1/admin/ingestion-jobs',
                headers={'Idempotency-Key': 'offline-demo-doctor-must-not-spend'},
                json={'query': 'should not enqueue', 'max_results': 1},
            )
            self.assertEqual(blocked_job.status_code, 403, blocked_job.text)

    def test_demo_mode_login_reseeds_documented_accounts(self):
        from seed_demo import DEMO_PASSWORD, seed
        from security import password_hash
        blocked = self.client.post(
            '/api/v1/auth/login',
            json={'email': 'demo@carecredits.local', 'password': DEMO_PASSWORD},
        )
        self.assertEqual(blocked.status_code, 401, blocked.text)
        with patch.dict(os.environ, {'DEMO_MODE': 'true'}):
            restored = self.client.post(
                '/api/v1/auth/login',
                json={'email': 'demo@carecredits.local', 'password': DEMO_PASSWORD},
            )
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()['email'], 'demo@carecredits.local')
            self.client.post('/api/v1/auth/logout')
            doctor = self.client.post(
                '/api/v1/auth/login',
                json={'email': 'doctor@carecredits.local', 'password': DEMO_PASSWORD},
            )
            self.assertEqual(doctor.status_code, 200, doctor.text)
            self.assertEqual(doctor.json()['role'], 'doctor')
            wrong = self.client.post(
                '/api/v1/auth/login',
                json={'email': 'demo@carecredits.local', 'password': 'Wrong-demo-password-999'},
            )
            self.assertEqual(wrong.status_code, 401, wrong.text)
            # Matching demo password must still restore an overwritten role (not only a broken hash).
            with self.Session() as db:
                seed(db)
                demo = db.query(Account).filter_by(email='demo@carecredits.local').one()
                demo.role = 'doctor'
                demo.password_hash = password_hash(DEMO_PASSWORD)
                db.commit()
            demoted = self.client.post(
                '/api/v1/auth/login',
                json={'email': 'demo@carecredits.local', 'password': DEMO_PASSWORD},
            )
            self.assertEqual(demoted.status_code, 200, demoted.text)
            self.assertEqual(demoted.json()['role'], 'operator')
