"""T-09: secrets stay off the client; origins and unauthenticated user routes stay closed."""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend'


class SecretSurfaceTests(unittest.TestCase):
    def test_frontend_has_no_service_secrets(self):
        needles = (
            'TAVILY_API_KEY',
            'MODEL_API_KEY',
            'TYPESAFE_API_KEY',
            'SCRAPER_SERVICE_TOKEN',
            'POSTGRES_PASSWORD',
            'GOOGLE_CLIENT_SECRET',
        )
        hits = []
        for path in FRONTEND.rglob('*'):
            if not path.is_file() or any(part in path.parts for part in ('node_modules', '.next', 'dist', '.data')):
                continue
            if path.suffix.lower() not in {'.ts', '.tsx', '.js', '.jsx', '.json', '.env', '.md'}:
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            for needle in needles:
                if needle in text:
                    hits.append(f'{path.relative_to(ROOT)}:{needle}')
        self.assertEqual(hits, [])

    def test_default_origins_are_local_only(self):
        from main import DEFAULT_ALLOWED_ORIGINS
        default = DEFAULT_ALLOWED_ORIGINS
        self.assertNotIn('*', default)
        self.assertTrue(all(item.startswith('http://localhost') or item.startswith('http://127.0.0.1') for item in default.split(',')))
        self.assertIn('http://127.0.0.1:3020', default)
        self.assertIn('http://127.0.0.1:3021', default)
        self.assertIn('http://127.0.0.1:3030', default)
        self.assertIn('http://127.0.0.1:3040', default)
        main = (ROOT / 'backend' / 'services' / 'portal.py').read_text(encoding='utf-8')
        compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        sample = (ROOT / '.env.sample').read_text(encoding='utf-8')
        self.assertIn('http://127.0.0.1:3020', main)
        self.assertIn('http://127.0.0.1:3021', main)
        self.assertIn('http://127.0.0.1:3030', main)
        self.assertIn('http://127.0.0.1:3040', main)
        self.assertIn('http://127.0.0.1:3020', compose)
        self.assertIn('http://127.0.0.1:3021', compose)
        self.assertIn('http://127.0.0.1:3030', compose)
        self.assertIn('http://127.0.0.1:3040', compose)
        self.assertIn('http://127.0.0.1:3020', sample)
        self.assertIn('http://127.0.0.1:3021', sample)
        self.assertIn('http://127.0.0.1:3030', sample)
        self.assertIn('http://127.0.0.1:3040', sample)
        self.assertIn('DATABASE_URL=', sample)
        self.assertIn('BACKEND_INTERNAL_URL=', sample)
        self.assertIn('AGGREGATE_CREDIT_LABELS=', sample)
        self.assertNotIn('DATABASE_URL=postgresql', sample)
        self.assertNotIn('BACKEND_INTERNAL_URL=http', sample)

    def test_built_frontend_assets_omit_service_secret_names(self):
        trees = [FRONTEND / '.next', FRONTEND / '.data']
        existing = [tree for tree in trees if tree.exists()]
        if not existing:
            self.skipTest('No built frontend assets in this checkout')
        needles = ('TAVILY_API_KEY', 'MODEL_API_KEY', 'TYPESAFE_API_KEY', 'SCRAPER_SERVICE_TOKEN', 'POSTGRES_PASSWORD', 'GOOGLE_CLIENT_SECRET')
        hits = []
        for built in existing:
            for path in built.rglob('*'):
                if not path.is_file() or path.suffix.lower() not in {'.js', '.json', '.html', '.map'}:
                    continue
                text = path.read_text(encoding='utf-8', errors='ignore')
                for needle in needles:
                    if needle in text:
                        hits.append(f'{path.relative_to(ROOT)}:{needle}')
        self.assertEqual(hits, [])

    def test_runtime_logs_omit_service_secret_names(self):
        logs = ROOT / '.data'
        if not logs.exists():
            self.skipTest('No runtime log directory in this checkout')
        needles = ('TAVILY_API_KEY', 'MODEL_API_KEY', 'TYPESAFE_API_KEY', 'SCRAPER_SERVICE_TOKEN', 'POSTGRES_PASSWORD', 'GOOGLE_CLIENT_SECRET')
        hits = []
        for path in logs.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in {'.log', '.txt'}:
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            for needle in needles:
                if needle in text:
                    hits.append(f'{path.relative_to(ROOT)}:{needle}')
        self.assertEqual(hits, [])

    def test_source_tree_omits_live_secret_values(self):
        skip_parts = {'.git', '.venv', 'node_modules', '.next', '.data', 'dist', '__pycache__'}
        allow = {'tvly-test-only'}
        hits = []
        for path in ROOT.rglob('*'):
            if not path.is_file() or any(part in skip_parts for part in path.parts):
                continue
            if path.name.startswith('.env') or path.suffix.lower() in {'.db', '.pem', '.key'}:
                continue
            if path.suffix.lower() not in {'.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.md', '.yml', '.yaml', '.txt', '.sample', '.mjs'}:
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            for token in set(re.findall(r'tvly-[A-Za-z0-9_-]+', text)):
                if token not in allow:
                    hits.append(str(path.relative_to(ROOT)))
                    break
        self.assertEqual(hits, [])

    def test_compose_keeps_paid_secrets_on_scraper(self):
        text = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        backend, scraper = text.split('  scraper:', 1)
        self.assertIn('TYPESAFE_API_KEY', backend)
        self.assertIn('MODEL_ID', backend)
        self.assertIn('MODEL_KEY_CONFIGURED', backend)
        self.assertIn('SCRAPER_HEALTH_URL', backend)
        self.assertIn('CATALOGUE_AUTO_PUBLISH_NEW', backend)
        self.assertIn('AGGREGATE_CREDIT_LABELS', backend)
        self.assertIn('DAILY_SCRAPE_ENABLED', backend)
        self.assertIn('DAILY_SCRAPE_JOB_CEILING', backend)
        self.assertIn('SCRAPE_TOPICS_FILE', backend)
        self.assertIn('GOOGLE_CLIENT_ID', backend)
        self.assertIn('SMTP_HOST', backend)
        self.assertNotIn('MODEL_API_KEY: ${MODEL_API_KEY', backend)
        self.assertNotIn('TAVILY_API_KEY', backend)
        self.assertIn('TAVILY_API_KEY', scraper)
        self.assertIn('MODEL_API_KEY: ${MODEL_API_KEY:-}', scraper)
        self.assertIn('SCRAPER_SERVICE_TOKEN: ${SCRAPER_SERVICE_TOKEN:?', scraper)
        self.assertIn('FIREHOSE_MGMT_KEY', scraper)
        self.assertIn('SCRAPER_HEALTH_HOST', scraper)
        self.assertNotIn('TYPESAFE_API_KEY', scraper)
        self.assertNotIn('GOOGLE_CLIENT', scraper)
        self.assertNotIn('SMTP_', scraper)
        frontend = text.split('  frontend:', 1)[1]
        self.assertIn('/health/live', frontend)
        self.assertNotIn('TAVILY_API_KEY', frontend)
        dockerfile = (ROOT / 'backend' / 'Dockerfile').read_text(encoding='utf-8')
        self.assertIn('COPY config /app/config', dockerfile)
        self.assertIn('SCRAPE_TOPICS_FILE=/app/config/scrape_topics.json', dockerfile)
