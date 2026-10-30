"""Audit regressions using isolated SQLite fixtures; no provider/network calls."""
import os
import unittest
from unittest.mock import patch
from backend.tests import test_portal as portal_fixture
from portal_models import Account, Audit, Candidate, Job, SchemaVersion, SCHEMA_VERSION
from shared.contracts import Training, validate_evidence


class AuditFixTests(unittest.TestCase):
    setUp = portal_fixture.PortalTests.setUp
    tearDown = portal_fixture.PortalTests.tearDown
    login = portal_fixture.PortalTests.login

    def test_unicode_certificate_is_immutable_and_history_is_private(self):
        with self.Session() as db:
            account = db.get(Account, self.a)
            account.name = '\u6797\u533b\u751f'
            db.commit()
        issued = self.client.post('/api/v1/me/certificates', json={'year': 2026})
        self.assertEqual(issued.status_code, 201, issued.text)
        cert = issued.json()
        self.assertTrue(cert['identity_snapshot_available'])
        self.assertFalse(cert['pdf_available'])
        original = self.client.get(cert['print_url']).text
        self.assertIn('\u6797\u533b\u751f', original)
        self.assertEqual(self.client.get(cert['pdf_download_url']).status_code, 422)
        with self.Session() as db:
            db.get(Account, self.a).name = 'Changed Name'
            db.commit()
        self.assertEqual(self.client.get(cert['print_url']).text, original)
        history = self.client.get('/api/v1/me/certificates?year=2026').json()
        self.assertEqual(history['total'], 1)
        self.assertEqual(history['items'][0]['id'], cert['id'])
        self.login('b@example.com')
        self.assertEqual(self.client.get(cert['print_url']).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/me/certificates').json()['total'], 0)

    def test_password_change_requires_current_password_and_revokes_sessions(self):
        path = '/api/v1/auth/password'
        new = 'A-new-password-for-testing'
        bad = self.client.post(path, json={'current_password': 'wrong', 'new_password': new})
        self.assertEqual(bad.status_code, 403, bad.text)
        good = self.client.post(path, json={'current_password': portal_fixture.PASSWORD, 'new_password': new})
        self.assertEqual(good.status_code, 200, good.text)
        self.assertEqual(self.client.get('/api/v1/me').status_code, 401)
        login = self.client.post('/api/v1/auth/login', json={'email': 'a@example.com', 'password': new})
        self.assertEqual(login.status_code, 200, login.text)

    def test_serverless_digest_is_unavailable_and_maintenance_requires_secret(self):
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true', 'CRON_SECRET': 'test-maintenance'}):
            self.assertFalse(self.client.get('/api/v1/config').json()['digest_available'])
            self.assertEqual(self.client.patch('/api/v1/me/digest', json={'opted_in': True}).status_code, 503)
            self.assertEqual(self.client.get('/internal/v1/maintenance').status_code, 401)
            allowed = self.client.get('/internal/v1/maintenance', headers={'Authorization': 'Bearer test-maintenance'})
            self.assertEqual(allowed.status_code, 200, allowed.text)

    def test_readiness_requires_current_schema(self):
        self.assertEqual(self.client.get('/health/ready').status_code, 503)
        with self.Session() as db:
            db.add(SchemaVersion(version=SCHEMA_VERSION)); db.commit()
        self.assertEqual(self.client.get('/health/ready').status_code, 200)

    def test_unrelated_quote_does_not_verify_claim(self):
        data = portal_fixture.sample()
        validate_evidence(Training(**data))
        for field, value in [('title', 'Invented course'), ('provider', 'Invented provider'), ('points', 9999)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_evidence(Training(**{**data, field: value}))

    def test_published_corrections_are_versioned_and_update_catalogue(self):
        data = portal_fixture.sample('Original training')
        data['source_text'] += ' Corrected training.'
        data['evidence']['title'] = data['source_text']
        with self.Session() as db:
            job = Job(id='audit-job', query='GP', status='succeeded', account_id=self.a, request_key='audit-test')
            db.add(job); db.flush()
            candidate = Candidate(job_id=job.id, source_key='audit-candidate', data=data, status='pending', version=1)
            db.add(candidate); db.commit(); cid = candidate.id
        path = '/api/v1/admin/candidates/' + cid + '/review'
        first = self.client.post(path, json={'action': 'publish', 'version': 1})
        self.assertEqual(first.status_code, 200, first.text)
        body = {'action': 'publish', 'version': 2, 'reason': 'Correct source title', 'corrections': {'title': 'Corrected training'}, 'evidence': {'title': data['source_text']}}
        corrected = self.client.post(path, json=body)
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()['version'], 3)
        self.assertEqual(self.client.post(path, json=body).status_code, 409)
        listed = self.client.get('/api/v1/admin/candidates?status=published').json()
        self.assertEqual(listed['items'][0]['data']['title'], 'Corrected training')
        results = self.client.get('/api/v1/trainings?period=all&q=Corrected').json()
        self.assertEqual(results['items'][0]['title'], 'Corrected training')

    def test_undated_online_suggestion_is_labelled_honestly(self):
        from portal_models import Course
        with self.Session() as db:
            course = db.get(Course, self.course)
            course.start_date = None
            course.mode = 'online'
            db.commit()
        result = self.client.get('/api/v1/me/suggestions')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['items'][0]['id'], self.course)
        self.assertIn('date not listed', result.json()['items'][0]['reason'])


class EvidenceFactTests(unittest.TestCase):
    def test_free_fee_is_not_proof_of_zero_points(self):
        data = portal_fixture.sample()
        data['source_text'] += ' Free to attend. MYR.'
        data['fee'] = 0
        data['currency'] = 'MYR'
        data['evidence']['currency'] = 'MYR'
        data['evidence']['fee'] = 'Free to attend.'
        validate_evidence(Training(**data))
        data['points'] = 0
        data['evidence']['points'] = 'Free to attend.'
        with self.assertRaises(ValueError):
            validate_evidence(Training(**data))

    def test_numeric_evidence_requires_full_value_and_accepts_sentence_punctuation(self):
        from shared.contracts import _quote_contains_number
        self.assertTrue(_quote_contains_number('Awarded 4.5 CPD points.', 4.5))
        self.assertTrue(_quote_contains_number('Awarded 2.', 2))
        self.assertFalse(_quote_contains_number('Awarded 40.', 4))
        self.assertFalse(_quote_contains_number('Awarded 4.5.', 4))
        self.assertFalse(_quote_contains_number('Correction -4.', 4))
        self.assertTrue(_quote_contains_number('Fee 1,200.50.', 1200.5))
