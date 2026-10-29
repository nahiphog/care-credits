"""Keep unittest DATABASE_URL off a running DEMO_MODE sqlite file."""
import os
import tempfile
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(tempfile.mkdtemp()) / 'unittest.db')
os.environ.setdefault('APP_ENV', 'test')
os.environ.setdefault('DEMO_MODE', 'false')
os.environ.setdefault('DAILY_SCRAPE_ENABLED', 'false')
