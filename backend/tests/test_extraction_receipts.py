import unittest
from backend.tests import test_portal


class ReceiptTests(unittest.TestCase):
    login = test_portal.PortalTests.login
    setUp = test_portal.PortalTests.setUp
    tearDown = test_portal.PortalTests.tearDown

    def test_receipt_persists_and_requires_operator(self):
        service = {'Authorization': 'Bearer test-service-token'}
        queued = self.client.post('/api/v1/admin/ingestion-jobs', json={'query': 'GP courses Malaysia'}, headers={'Idempotency-Key': 'receipt-test'})
        self.assertEqual(queued.status_code, 202, queued.text)
        job = self.client.post('/internal/v1/jobs/claim', headers=service).json()
        receipt = {'model_id': 'nvidia/test', 'endpoint_host': 'example.org', 'completed_at': '2026-10-29T00:00:00Z', 'candidate_count': 1}
        response = self.client.post('/internal/v1/jobs/' + job['id'] + '/complete', headers=service, json={
            'lease_token': job['lease_token'], 'status': 'succeeded',
            'candidates': [test_portal.sample()], 'extractions': [receipt],
        })
        self.assertEqual(response.status_code, 200, response.text)
        detail = self.client.get('/api/v1/admin/ingestion-jobs/' + job['id'])
        self.assertEqual(detail.json()['result']['extractions'][0]['model_id'], 'nvidia/test')
        self.client.post('/api/v1/auth/logout')
        self.assertEqual(self.client.get('/api/v1/admin/ingestion-jobs/' + job['id']).status_code, 401)
