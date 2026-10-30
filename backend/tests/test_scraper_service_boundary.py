"""Real HTTP contracts between independently deployable backend and scraper runtimes."""
import os
import time
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from scraper.service import app
from infrastructure import scraper_client
from domain.errors import DomainError


class ScraperBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'SCRAPER_SERVICE_TOKEN': 'test-worker-token',
                                         'SCRAPER_SERVICE_URL': 'http://scraper.test'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.body = {'id': 'job-test', 'query': 'Malaysia GP CPD', 'max_results': 1,
                     'lease_token': 'lease-test', 'expires_at': time.time() + 240}

    def test_unauthorized_call_never_runs_discovery(self):
        with patch('scraper.service.run_job') as run:
            response = self.client.post('/internal/v1/discovery/run', json=self.body)
        self.assertEqual(response.status_code, 401)
        run.assert_not_called()

    def test_boolean_source_count_never_runs_discovery(self):
        with patch('scraper.service.run_job') as run:
            response = self.client.post('/internal/v1/discovery/run', json={**self.body, 'max_results': True},
                                        headers={'Authorization': 'Bearer test-worker-token'})
        self.assertEqual(response.status_code, 422)
        run.assert_not_called()

    def test_unready_service_blocks_spend(self):
        from services.discovery_status_service import _paid_scrape_ready
        self.assertFalse(_paid_scrape_ready({'status': 'not_ready', 'model_ready': True, 'tavily_configured': True}))

    def test_valid_ticket_runs_without_backend_callback(self):
        def run(job, renew, *, review_only):
            self.assertTrue(review_only)
            renew()
            return {'lease_token': job['lease_token'], 'status': 'succeeded', 'candidates': [],
                    'sources': [], 'warnings': [], 'usage': {}}
        with patch('scraper.service.run_job', side_effect=run), patch('httpx.post') as callback:
            response = self.client.post('/internal/v1/discovery/run', json=self.body,
                                        headers={'Authorization': 'Bearer test-worker-token'})
        self.assertEqual(response.status_code, 200, response.text)
        callback.assert_not_called()

    def test_expired_ticket_stops_before_discovery(self):
        with patch('scraper.service.run_job') as run:
            response = self.client.post('/internal/v1/discovery/run', json={**self.body, 'expires_at': time.time() - 1},
                                        headers={'Authorization': 'Bearer test-worker-token'})
            self.assertEqual(response.status_code, 409)
        run.assert_not_called()

    def test_local_execution_deadline_cannot_extend_ticket(self):
        def run(job, check, *, review_only):
            with patch('scraper.service.time.monotonic', return_value=10**15):
                check()
            self.fail('Expired execution must stop before returning a result')
        with patch('scraper.service.run_job', side_effect=run):
            response = self.client.post('/internal/v1/discovery/run', json=self.body,
                                        headers={'Authorization': 'Bearer test-worker-token'})
        self.assertEqual(response.status_code, 409)

    def test_readiness_does_not_need_backend_url(self):
        with patch.dict(os.environ, {'BACKEND_URL': '', 'TAVILY_API_KEY': 'tvly-test-only'}), patch('scraper.service.configuration'):
            response = self.client.get('/health/ready')
        self.assertEqual(response.status_code, 200)

    def test_backend_dispatch_does_not_retry_provider_work(self):
        with patch('infrastructure.scraper_client.httpx.post', side_effect=httpx.ReadTimeout('timed out')) as send:
            with self.assertRaises(DomainError) as caught:
                scraper_client.execute(self.body)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(send.call_count, 1)
        self.assertNotIn('test-worker-token', caught.exception.detail)
