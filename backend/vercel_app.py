"""Vercel entrypoint: shared Python API with request-bounded discovery."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['SERVERLESS_MODE'] = 'true'
os.environ['APP_ENV'] = 'production'
os.environ['DEMO_MODE'] = 'false'
os.environ['DAILY_SCRAPE_ENABLED'] = 'false'
os.environ['DIGEST_ENABLED'] = 'false'
os.environ['SCRAPE_TOPICS_FILE'] = str(ROOT / 'config' / 'scrape_topics.json')
hosts = [os.getenv('VERCEL_PROJECT_PRODUCTION_URL'), os.getenv('VERCEL_URL')]
origins = ['https://' + host for host in hosts if host]
if origins:
    os.environ.setdefault('ALLOWED_ORIGINS', ','.join(origins))
    os.environ.setdefault('PUBLIC_FRONTEND_BASE', origins[0])
    os.environ.setdefault('PUBLIC_API_BASE', origins[0])
if not os.getenv('DATABASE_URL'):
    raise RuntimeError('Configure Neon DATABASE_URL before serving requests.')

from main import app  # noqa: E402,F401
