import os
import unittest
from unittest.mock import patch
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
        def fake_run(job, heartbeat):
            heartbeat()
            return {'lease_token': job['lease_token'], 'status': 'succeeded',
                    'candidates': [], 'sources': [], 'warnings': [], 'usage': {}}
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('scraper.worker.run_job', side_effect=fake_run) as run:
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
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('scraper.worker.run_job') as run:
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

    def test_missing_credentials_block_before_job_creation(self):
        with patch.dict(os.environ, {'SERVERLESS_MODE': 'true'}), patch('main._scraper_service_status', return_value={}):
            self.assertEqual(self.create().status_code, 409)
