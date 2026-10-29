import io
import logging
import unittest
from observe import failure_line, job_line, request_line, setup


class ObserveTests(unittest.TestCase):
    def setUp(self):
        setup()
        self.buffer = io.StringIO()
        self.handler = logging.StreamHandler(self.buffer)
        log = logging.getLogger('carecredits')
        log.addHandler(self.handler)
        self.addCleanup(log.removeHandler, self.handler)

    def test_request_and_job_lines_omit_secrets(self):
        request_line('abc123', 'GET', '/api/v1/trainings', 200, 12)
        job_line('job-1', 'partial', 2, 3, {'tavily_credits': 1, 'model_tokens': 30}, 1)
        failure_line('abc123', 429, 'Tavily rate or credit limit reached. Try again later.')
        text = self.buffer.getvalue()
        self.assertIn('request id=abc123', text)
        self.assertIn('job id=job-1 status=partial candidates=2 sources=3 tavily_credits=1.0 model_tokens=30', text)
        self.assertIn('failure id=abc123 status=429', text)
        self.assertNotIn('sk-', text)
        self.assertNotIn('Bearer', text)
        self.assertNotIn('TAVILY_API_KEY', text)

    def test_job_line_normalizes_bool_usage_to_null(self):
        job_line('job-2', 'failed', 0, 0, {'tavily_credits': True, 'model_tokens': False}, 0)
        text = self.buffer.getvalue()
        self.assertIn('job id=job-2 status=failed candidates=0 sources=0 tavily_credits=None model_tokens=None', text)

    def test_job_line_normalizes_inf_model_tokens_to_null(self):
        # as_int path must catch OverflowError from int(inf), not crash the log line.
        job_line('job-3', 'partial', 1, 1, {'tavily_credits': 1, 'model_tokens': float('inf')}, 0)
        text = self.buffer.getvalue()
        self.assertIn('job id=job-3 status=partial candidates=1 sources=1 tavily_credits=1.0 model_tokens=None', text)
