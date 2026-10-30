import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from schemas.discovery import CompleteJob
from backend.tests.test_portal import PortalTests


class ServerlessTests(unittest.TestCase):
    setUp = PortalTests.setUp
    tearDown = PortalTests.tearDown
    login = PortalTests.login

    def create(self, maximum=1):
        return self.client.post('/api/v1/admin/ingestion-jobs',
            headers={'Idempotency-Key': 'serverless-test-key'},
            json={'query': 'Malaysia GP CPD', 'max_results': maximum})

    def test_requires_operator_and_single_source(self):
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}):
            self.assertEqual(self.create(2).status_code, 422)
            self.login('b@example.com')
            self.assertEqual(self.create().status_code, 403)
            self.assertEqual(self.client.post('/api/v1/admin/ingestion-jobs/x/run').status_code, 403)

    def test_completed_job_is_not_executed_twice(self):
        def fake_run(job):
            from backend.tests.test_portal import Job
            from shared.discovery_limits import SCRAPER_REQUEST_TIMEOUT_SECONDS
            with self.Session() as db:
                stored = db.get(Job, job['id'])
                self.assertEqual(stored.lease_until, job['expires_at'])
                self.assertEqual(stored.lease_until - stored.started_at, 240)
                self.assertGreater(stored.lease_until - stored.started_at, SCRAPER_REQUEST_TIMEOUT_SECONDS)
            return SimpleNamespace(**CompleteJob(lease_token=job['lease_token'], status='succeeded', candidates=[], sources=[], warnings=[], usage={}).model_dump(mode='json'))
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('services.ingestion_job_service.execute_scraper', side_effect=fake_run) as run:
            created = self.create()
            self.assertEqual(created.status_code, 202, created.text)
            job = created.json()
            self.assertEqual(job['execution_mode'], 'request')
            url = '/api/v1/admin/ingestion-jobs/' + job['id'] + '/run'
            first = self.client.post(url)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()['status'], 'succeeded')
            self.assertEqual(self.client.post(url).status_code, 200)
            self.assertEqual(run.call_count, 1)

    def test_running_job_cannot_be_claimed_again(self):
        from backend.tests.test_portal import Job
        import time
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('services.ingestion_job_service.execute_scraper') as run:
            job_id = self.create().json()['id']
            with self.Session() as db:
                job = db.get(Job, job_id)
                job.status = 'running'
                job.lease_token = 'active'
                job.lease_until = time.time() + 120
                job.started_at = time.time()
                db.commit()
            self.assertEqual(self.client.post('/api/v1/admin/ingestion-jobs/' + job_id + '/run').status_code, 409)
            run.assert_not_called()

    def test_review_only_run_persists_candidate_without_publishing(self):
        from backend.tests.test_portal import Candidate, Course, sample
        training = sample('Review-only course')
        source = {'url': training['source_url'], 'raw_content': training['source_text']}
        def remote_execute(job):
            from scraper.worker import run_job
            return SimpleNamespace(**CompleteJob(**run_job(job, lambda: None, review_only=True)).model_dump(mode='json'))
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('services.ingestion_job_service.execute_scraper', side_effect=remote_execute), patch(
            'scraper.worker.configuration'
        ), patch('scraper.worker.firehose_configured', return_value=False), patch(
            'scraper.worker.discover', return_value={'sources': [source], 'warnings': []}
        ), patch('scraper.worker.extract_training', return_value=[training]):
            job_id = self.create().json()['id']
            response = self.client.post('/api/v1/admin/ingestion-jobs/' + job_id + '/run')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'succeeded')
        self.assertEqual(response.json()['result']['warnings'], [])
        with self.Session() as db:
            candidate = db.query(Candidate).filter_by(job_id=job_id).one()
            self.assertEqual(candidate.status, 'pending')
            self.assertEqual(db.query(Course).filter_by(title='Review-only course').count(), 0)

    def test_missing_credentials_block_before_job_creation(self):
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('services.discovery_status_service._scraper_service_status', return_value={}):
            self.assertEqual(self.create().status_code, 409)
