import os
import unittest
from unittest.mock import patch
from backend.tests import test_extraction
from scraper.extraction import resolved_configuration, ExtractionError, extract_training


class ExplicitModelTests(unittest.TestCase):
    setUp = test_extraction.ModelTests.setUp
    client = test_extraction.ModelTests.client
    def test_missing_or_blank_settings_fail_closed(self):
        for name in ('MODEL_ID', 'MODEL_BASE_URL', 'MODEL_API_KEY', 'MODEL_WEIGHTS_URL', 'MODEL_LICENSE_URL'):
            with self.subTest(name=name), patch.dict(os.environ, {name: ' '}):
                with self.assertRaises(ExtractionError):
                    resolved_configuration()

    def test_success_receipt_contains_no_credentials(self):
        usage = {}
        with self.client(self.row) as client:
            extract_training(self.source, client, usage)
        receipt = usage['extractions'][0]
        self.assertEqual(receipt['model_id'], 'test/open-weight-model')
        self.assertEqual(receipt['endpoint_host'], 'example.org')
        self.assertEqual(receipt['candidate_count'], 1)
        self.assertIn('completed_at', receipt)
        self.assertNotIn('test-secret', str(receipt))

    def test_failure_cannot_create_success_receipt(self):
        usage = {}
        with self.client(self.row, status=500) as client:
            with self.assertRaises(ExtractionError):
                extract_training(self.source, client, usage)
        self.assertNotIn('extractions', usage)
