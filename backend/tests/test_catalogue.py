import os
import sys
import json
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

os.environ['APP_ENV'] = 'development'
os.environ['DEMO_MODE'] = 'false'
os.environ['ALLOW_SIGNUP'] = 'true'
os.environ['SCRAPER_SERVICE_TOKEN'] = 'test-service-token'
os.environ['DAILY_SCRAPE_ENABLED'] = 'false'
os.environ.pop('TYPESAFE_API_KEY', None)

FOLDER = tempfile.TemporaryDirectory()
DB_PATH = Path(FOLDER.name) / 'catalogue-test.db'
os.environ['DATABASE_URL'] = 'sqlite:///' + str(DB_PATH)

from main import app, source_key
from database import Base, get_db, engine
from catalogue import course_public
from portal_models import Account, Candidate, Course, FieldEvidence, Job, fill_course
from security import password_hash
from shared.contracts import Training
from schedule import daily_request_key, enqueue_daily, load_topics


QUOTE = (
    'Primary Care Update by Academy of Family Physicians in Malaysia Kuala Lumpur. '
    '2026-06-01 in person. CPD points 2. Source backed excerpt.'
)


def sample(**overrides):
    row = {
        'title': 'Primary Care Update 2026',
        'provider': 'Academy of Family Physicians',
        'mode': 'in_person',
        'country': 'MY',
        'start_date': '2026-06-01',
        'city': 'Kuala Lumpur',
        'points': 2,
        'credit_label': 'CPD',
        'source_url': 'https://example.org/afpm-primary-care-update-2026',
        'source_text': QUOTE,
        'evidence': {key: QUOTE for key in ['title', 'provider', 'mode', 'country', 'start_date', 'city', 'points', 'credit_label']},
    }
    row.update(overrides)
    return Training(**row).model_dump(mode='json')


class CatalogueApiTests(unittest.TestCase):
    def setUp(self):
        if 'demo.db' in str(engine.url):
            raise RuntimeError('Catalogue tests must not drop the live DEMO_MODE database')
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

        def dependency():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = dependency
        with self.Session() as db:
            op = Account(
                email='op@example.com',
                name='Operator',
                password_hash=password_hash('CareCredits-demo-2026'),
                role='operator',
            )
            db.add(op)
            db.commit()
        self.client = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'http://127.0.0.1:3000'})
        self.service = {'Authorization': 'Bearer test-service-token'}
        self.env = patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}, clear=False)
        self.env.start()
        self.scraper_ready = patch(
            'main._scraper_service_status',
            return_value={'status': 'ready', 'reachable': True, 'tavily_configured': True, 'model_ready': True},
        )
        self.scraper_ready.start()
        self.keyfile = patch('jev.keyfile_path')
        mocked = self.keyfile.start()
        mocked.return_value.is_file.return_value = False

    def tearDown(self):
        self.keyfile.stop()
        self.scraper_ready.stop()
        self.env.stop()
        app.dependency_overrides.clear()

    def test_connect_and_lookup_exact(self):
        training = sample()
        with self.Session() as db:
            db.add(fill_course(Course(source_key=source_key(training)), training))
            db.commit()
        self.assertEqual(self.client.get('/internal/v1/catalogue/connect', headers=self.service).status_code, 200)
        lookup = self.client.post('/internal/v1/catalogue/lookup', json={'candidate': training}, headers=self.service)
        self.assertEqual(lookup.status_code, 200, lookup.text)
        self.assertIsNotNone(lookup.json()['exact'])
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={'candidate': training, 'matches': []},
            headers=self.service,
        )
        self.assertEqual(decide.json()['decision'], 'exists')

    def test_near_neighbours_omit_cancelled_exact_cancelled_still_exists(self):
        """Fuzzy near-match must not feed cancelled rows to Jev; exact cancelled still short-circuits."""
        cancelled_payload = sample(
            title='Probe GP Day',
            source_url='https://example.org/probe-gp-day',
            start_date='2026-07-01',
        )
        # Different identity (title/url) but same provider/city/date so score ≥ 5 without listed_filter.
        different = sample(
            title='Different Session Name',
            source_url='https://example.org/different-session-name',
            start_date='2026-07-01',
        )
        with self.Session() as db:
            cancelled = fill_course(Course(source_key=source_key(cancelled_payload)), cancelled_payload)
            cancelled.publication_status = 'cancelled'
            cancelled.cancellation_status = 'cancelled'
            live = fill_course(
                Course(source_key=source_key(sample(title='Live Neighbour GP', source_url='https://example.org/live-neighbour'))),
                sample(title='Live Neighbour GP', source_url='https://example.org/live-neighbour', start_date='2026-07-01'),
            )
            db.add_all([cancelled, live])
            db.commit()
            cancelled_id, live_id = cancelled.id, live.id
        near = self.client.post('/internal/v1/catalogue/lookup', json={'candidate': different}, headers=self.service)
        self.assertEqual(near.status_code, 200, near.text)
        body = near.json()
        self.assertIsNone(body['exact'])
        match_ids = {row['id'] for row in body['matches']}
        self.assertNotIn(cancelled_id, match_ids)
        self.assertIn(live_id, match_ids)
        # Exact cancelled identity still resolves for re-list soft-refresh (not a near-match).
        exact = self.client.post(
            '/internal/v1/catalogue/lookup',
            json={'candidate': cancelled_payload},
            headers=self.service,
        )
        self.assertEqual(exact.status_code, 200, exact.text)
        self.assertEqual(exact.json()['exact']['id'], cancelled_id)
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={'candidate': cancelled_payload, 'matches': []},
            headers=self.service,
        )
        self.assertEqual(decide.json()['decision'], 'exists')
        self.assertEqual(decide.json()['matched_session_id'], cancelled_id)

    def test_near_neighbours_omit_cancellation_status_drift(self):
        """listed_filter must honour cancellation_status even if publication_status drifted published."""
        drifted_payload = sample(
            title='Drift Cancelled GP Day',
            source_url='https://example.org/drift-cancelled-gp',
            start_date='2026-07-02',
        )
        different = sample(
            title='Other Drift Session',
            source_url='https://example.org/other-drift-session',
            start_date='2026-07-02',
        )
        with self.Session() as db:
            drifted = fill_course(Course(source_key=source_key(drifted_payload)), drifted_payload)
            drifted.publication_status = 'published'
            drifted.cancellation_status = 'cancelled'
            live = fill_course(
                Course(source_key=source_key(sample(title='Live Drift Neighbour', source_url='https://example.org/live-drift'))),
                sample(title='Live Drift Neighbour', source_url='https://example.org/live-drift', start_date='2026-07-02'),
            )
            db.add_all([drifted, live])
            db.commit()
            drifted_id, live_id = drifted.id, live.id
        near = self.client.post('/internal/v1/catalogue/lookup', json={'candidate': different}, headers=self.service)
        self.assertEqual(near.status_code, 200, near.text)
        match_ids = {row['id'] for row in near.json()['matches']}
        self.assertNotIn(drifted_id, match_ids)
        self.assertIn(live_id, match_ids)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        listed = self.client.get('/api/v1/trainings?period=all&q=Drift+Cancelled').json()
        self.assertFalse(any(item['id'] == drifted_id for item in listed['items']))

    def test_connect_fails_closed_when_database_unavailable(self):
        class Boom:
            def execute(self, *_args, **_kwargs):
                raise RuntimeError('db down')

        def dependency():
            yield Boom()

        app.dependency_overrides[get_db] = dependency
        down = self.client.get('/internal/v1/catalogue/connect', headers=self.service)
        self.assertEqual(down.status_code, 503, down.text)
        body = down.json()['error']
        self.assertEqual(body['code'], 'unavailable')
        self.assertIn('Catalogue database is unavailable', body['message'])
        self.assertNotIn('db down', down.text)
        self.assertNotIn('RuntimeError', down.text)

    def test_decide_stores_judgment_on_existing_candidate(self):
        training = sample(title='Held GP Workshop', source_url='https://example.org/held-gp-workshop')
        key = source_key(training)
        with self.Session() as db:
            job = Job(account_id=db.query(Account).first().id, request_key='held-decide', query='GP', status='succeeded')
            db.add(job)
            db.flush()
            candidate = Candidate(job_id=job.id, source_key=key, data=training, status='pending')
            db.add(candidate)
            db.commit()
            candidate_id = candidate.id
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={'candidate': training, 'matches': []},
            headers=self.service,
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        self.assertEqual(decide.json()['decision'], 'new')
        self.assertEqual(decide.json()['candidate_id'], candidate_id)
        with self.Session() as db:
            stored = db.get(Candidate, candidate_id)
            self.assertEqual((stored.data or {}).get('_judgment', {}).get('decision'), 'new')

    def test_decide_exact_match_stores_exists_judgment_on_pending_candidate(self):
        training = sample(title='Exact GP Workshop', source_url='https://example.org/exact-gp-workshop')
        key = source_key(training)
        with self.Session() as db:
            course = fill_course(Course(source_key=key), training)
            db.add(course)
            job = Job(account_id=db.query(Account).first().id, request_key='exact-decide', query='GP', status='succeeded')
            db.add(job)
            db.flush()
            candidate = Candidate(job_id=job.id, source_key=key, data=training, status='pending')
            db.add(candidate)
            db.commit()
            candidate_id = candidate.id
            course_id = course.id
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={'candidate': training, 'matches': []},
            headers=self.service,
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        body = decide.json()
        self.assertEqual(body['decision'], 'exists')
        self.assertEqual(body['matched_session_id'], course_id)
        self.assertEqual(body['candidate_id'], candidate_id)
        with self.Session() as db:
            stored = db.get(Candidate, candidate_id)
            judgment = (stored.data or {}).get('_judgment') or {}
            self.assertEqual(judgment.get('decision'), 'exists')
            self.assertEqual(judgment.get('matched_session_id'), course_id)

    def test_decide_new_without_matches_and_save(self):
        training = sample(title='Brand New GP Workshop', source_url='https://example.org/new-gp-workshop')
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={'candidate': training, 'matches': []},
            headers=self.service,
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        self.assertEqual(decide.json()['decision'], 'new')
        save = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': decide.json()},
            headers=self.service,
        )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['decision'], 'new')
        self.assertEqual(save.json()['status'], 'pending')
        self.assertFalse(save.json().get('course_id'))
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        listed = self.client.get('/api/v1/trainings?period=all&include_unknown=true')
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()['total'], 0)
        queue = self.client.get('/api/v1/admin/candidates').json()
        self.assertEqual(queue['items'][0]['status'], 'pending')

    def test_save_new_auto_publishes_only_when_policy_allows(self):
        training = sample(title='Auto Publish Workshop', source_url='https://example.org/auto-publish-workshop')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true'}):
            save = self.client.post(
                '/internal/v1/catalogue/save',
                json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 1, 'probabilities': {'new': 1}}},
                headers=self.service,
            )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['status'], 'published')
        self.assertTrue(save.json().get('course_id'))
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        listed = self.client.get('/api/v1/trainings?period=all&include_unknown=true')
        self.assertGreaterEqual(listed.json()['total'], 1)

    def test_auto_publish_requires_confidence_floor(self):
        training = sample(title='Low Confidence New', source_url='https://example.org/low-confidence-new')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            save = self.client.post(
                '/internal/v1/catalogue/save',
                json={
                    'candidate': training,
                    'judgment': {'decision': 'new', 'confidence': 0.4, 'probabilities': {'new': 0.4, 'uncertain': 0.6}},
                },
                headers=self.service,
            )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['status'], 'pending')
        self.assertFalse(save.json().get('course_id'))
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        listed = self.client.get('/api/v1/trainings?period=all&q=Low%20Confidence').json()
        self.assertEqual(listed['total'], 0)
        queue = self.client.get('/api/v1/admin/candidates').json()['items']
        heldish = next(item for item in queue if item['data']['title'] == 'Low Confidence New')
        self.assertEqual(heldish['status'], 'pending')

    def test_auto_publish_rejects_nan_confidence(self):
        training = sample(title='NaN Confidence New', source_url='https://example.org/nan-confidence-new')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            save = self.client.post(
                '/internal/v1/catalogue/save',
                json={
                    'candidate': training,
                    'judgment': {'decision': 'new', 'confidence': 'nan', 'probabilities': {'new': 1}},
                },
                headers=self.service,
            )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['status'], 'pending')
        self.assertFalse(save.json().get('course_id'))

    def test_auto_publish_rejects_bool_confidence(self):
        """JSON true must not float(True)==1.0 past the auto-publish floor."""
        training = sample(title='Bool Confidence New', source_url='https://example.org/bool-confidence-new')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            save = self.client.post(
                '/internal/v1/catalogue/save',
                json={
                    'candidate': training,
                    'judgment': {'decision': 'new', 'confidence': True, 'probabilities': {'new': 1}},
                },
                headers=self.service,
            )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['status'], 'pending')
        self.assertFalse(save.json().get('course_id'))

    def test_training_fee_points_reject_bool(self):
        """Catalogue Training fee/points must not coerce JSON true/false to 1.0/0.0."""
        base = sample(title='Bool Fee Points', source_url='https://example.org/bool-fee-points')
        for field, value in (('fee', True), ('points', True), ('fee', False), ('points', False)):
            payload = {**base, field: value, 'currency': 'MYR', 'credit_label': 'CPD'}
            if field == 'fee':
                payload['evidence'] = {**base['evidence'], 'fee': QUOTE, 'currency': QUOTE}
            with self.assertRaises(Exception):
                Training(**payload)

    def test_auto_publish_at_confidence_floor(self):
        training = sample(title='Floor Confidence New', source_url='https://example.org/floor-confidence-new')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            save = self.client.post(
                '/internal/v1/catalogue/save',
                json={
                    'candidate': training,
                    'judgment': {'decision': 'new', 'confidence': 0.7, 'probabilities': {'new': 0.7}},
                },
                headers=self.service,
            )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['status'], 'published')
        self.assertTrue(save.json().get('course_id'))

    def test_auto_publish_promotes_pending_and_stores_field_evidence(self):
        training = sample(title='Promote Pending Auto', source_url='https://example.org/promote-pending-auto')
        pending = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 0.2, 'probabilities': {'new': 0.2}}},
            headers=self.service,
        )
        self.assertEqual(pending.status_code, 200, pending.text)
        pending_id = pending.json()['candidate_id']
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true', 'JEV_CONFIDENCE_FLOOR': '0.7'}):
            published = self.client.post(
                '/internal/v1/catalogue/save',
                json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 0.95, 'probabilities': {'new': 0.95}}},
                headers=self.service,
            )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()['status'], 'published')
        self.assertEqual(published.json()['candidate_id'], pending_id)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        queue = self.client.get('/api/v1/admin/candidates').json()['items']
        self.assertFalse(any(item['id'] == pending_id for item in queue))
        detail = self.client.get('/api/v1/trainings/' + published.json()['course_id']).json()
        self.assertEqual(detail.get('verification_status'), 'unverified')
        self.assertGreaterEqual(len(detail.get('field_evidence') or []), 4)
        self.assertTrue(all(item.get('excerpt') for item in detail['field_evidence']))
        # Auto-publish stores excerpts without a reviewer stamp (reviewed_at stays null).
        self.assertTrue(all(item.get('reviewed_at') is None for item in detail['field_evidence']))
        with self.Session() as db:
            rows = db.query(FieldEvidence).filter_by(course_id=published.json()['course_id']).all()
            self.assertTrue(all(row.reviewed_by is None and row.reviewed_at is None for row in rows))

    def test_uncertain_stays_held_even_when_auto_publish_enabled(self):
        training = sample(title='Uncertain Hold Workshop', source_url='https://example.org/uncertain-hold')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true'}):
            save = self.client.post(
                '/internal/v1/catalogue/save',
                json={
                    'candidate': training,
                    'judgment': {
                        'decision': 'uncertain',
                        'confidence': 0.9,
                        'probabilities': {'uncertain': 0.9, 'new': 0.1},
                        'warning': 'Ambiguous near match',
                    },
                },
                headers=self.service,
            )
        self.assertEqual(save.status_code, 200, save.text)
        self.assertEqual(save.json()['status'], 'held')
        self.assertFalse(save.json().get('course_id'))
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        listed = self.client.get('/api/v1/trainings?period=all&q=Uncertain%20Hold').json()
        self.assertEqual(listed['total'], 0)
        queue = self.client.get('/api/v1/admin/candidates').json()['items']
        held = next(item for item in queue if item['data']['title'] == 'Uncertain Hold Workshop')
        self.assertEqual(held['status'], 'held')
        self.assertIn('Ambiguous near match', held['reason'])

    def test_near_match_without_typesafe_is_uncertain(self):
        training = sample()
        with self.Session() as db:
            course = fill_course(Course(source_key='other-key'), training)
            db.add(course)
            db.commit()
            course_id = course.id
        other = sample(title='Primary Care Update Evening', source_url='https://example.org/other')
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={
                'candidate': other,
                'matches': [{'id': course_id, 'title': training['title'], 'provider': training['provider'], 'start_date': training['start_date'], 'city': training['city'], 'mode': training['mode']}],
            },
            headers=self.service,
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        self.assertEqual(decide.json()['decision'], 'uncertain')
        save = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': other, 'judgment': decide.json()},
            headers=self.service,
        )
        self.assertEqual(save.json()['status'], 'held')

    def test_load_topics_clamps_and_skips_invalid_max_results(self):
        import schedule as schedule_mod

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'topics.json'
            path.write_text(
                '[{"query":"GP CPD valid topic one","max_results":99},'
                '{"query":"GP CPD valid topic two","max_results":"abc"},'
                '{"query":"x","max_results":3},'
                '{"query":"GP CPD valid topic three","max_results":0},'
                'null,'
                '{"query":"GP CPD bool true topic","max_results":true},'
                '{"query":"GP CPD bool false topic","max_results":false},'
                '{"query":true,"max_results":3},'
                '{"query":12345,"max_results":3},'
                '{"query":"GP CPD valid topic four"}]',
                encoding='utf-8',
            )
            with patch.object(schedule_mod, 'TOPICS_PATH', path):
                topics = load_topics()
            by_query = {item['query']: item['max_results'] for item in topics}
            self.assertEqual(by_query['GP CPD valid topic one'], 5)
            self.assertNotIn('GP CPD valid topic two', by_query)
            self.assertNotIn('x', by_query)
            self.assertEqual(by_query['GP CPD valid topic three'], 1)
            self.assertEqual(by_query['GP CPD valid topic four'], 5)
            self.assertNotIn('GP CPD bool true topic', by_query)
            self.assertNotIn('GP CPD bool false topic', by_query)
            self.assertNotIn('True', by_query)
            self.assertNotIn('12345', by_query)
            # Non-finite max_results must skip (not OverflowError crash) — observe usage parity.
            path.write_text(
                json.dumps(
                    [
                        {'query': 'GP CPD infinity topic padded', 'max_results': 1e309},
                        {'query': 'GP CPD nan topic padded xx', 'max_results': float('nan')},
                        {'query': 'GP CPD valid after inf topic', 'max_results': 2},
                    ]
                ),
                encoding='utf-8',
            )
            with patch.object(schedule_mod, 'TOPICS_PATH', path):
                finite = load_topics()
            self.assertEqual([item['query'] for item in finite], ['GP CPD valid after inf topic'])
            self.assertEqual(finite[0]['max_results'], 2)
            # No silent [:20] truncate — ceiling owns the spend bound.
            many = [{'query': f'GP CPD many topic {i:02d} padded', 'max_results': 2} for i in range(25)]
            path.write_text(json.dumps(many), encoding='utf-8')
            with patch.object(schedule_mod, 'TOPICS_PATH', path):
                self.assertEqual(len(load_topics()), 25)
            bad = Path(folder) / 'bad.json'
            bad.write_text('{not-json', encoding='utf-8')
            with patch.object(schedule_mod, 'TOPICS_PATH', bad):
                with self.assertRaises(ValueError):
                    load_topics()
                result = enqueue_daily(self.Session())
            self.assertEqual(result['enqueued'], 0)
            self.assertIn('not valid JSON', result['error'])
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        with patch('main.load_topics', side_effect=ValueError('scrape_topics.json is not valid JSON')):
            listed = self.client.get('/api/v1/admin/scrape-topics')
        self.assertEqual(listed.status_code, 503, listed.text)
        self.assertEqual(listed.json()['error']['code'], 'unavailable')

    def test_daily_scrape_enqueue(self):
        from schedule import local_today
        topics = load_topics()
        self.assertTrue(topics)
        self.assertGreaterEqual(len(topics), 11)
        self.assertTrue(any('site:' in item['query'] for item in topics))
        self.assertTrue(any(item['max_results'] != 5 for item in topics), 'at least one topic should exercise non-default max_results')
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value='2099-01-15'
        ):
            first = enqueue_daily(self.Session())
        self.assertEqual(first['day'], '2099-01-15')
        self.assertEqual(first['ceiling'], 10)
        self.assertEqual(first['enqueued'], 10)
        self.assertGreaterEqual(first['skipped'], 2)
        by_query = {item['query']: max(1, min(int(item['max_results']), 5)) for item in topics}
        with self.Session() as db:
            matched = [job for job in db.query(Job).all() if job.query in by_query]
            self.assertEqual(len(matched), 10)
            for job in matched:
                self.assertEqual(job.max_results, by_query[job.query])
                self.assertEqual(job.status, 'queued')
                job.status = 'succeeded'
            db.commit()
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value='2099-01-15'
        ):
            second = enqueue_daily(self.Session())
            self.assertEqual(second['enqueued'], 0)
            # force must not replay succeeded spend
            forced_succeeded = enqueue_daily(self.Session(), force=True)
        self.assertEqual(forced_succeeded['enqueued'], 0)
        with self.Session() as db:
            idle = [job for job in db.query(Job).all() if job.query in by_query][:2]
            for job in idle:
                job.status = 'interrupted'
            db.commit()
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value='2099-01-15'
        ):
            forced_local = enqueue_daily(self.Session(), force=True)
        self.assertGreaterEqual(forced_local['enqueued'], 1)
        with self.Session() as db:
            forced_rows = [job for job in db.query(Job).all() if job.query in by_query and job.status == 'queued']
            self.assertGreaterEqual(len(forced_rows), 1)
            still_succeeded = [
                job for job in db.query(Job).all() if job.query in by_query and job.status == 'succeeded'
            ]
            self.assertGreaterEqual(len(still_succeeded), 1)
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value='2099-01-16'
        ):
            next_day = enqueue_daily(self.Session())
        self.assertEqual(next_day['day'], '2099-01-16')
        self.assertEqual(next_day['enqueued'], 10)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        forced = self.client.post('/api/v1/admin/daily-scrape?force=true')
        self.assertEqual(forced.status_code, 202, forced.text)
        listed = self.client.get('/api/v1/admin/scrape-topics')
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertGreaterEqual(len(body['topics']), 1)
        self.assertEqual(body['topics'][0].keys(), {'query', 'max_results'})
        self.assertGreaterEqual(body['ceiling'], 1)
        self.assertTrue(body['day'])
        self.assertEqual(body['day'], local_today())
        with self.Session() as db:
            db.add(
                Account(
                    email='doc@example.com',
                    name='Doctor',
                    password_hash=password_hash('CareCredits-demo-2026'),
                    role='doctor',
                )
            )
            db.commit()
        self.client.post('/api/v1/auth/logout')
        self.client.post('/api/v1/auth/login', json={'email': 'doc@example.com', 'password': 'CareCredits-demo-2026'})
        self.assertEqual(self.client.get('/api/v1/admin/scrape-topics').status_code, 403)

    def test_course_public_omits_non_web_source_url(self):
        with self.Session() as db:
            course = fill_course(Course(source_key='public-unsafe'), sample())
            course.data = {**(course.data or {}), 'source_url': 'javascript:alert(1)'}
            db.add(course)
            db.commit()
            payload = course_public(course)
        self.assertIsNone(payload['source_url'])
        self.assertIsNone(payload['data']['source_url'])
        self.assertNotIn('javascript:', str(payload))

    def test_daily_scrape_unique_key_race_skips(self):
        from sqlalchemy.exc import IntegrityError

        topics = [{'query': 'Integrity race GP CPD topic', 'max_results': 2}]
        day = '2099-03-01'

        class BoomNested:
            def __enter__(self):
                raise IntegrityError('INSERT', {}, Exception('UNIQUE constraint failed'))

            def __exit__(self, *args):
                return False

        with self.Session() as db:
            with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
                'schedule.local_today', return_value=day
            ), patch('schedule.load_topics', return_value=topics), patch.object(db, 'begin_nested', return_value=BoomNested()):
                result = enqueue_daily(db, force=False)
        self.assertEqual(result['enqueued'], 0, result)
        self.assertEqual(result['skipped'], 1, result)
        with self.Session() as db:
            self.assertEqual(db.query(Job).filter_by(query=topics[0]['query']).count(), 0)
        schedule_src = Path(__file__).resolve().parents[1].joinpath('schedule.py').read_text(encoding='utf-8')
        self.assertIn('begin_nested', schedule_src)
        self.assertIn('IntegrityError', schedule_src)
        self.assertIn('with_for_update', schedule_src)
        self.assertIn('daily_jobs_used', schedule_src)
        self.assertIn("like(f'daily:{day}:%')", schedule_src)
        self.assertIn('daily_request_key', schedule_src)
        self.assertNotIn('topics[:20]', schedule_src)

    def test_daily_scrape_ceiling_spans_mid_day_topic_swap(self):
        """Whole-day ceiling must count prior daily keys after the curated list changes."""
        day = '2099-04-01'
        first = [{'query': 'Swap topic A GP CPD', 'max_results': 2}, {'query': 'Swap topic B GP CPD', 'max_results': 2}]
        second = [{'query': 'Swap topic C GP CPD', 'max_results': 2}, {'query': 'Swap topic D GP CPD', 'max_results': 2}]
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '2'}, clear=False), patch(
            'schedule.local_today', return_value=day
        ), patch('schedule.load_topics', return_value=first):
            first_run = enqueue_daily(self.Session())
        self.assertEqual(first_run['enqueued'], 2, first_run)
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '2'}, clear=False), patch(
            'schedule.local_today', return_value=day
        ), patch('schedule.load_topics', return_value=second):
            second_run = enqueue_daily(self.Session())
        self.assertEqual(second_run['enqueued'], 0, second_run)
        self.assertEqual(second_run['skipped'], 2, second_run)
        with self.Session() as db:
            self.assertEqual(db.query(Job).filter(Job.request_key.like(f'daily:{day}:%')).count(), 2)
            self.assertEqual(db.query(Job).filter_by(query=second[0]['query']).count(), 0)

    def test_enqueue_daily_skips_bool_max_results_and_pads_query(self):
        """enqueue_daily re-validates topics so patched/bad rows cannot invent spend keys."""
        day = '2099-05-01'
        topics = [
            {'query': '  Enqueue strip query GP CPD  ', 'max_results': 2},
            {'query': 'Enqueue bool max GP CPD', 'max_results': True},
            {'query': 'Enqueue inf max GP CPD xx', 'max_results': float('inf')},
            {'query': 12345, 'max_results': 2},
            {'query': 'x', 'max_results': 2},
        ]
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value=day
        ), patch('schedule.load_topics', return_value=topics):
            result = enqueue_daily(self.Session())
        self.assertEqual(result['enqueued'], 1, result)
        self.assertEqual(result['skipped'], 4, result)
        with self.Session() as db:
            rows = db.query(Job).filter(Job.request_key.like(f'daily:{day}:%')).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].query, 'Enqueue strip query GP CPD')
            self.assertEqual(rows[0].max_results, 2)

    def test_daily_scrape_force_requeues_failed_partial_not_running(self):
        topics = [
            {'query': 'Force failed topic GP CPD', 'max_results': 2},
            {'query': 'Force partial topic GP CPD', 'max_results': 2},
            {'query': 'Force running topic GP CPD', 'max_results': 2},
        ]
        day = '2099-02-01'
        now = time.time()
        with self.Session() as db:
            op = db.query(Account).filter_by(role='operator').one()
            statuses = ('failed', 'partial', 'running')
            for topic, status in zip(topics, statuses):
                job = Job(
                    account_id=op.id,
                    request_key=daily_request_key(day, topic['query']),
                    query=topic['query'],
                    max_results=topic['max_results'],
                    status=status,
                )
                # Live running must keep a fresh lease so force skips it (aged-stuck is covered separately).
                if status == 'running':
                    job.lease_token = 'live-lease'
                    job.lease_until = now + 600
                    job.started_at = now
                db.add(job)
            db.commit()
        with self.Session() as db:
            before = {
                job.query: job.attempt
                for job in db.query(Job).all()
                if job.query in {topic['query'] for topic in topics}
            }
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value=day
        ), patch('schedule.load_topics', return_value=topics):
            forced = enqueue_daily(self.Session(), force=True)
        self.assertEqual(forced['enqueued'], 2, forced)
        self.assertEqual(forced['skipped'], 1, forced)
        with self.Session() as db:
            by_query = {topic['query'] for topic in topics}
            rows = {
                job.query: (job.status, job.attempt)
                for job in db.query(Job).all()
                if job.query in by_query
            }
            self.assertEqual(rows[topics[0]['query']][0], 'queued')
            self.assertEqual(rows[topics[1]['query']][0], 'queued')
            self.assertEqual(rows[topics[2]['query']][0], 'running')
            self.assertEqual(rows[topics[0]['query']][1], before[topics[0]['query']] + 1)
            self.assertEqual(rows[topics[1]['query']][1], before[topics[1]['query']] + 1)
            self.assertEqual(rows[topics[2]['query']][1], before[topics[2]['query']])

    def test_daily_scrape_force_expires_aged_stuck_running(self):
        """force=true must expire aged-stuck running leases before skipping non-idle statuses."""
        topic = {'query': 'Force aged stuck GP CPD', 'max_results': 2}
        day = '2099-02-15'
        with self.Session() as db:
            op = db.query(Account).filter_by(role='operator').one()
            db.add(
                Job(
                    account_id=op.id,
                    request_key=daily_request_key(day, topic['query']),
                    query=topic['query'],
                    max_results=topic['max_results'],
                    status='running',
                    lease_token='stale-lease',
                    lease_until=1.0,  # long expired
                    started_at=1.0,
                    attempt=1,
                )
            )
            db.commit()
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value=day
        ), patch('schedule.load_topics', return_value=[topic]):
            forced = enqueue_daily(self.Session(), force=True)
        self.assertEqual(forced['enqueued'], 1, forced)
        self.assertEqual(forced['skipped'], 0, forced)
        with self.Session() as db:
            job = db.query(Job).filter_by(query=topic['query']).one()
            self.assertEqual(job.status, 'queued')
            self.assertIsNone(job.lease_token)
            self.assertIsNone(job.lease_until)
            self.assertIsNone(job.started_at)
            self.assertEqual(job.attempt, 2)

    def test_daily_scrape_force_refreshes_created_at(self):
        """Force requeue must refresh created_at so retention cannot blank fresh snippets."""
        from portal_models import purge_expired_source_text

        topic = {'query': 'Force created_at GP CPD', 'max_results': 2}
        day = '2099-02-20'
        aged = time.time() - 40 * 86400
        with self.Session() as db:
            op = db.query(Account).filter_by(role='operator').one()
            db.add(
                Job(
                    account_id=op.id,
                    request_key=daily_request_key(day, topic['query']),
                    query=topic['query'],
                    max_results=topic['max_results'],
                    status='failed',
                    created_at=aged,
                    attempt=1,
                )
            )
            db.commit()
        with patch.dict(os.environ, {'DAILY_SCRAPE_JOB_CEILING': '10'}, clear=False), patch(
            'schedule.local_today', return_value=day
        ), patch('schedule.load_topics', return_value=[topic]):
            forced = enqueue_daily(self.Session(), force=True)
        self.assertEqual(forced['enqueued'], 1, forced)
        with self.Session() as db:
            job = db.query(Job).filter_by(query=topic['query']).one()
            self.assertEqual(job.status, 'queued')
            self.assertGreater(job.created_at, aged + 30 * 86400)
            job.status = 'succeeded'
            job.result = {'sources': [{'url': 'https://example.org/fresh', 'snippet': 'fresh spend evidence'}]}
            db.commit()
            job_id = job.id
        with self.Session() as db:
            purge_expired_source_text(db)
            db.commit()
            job = db.get(Job, job_id)
            snippet = ((job.result or {}).get('sources') or [{}])[0].get('snippet')
            self.assertEqual(snippet, 'fresh spend evidence')

    def test_auto_daily_scrape_stays_off_until_tavily_and_model_ready(self):
        from main import _paid_scrape_ready
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': False}):
            self.assertFalse(_paid_scrape_ready())
        with patch('main._scraper_service_status', return_value={'tavily_configured': False, 'model_ready': True}):
            self.assertFalse(_paid_scrape_ready())
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': True}):
            self.assertTrue(_paid_scrape_ready())

    def test_operator_api_blocks_tavily_spend_without_model(self):
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': False}):
            blocked = self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query': 'GP CPD Kuala Lumpur'},
                headers={'Idempotency-Key': 'tavily-only-block'},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(
                blocked.json()['error']['message'],
                'Live discovery stays off until Tavily and the open-weight model are ready.',
            )
            daily = self.client.post('/api/v1/admin/daily-scrape')
            self.assertEqual(daily.status_code, 409, daily.text)
            retry = self.client.post('/api/v1/admin/ingestion-jobs/missing-job/retry')
            self.assertEqual(retry.status_code, 409, retry.text)
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': True}):
            allowed = self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query': 'GP CPD Kuala Lumpur'},
                headers={'Idempotency-Key': 'tavily-ready-allow'},
            )
            self.assertEqual(allowed.status_code, 202, allowed.text)

    def test_claim_blocks_tavily_spend_without_model(self):
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': True}):
            queued = self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query': 'GP CPD Kuala Lumpur'},
                headers={'Idempotency-Key': 'tavily-claim-block'},
            )
        self.assertEqual(queued.status_code, 202, queued.text)
        job_id = queued.json()['id']
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': False}):
            blocked = self.client.post('/internal/v1/jobs/claim', headers=self.service)
        self.assertEqual(blocked.status_code, 204, blocked.text)
        self.assertEqual(blocked.headers.get('x-care-claim-reason'), 'not_ready')
        with patch('main._scraper_service_status', return_value={'tavily_configured': True, 'model_ready': True}):
            claimed = self.client.post('/internal/v1/jobs/claim', headers=self.service)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json()['id'], job_id)

    def test_operator_api_blocks_when_scraper_health_unreachable(self):
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        unreachable = {'status': 'unreachable', 'reachable': False, 'tavily_configured': False, 'model_ready': False}
        with patch('main._scraper_service_status', return_value=unreachable):
            blocked = self.client.post(
                '/api/v1/admin/ingestion-jobs',
                json={'query': 'GP CPD Kuala Lumpur'},
                headers={'Idempotency-Key': 'health-down-block'},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            daily = self.client.post('/api/v1/admin/daily-scrape')
            self.assertEqual(daily.status_code, 409, daily.text)
            claim = self.client.post('/internal/v1/jobs/claim', headers=self.service)
            self.assertEqual(claim.status_code, 204, claim.text)
            self.assertEqual(claim.headers.get('x-care-claim-reason'), 'not_ready')

    def test_changed_content_queues_refresh_without_duplicate(self):
        training = sample()
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true'}):
            first = self.client.post(
                '/internal/v1/catalogue/save',
                json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 1, 'probabilities': {'new': 1}}},
                headers=self.service,
            )
        self.assertEqual(first.status_code, 200, first.text)
        course_id = first.json()['course_id']
        changed = sample()
        changed['description'] = 'Updated brochure copy with a new fee note.'
        changed['fee'] = 150
        changed['currency'] = 'MYR'
        changed['evidence'] = {**changed['evidence'], 'fee': QUOTE, 'currency': QUOTE, 'description': QUOTE}
        again = self.client.post(
            '/internal/v1/catalogue/save',
            json={
                'candidate': changed,
                'judgment': {'decision': 'exists', 'confidence': 1, 'matched_session_id': course_id, 'probabilities': {'exists': 1}},
            },
            headers=self.service,
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()['status'], 'exists')
        self.assertEqual(again.json()['course_id'], course_id)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        listed = self.client.get('/api/v1/trainings?period=all&q=Primary%20Care%20Update').json()
        self.assertEqual(listed['total'], 1)
        queue = self.client.get('/api/v1/admin/candidates').json()['items']
        held = next(item for item in queue if item['id'] == again.json()['candidate_id'])
        self.assertEqual(held['status'], 'held')
        diff = {row['field']: row for row in held['data'].get('_refresh_diff') or []}
        self.assertEqual(diff['fee']['published'], None)
        self.assertEqual(diff['fee']['proposed'], 150)
        self.assertIn('description', diff)
        published = self.client.post(
            '/api/v1/admin/candidates/' + held['id'] + '/review',
            json={'action': 'publish', 'reason': 'Fee change is source-backed', 'version': held['version']},
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()['status'], 'published')
        self.assertEqual(published.json()['resulting_course_id'], course_id)
        listed = self.client.get('/api/v1/trainings?period=all&q=Primary%20Care%20Update').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['id'], course_id)
        self.assertEqual(listed['items'][0]['fee'], 150)

    def test_exists_refresh_updates_matched_course_when_source_key_drifts(self):
        training = sample(title='Primary Care Update 2026')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true'}):
            first = self.client.post(
                '/internal/v1/catalogue/save',
                json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 1, 'probabilities': {'new': 1}}},
                headers=self.service,
            )
        course_id = first.json()['course_id']
        renamed = sample(title='Primary Care Update KL 2026')
        renamed['evidence'] = {**renamed['evidence'], 'title': QUOTE}
        renamed['source_text'] = QUOTE
        again = self.client.post(
            '/internal/v1/catalogue/save',
            json={
                'candidate': renamed,
                'judgment': {'decision': 'exists', 'confidence': 1, 'matched_session_id': course_id, 'probabilities': {'exists': 1}},
            },
            headers=self.service,
        )
        self.assertEqual(again.json()['course_id'], course_id)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        held_id = again.json()['candidate_id']
        held = next(item for item in self.client.get('/api/v1/admin/candidates').json()['items'] if item['id'] == held_id)
        published = self.client.post(
            '/api/v1/admin/candidates/' + held_id + '/review',
            json={'action': 'publish', 'reason': 'Same session, updated title', 'version': held['version']},
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()['resulting_course_id'], course_id)
        listed = self.client.get('/api/v1/trainings?period=all&include_unknown=true').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['id'], course_id)
        self.assertEqual(listed['items'][0]['title'], 'Primary Care Update KL 2026')
        with self.Session() as db:
            course = db.get(Course, course_id)
            self.assertEqual(course.source_key, source_key(renamed))
            self.assertNotEqual(course.source_key, source_key(training))
        # Exact lookup on the drifted identity must still resolve the same session.
        lookup = self.client.post(
            '/internal/v1/catalogue/lookup',
            json={'candidate': renamed},
            headers=self.service,
        )
        self.assertEqual(lookup.status_code, 200, lookup.text)
        self.assertEqual(lookup.json()['exact']['id'], course_id)

    def test_exists_refresh_upserts_same_source_key(self):
        training = sample(title='Refresh Upsert Workshop', source_url='https://example.org/refresh-upsert')
        with patch.dict(os.environ, {'CATALOGUE_AUTO_PUBLISH_NEW': 'true'}):
            first = self.client.post(
                '/internal/v1/catalogue/save',
                json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 1, 'probabilities': {'new': 1}}},
                headers=self.service,
            )
        self.assertEqual(first.status_code, 200, first.text)
        course_id = first.json()['course_id']
        changed = sample(title='Refresh Upsert Workshop', source_url='https://example.org/refresh-upsert')
        changed['fee'] = 90
        changed['currency'] = 'MYR'
        changed['evidence'] = {**changed['evidence'], 'fee': QUOTE, 'currency': QUOTE}
        again = self.client.post(
            '/internal/v1/catalogue/save',
            json={
                'candidate': changed,
                'judgment': {'decision': 'exists', 'confidence': 1, 'matched_session_id': course_id, 'probabilities': {'exists': 1}},
            },
            headers=self.service,
        )
        self.assertEqual(again.status_code, 200, again.text)
        first_id = again.json()['candidate_id']
        changed['fee'] = 120
        twice = self.client.post(
            '/internal/v1/catalogue/save',
            json={
                'candidate': changed,
                'judgment': {'decision': 'exists', 'confidence': 1, 'matched_session_id': course_id, 'probabilities': {'exists': 1}},
            },
            headers=self.service,
        )
        self.assertEqual(twice.status_code, 200, twice.text)
        self.assertEqual(twice.json()['candidate_id'], first_id)
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        held = [item for item in self.client.get('/api/v1/admin/candidates').json()['items'] if item['id'] == first_id]
        self.assertEqual(len(held), 1)
        diff = {row['field']: row for row in held[0]['data'].get('_refresh_diff') or []}
        self.assertEqual(diff['fee']['proposed'], 120)

    def test_save_reopens_rejected_same_source_key(self):
        training = sample(title='Rejected Reopen Workshop', source_url='https://example.org/rejected-reopen')
        first = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 0.4, 'probabilities': {'new': 0.4}}},
            headers=self.service,
        )
        self.assertEqual(first.status_code, 200, first.text)
        candidate_id = first.json()['candidate_id']
        self.client.post('/api/v1/auth/login', json={'email': 'op@example.com', 'password': 'CareCredits-demo-2026'})
        rejected = self.client.post(
            '/api/v1/admin/candidates/' + candidate_id + '/review',
            json={'action': 'reject', 'version': 1, 'reason': 'Not GP relevant'},
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        again = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 0.5, 'probabilities': {'new': 0.5}}},
            headers=self.service,
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()['candidate_id'], candidate_id)
        self.assertEqual(again.json()['status'], 'pending')
        with self.Session() as db:
            rows = db.query(Candidate).filter(Candidate.source_key == source_key(training)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, 'pending')
            self.assertEqual(rows[0].review_reason, '')
            self.assertIsNone(rows[0].reviewed_by)
            self.assertIsNone(rows[0].reviewed_at)
            # Rejected→pending bumps version so CandidateCard remounts (id+version).
            self.assertGreater(rows[0].version, 1)

    def test_save_new_reopens_held_candidate_to_pending(self):
        """decision=new must not leave a prior held row stuck while the API claims pending."""
        training = sample(title='Held To Pending Workshop', source_url='https://example.org/held-to-pending')
        key = source_key(training)
        with self.Session() as db:
            job = Job(account_id=db.query(Account).first().id, request_key='held-to-pending', query='GP', status='succeeded')
            db.add(job)
            db.flush()
            candidate = Candidate(
                job_id=job.id,
                source_key=key,
                data={**training, '_judgment': {'decision': 'uncertain', 'confidence': 0.4}},
                status='held',
                review_reason='Jev uncertain: needs operator review',
                reviewed_by='operator',
                reviewed_at=1.0,
                version=2,
            )
            db.add(candidate)
            db.commit()
            candidate_id, prior_version = candidate.id, candidate.version
        again = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 0.9, 'probabilities': {'new': 0.9}}},
            headers=self.service,
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()['candidate_id'], candidate_id)
        self.assertEqual(again.json()['status'], 'pending')
        with self.Session() as db:
            rows = db.query(Candidate).filter(Candidate.source_key == key).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, 'pending')
            self.assertEqual(rows[0].review_reason, '')
            self.assertIsNone(rows[0].reviewed_by)
            self.assertIsNone(rows[0].reviewed_at)
            self.assertGreater(rows[0].version, prior_version)
            self.assertEqual((rows[0].data or {}).get('_judgment', {}).get('decision'), 'new')

    def test_save_new_pending_refresh_bumps_version(self):
        training = sample(title='Pending Refresh Workshop', source_url='https://example.org/pending-refresh')
        first = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': training, 'judgment': {'decision': 'new', 'confidence': 0.5, 'probabilities': {'new': 0.5}}},
            headers=self.service,
        )
        self.assertEqual(first.status_code, 200, first.text)
        candidate_id = first.json()['candidate_id']
        with self.Session() as db:
            prior_version = db.get(Candidate, candidate_id).version
        refreshed = {**training, 'description': 'Updated excerpt for remount'}
        again = self.client.post(
            '/internal/v1/catalogue/save',
            json={'candidate': refreshed, 'judgment': {'decision': 'new', 'confidence': 0.6, 'probabilities': {'new': 0.6}}},
            headers=self.service,
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()['candidate_id'], candidate_id)
        self.assertEqual(again.json()['status'], 'pending')
        with self.Session() as db:
            row = db.get(Candidate, candidate_id)
            self.assertEqual(row.status, 'pending')
            self.assertGreater(row.version, prior_version)
            self.assertEqual(row.data.get('description'), 'Updated excerpt for remount')

    def test_decide_reopens_rejected_candidate_with_version_bump(self):
        training = sample(title='Decide Rejected Workshop', source_url='https://example.org/decide-rejected')
        key = source_key(training)
        with self.Session() as db:
            job = Job(account_id=db.query(Account).first().id, request_key='decide-rejected', query='GP', status='succeeded')
            db.add(job)
            db.flush()
            candidate = Candidate(
                job_id=job.id,
                source_key=key,
                data=training,
                status='rejected',
                review_reason='Earlier reject',
                reviewed_by='operator',
                reviewed_at=1.0,
                version=4,
            )
            db.add(candidate)
            db.commit()
            candidate_id = candidate.id
            prior_version = candidate.version
        decide = self.client.post(
            '/internal/v1/catalogue/decide',
            json={'candidate': training, 'matches': []},
            headers=self.service,
        )
        self.assertEqual(decide.status_code, 200, decide.text)
        self.assertEqual(decide.json()['decision'], 'new')
        self.assertEqual(decide.json()['candidate_id'], candidate_id)
        with self.Session() as db:
            stored = db.get(Candidate, candidate_id)
            self.assertEqual(stored.status, 'pending')
            self.assertEqual(stored.review_reason, '')
            self.assertIsNone(stored.reviewed_by)
            self.assertIsNone(stored.reviewed_at)
            self.assertGreater(stored.version, prior_version)
            self.assertEqual((stored.data or {}).get('_judgment', {}).get('decision'), 'new')


if __name__ == '__main__':
    unittest.main()
