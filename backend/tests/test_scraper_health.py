import os
import unittest
from unittest.mock import patch
from scraper.health import ready, start


class ScraperHealthTests(unittest.TestCase):
    def test_ready_fails_closed_without_required_config(self):
        with patch.dict(os.environ, {'SCRAPER_SERVICE_TOKEN': '', 'BACKEND_INTERNAL_URL': '', 'TAVILY_API_KEY': ''}, clear=False):
            payload = ready()
            self.assertEqual(payload['status'], 'not_ready')
            self.assertIn('SCRAPER_SERVICE_TOKEN', payload['missing'])
            self.assertEqual(payload['backend_internal_url'], 'http://127.0.0.1:8000')

    def test_ready_defaults_backend_url_like_worker(self):
        with patch.dict(os.environ, {'SCRAPER_SERVICE_TOKEN': 'token', 'BACKEND_INTERNAL_URL': '', 'TAVILY_API_KEY': '', 'MODEL_API_KEY': '', 'MODEL_ID': ''}, clear=False):
            payload = ready()
            self.assertEqual(payload['status'], 'ready')
            self.assertEqual(payload['backend_internal_url'], 'http://127.0.0.1:8000')

    def test_ready_does_not_call_paid_providers(self):
        with patch.dict(os.environ, {'SCRAPER_SERVICE_TOKEN': 'token', 'BACKEND_INTERNAL_URL': 'http://127.0.0.1:8000', 'TAVILY_API_KEY': 'set', 'MODEL_API_KEY': '', 'MODEL_ID': ''}, clear=False):
            payload = ready()
            self.assertEqual(payload['status'], 'ready')
            self.assertTrue(payload['tavily_configured'])
            self.assertFalse(payload['model_ready'])

    def test_model_ready_requires_confirmation(self):
        env = {
            'SCRAPER_SERVICE_TOKEN': 'token',
            'BACKEND_INTERNAL_URL': 'http://127.0.0.1:8000',
            'MODEL_API_KEY': 'set',
            'MODEL_ID': '',
            'MODEL_WEIGHTS_URL': '',
            'MODEL_LICENSE_URL': '',
            'MODEL_OPEN_WEIGHT_CONFIRMED': 'false',
            'MODEL_MAX_INPUT_CHARS': '',
            'MODEL_MAX_OUTPUT_TOKENS': '',
        }
        with patch.dict(os.environ, env, clear=False):
            payload = ready()
            self.assertEqual(payload['status'], 'ready')
            self.assertTrue(payload['model_configured'])
            self.assertFalse(payload['model_ready'])
            self.assertIn('MODEL_OPEN_WEIGHT_CONFIRMED', payload['missing_model'])
            self.assertNotIn('MODEL_MAX_INPUT_CHARS', payload['missing_model'])
        env['MODEL_OPEN_WEIGHT_CONFIRMED'] = 'true'
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(ready()['model_ready'])

    def test_health_server_defaults_to_localhost(self):
        with patch.dict(os.environ, {'SCRAPER_HEALTH_HOST': '', 'SCRAPER_HEALTH_PORT': '18002'}, clear=False):
            server = start()
        try:
            self.assertEqual(server.server_address[0], '127.0.0.1')
        finally:
            server.shutdown()
            server.server_close()

    def test_unmatched_path_uses_error_envelope(self):
        import json
        from urllib.error import HTTPError
        from urllib.request import urlopen

        server = start(port=18042)
        try:
            ping = json.loads(urlopen('http://127.0.0.1:18042/health', timeout=2).read())
            live = json.loads(urlopen('http://127.0.0.1:18042/health/live', timeout=2).read())
            self.assertEqual(ping['status'], 'ok')
            self.assertEqual(live['status'], 'live')
            with self.assertRaises(HTTPError) as caught:
                urlopen('http://127.0.0.1:18042/does-not-exist', timeout=2)
            self.assertEqual(caught.exception.code, 404)
            body = json.loads(caught.exception.read())
            self.assertEqual(body['error']['code'], 'not_found')
            self.assertTrue(body['error']['message'])
            self.assertTrue(body['error']['request_id'])
            self.assertNotIn('status', body)
        finally:
            server.shutdown()
            server.server_close()
