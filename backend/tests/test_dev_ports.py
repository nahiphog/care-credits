import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT))

from scripts.dev import (
    LOCAL_DEV_ALLOWED_ORIGINS,
    allowed_origins_for_frontend,
    free_port,
    is_live_body,
    probe_live,
    reserve_local_ports,
    service_environments,
    wait_for_live,
)
from shared.model_defaults import apply_provisional_model, using_provisional


class DevPortTests(unittest.TestCase):
    def test_free_port_skips_a_bound_preferred_port(self):
        occupied = socket.socket()
        occupied.bind(('127.0.0.1', 0))
        preferred = occupied.getsockname()[1]
        try:
            chosen = free_port(preferred)
            self.assertNotEqual(chosen, preferred)
            self.assertGreaterEqual(chosen, preferred)
        finally:
            occupied.close()

    def test_reserve_local_ports_keeps_backend_and_health_distinct(self):
        # Overlapping preferred ranges used to bind-and-close independently and could collide.
        ports, held = reserve_local_ports(18050, 18050, 18050)
        try:
            self.assertEqual(len(ports), 3)
            self.assertEqual(len(set(ports)), 3)
            for port in ports:
                self.assertGreaterEqual(port, 18050)
                self.assertLess(port, 18070)
        finally:
            for sock in held:
                sock.close()

    def test_service_environments_point_backend_at_scraper_health_without_model_secret(self):
        root = Path(tempfile.mkdtemp())
        settings = {
            'MODEL_API_KEY': 'secret-model-key',
            'MODEL_ID': 'Qwen/Qwen3-test',
            'MODEL_PUBLISHER': 'Qwen',
            'MODEL_WEIGHTS_URL': 'https://example.org/weights',
            'MODEL_LICENSE_URL': 'https://example.org/license',
            'TAVILY_API_KEY': 'secret-tavily',
            'FIREHOSE_MGMT_KEY': 'secret-firehose',
            'TYPESAFE_API_KEY': 'secret-typesafe',
            'CATALOGUE_AUTO_PUBLISH_NEW': 'false',
            'SCRAPE_TOPICS_FILE': '/tmp/topics.json',
        }
        backend, scraper, frontend = service_environments(
            root,
            settings,
            {'MODEL_API_KEY': 'leaked', 'TAVILY_API_KEY': 'leaked', 'HOME': '/tmp'},
            backend_port=8000,
            frontend_port=3000,
            health_port=8002,
            demo=True,
            token='shared-token',
            typesafe_keyfile=root / 'missing-typesafe-key',
        )
        self.assertEqual(backend['SCRAPER_HEALTH_URL'], 'http://127.0.0.1:8002')
        self.assertEqual(backend['MODEL_ID'], 'Qwen/Qwen3-test')
        self.assertEqual(backend['MODEL_PUBLISHER'], 'Qwen')
        self.assertEqual(backend['MODEL_KEY_CONFIGURED'], 'true')
        self.assertEqual(backend['SCRAPE_TOPICS_FILE'], '/tmp/topics.json')
        self.assertEqual(backend['DAILY_SCRAPE_ENABLED'], 'false')
        self.assertNotIn('MODEL_API_KEY', backend)
        self.assertNotIn('TAVILY_API_KEY', backend)
        self.assertNotIn('FIREHOSE_MGMT_KEY', backend)
        self.assertEqual(scraper['MODEL_API_KEY'], 'secret-model-key')
        self.assertEqual(scraper['TAVILY_API_KEY'], 'secret-tavily')
        self.assertEqual(scraper['SCRAPER_HEALTH_PORT'], '8002')
        self.assertEqual(scraper['BACKEND_INTERNAL_URL'], 'http://127.0.0.1:8000')
        self.assertNotIn('TYPESAFE_API_KEY', scraper)
        self.assertEqual(frontend['BACKEND_URL'], 'http://127.0.0.1:8000')
        self.assertEqual(frontend['NEXT_DIST_DIR'], '.data/next-dev-3000')
        self.assertEqual(frontend['WATCHPACK_POLLING'], 'true')
        self.assertEqual(frontend['CHOKIDAR_USEPOLLING'], 'true')
        self.assertNotIn('MODEL_API_KEY', frontend)
        self.assertIn('http://localhost:3000', backend['ALLOWED_ORIGINS'])
        self.assertIn('http://127.0.0.1:3030', backend['ALLOWED_ORIGINS'])
        self.assertIn('http://127.0.0.1:3040', backend['ALLOWED_ORIGINS'])
        filled = apply_provisional_model({'MODEL_ID': '', 'TAVILY_API_KEY': 'keep'})
        self.assertEqual(filled['MODEL_ID'], 'nvidia/nemotron-3-super-120b-a12b')
        self.assertEqual(filled['TAVILY_API_KEY'], 'keep')
        self.assertNotIn('MODEL_API_KEY', filled)
        self.assertTrue(using_provisional('MODEL_ID', {'MODEL_ID': ''}))
        self.assertFalse(using_provisional('MODEL_ID', {'MODEL_ID': 'Qwen/owner-chosen'}))
        # OPEN-03 samples filled for the scraper must not land on the backend process env.
        filled = apply_provisional_model({})
        backend_empty, scraper_filled, _fe = service_environments(
            root,
            filled,
            {'HOME': '/tmp'},
            backend_port=8010,
            frontend_port=3010,
            health_port=8012,
            demo=True,
            token='shared-token',
            typesafe_keyfile=root / 'missing-typesafe-key',
            owner_settings={},
        )
        self.assertNotIn('MODEL_ID', backend_empty)
        self.assertNotIn('MODEL_PUBLISHER', backend_empty)
        self.assertNotIn('MODEL_HOST', backend_empty)
        self.assertNotIn('MODEL_WEIGHTS_URL', backend_empty)
        self.assertNotIn('MODEL_LICENSE_URL', backend_empty)
        self.assertNotIn('MODEL_MAX_INPUT_CHARS', backend_empty)
        self.assertNotIn('MODEL_MAX_OUTPUT_TOKENS', backend_empty)
        self.assertEqual(scraper_filled['MODEL_ID'], 'nvidia/nemotron-3-super-120b-a12b')
        self.assertIn('http://localhost:3010', backend_empty['ALLOWED_ORIGINS'])
        self.assertIn('http://localhost:3030', backend_empty['ALLOWED_ORIGINS'])
        from http_boundary import DEFAULT_ALLOWED_ORIGINS

        self.assertEqual(LOCAL_DEV_ALLOWED_ORIGINS, DEFAULT_ALLOWED_ORIGINS)
        self.assertIn('http://127.0.0.1:3040', allowed_origins_for_frontend(3040))

    def test_wait_for_live_requires_status_live(self):
        self.assertTrue(is_live_body({'status': 'live'}))
        self.assertFalse(is_live_body({'status': 'ok'}))
        self.assertFalse(is_live_body({'status': 'ready'}))
        from scraper.health import start

        server = start(port=18032)
        try:
            ready, missing = wait_for_live(
                {
                    'scraper': 'http://127.0.0.1:18032/health/live',
                    'missing': 'http://127.0.0.1:9/health/live',
                },
                timeout=2,
                sleep=0.1,
            )
            self.assertTrue(probe_live('http://127.0.0.1:18032/health/live'))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(ready, ['scraper'])
        self.assertEqual(missing, ['missing'])
