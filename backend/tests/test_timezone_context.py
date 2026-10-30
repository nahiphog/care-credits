"""Timezone selection is explicit and cannot leak between requests."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from domain import config
from domain.errors import DomainError
from http_boundary import request_boundary


class FixedClock:
    @classmethod
    def now(cls, zone):
        return datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc).astimezone(zone)


class TimezoneContextTests(unittest.TestCase):
    def test_default_context_and_explicit_timezone_precedence(self):
        with patch.dict(os.environ, {'DEFAULT_TIMEZONE': 'UTC'}), patch.object(config, 'datetime', FixedClock):
            self.assertEqual(str(config.today()), '2026-12-31')
            token = config.request_timezone.set('Asia/Kuala_Lumpur')
            try:
                self.assertEqual(str(config.today()), '2027-01-01')
                self.assertEqual(str(config.today('America/Los_Angeles')), '2026-12-31')
            finally:
                config.request_timezone.reset(token)
            self.assertEqual(str(config.today()), '2026-12-31')

    def test_invalid_explicit_timezone_is_rejected(self):
        with self.assertRaises(DomainError) as raised:
            config.today('Not/A_Real_Zone')
        self.assertEqual(raised.exception.status_code, 422)

    def test_http_header_is_validated_and_does_not_leak(self):
        app = FastAPI()
        app.middleware('http')(request_boundary)

        @app.get('/today')
        def today():
            return {'day': str(config.today()), 'zone': config.timezone_name()}

        with patch.dict(os.environ, {'DEFAULT_TIMEZONE': 'UTC'}), patch.object(config, 'datetime', FixedClock), TestClient(app) as client:
            selected = client.get('/today', headers={'X-Care-Timezone': 'Asia/Kuala_Lumpur'})
            self.assertEqual(selected.json(), {'day': '2027-01-01', 'zone': 'Asia/Kuala_Lumpur'})
            invalid = client.get('/today', headers={'X-Care-Timezone': 'Not/A_Real_Zone'})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(client.get('/today').json(), {'day': '2026-12-31', 'zone': 'UTC'})


if __name__ == '__main__':
    unittest.main()
