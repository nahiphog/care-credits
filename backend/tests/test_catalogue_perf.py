"""Catalogue p95 read target: 1,000 sessions, 10 concurrent readers (SDD §12)."""
import os
import platform
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from main import app
from database import Base, get_db
from portal_models import Account, Course, fill_course
from security import password_hash

PASSWORD = 'Testing-strong-password'


def sample(title, url):
    quote = title + ' by Learning Institute in Malaysia Kuala Lumpur online. 2099-01-15. CPD points 2.'
    return {
        'title': title,
        'provider': 'Learning Institute',
        'mode': 'online',
        'country': 'MY',
        'start_date': '2099-01-15',
        'city': 'Kuala Lumpur',
        'source_url': url,
        'source_text': quote,
        'points': 2,
        'credit_label': 'CPD',
        'evidence': {key: quote for key in ['title', 'provider', 'mode', 'country', 'start_date', 'city', 'points', 'credit_label']},
    }


class CataloguePerfTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.folder.name + '/perf.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        def dependency():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = dependency
        self.env = patch.dict(os.environ, {
            'APP_ENV': 'test',
            'DEMO_MODE': 'false',
            'SCRAPER_SERVICE_TOKEN': 'test-service-token',
            'ALLOW_SIGNUP': 'true',
            'DAILY_SCRAPE_ENABLED': 'false',
            'DIGEST_ENABLED': 'false',
        })
        self.env.start()
        self.client = TestClient(app, headers={'X-Care-Client': '1', 'Origin': 'http://127.0.0.1:3000'})
        with self.Session() as db:
            db.add(Account(email='perf@example.com', name='Perf Doctor', password_hash=password_hash(PASSWORD)))
            for index in range(1000):
                title = 'Perf session %04d' % index
                db.add(fill_course(Course(source_key='perf-%04d' % index), sample(title, 'https://example.org/perf/%04d' % index)))
            db.commit()
        login = self.client.post('/api/v1/auth/login', json={'email': 'perf@example.com', 'password': PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.env.stop()
        self.engine.dispose()
        self.folder.cleanup()

    def test_catalogue_read_p95_under_one_second(self):
        def read(_):
            started = time.perf_counter()
            response = self.client.get('/api/v1/trainings?period=upcoming&page=1&page_size=20')
            elapsed = time.perf_counter() - started
            return response.status_code, response.json().get('total'), elapsed

        samples = []
        with ThreadPoolExecutor(10) as pool:
            for code, total, elapsed in [future.result() for future in as_completed([pool.submit(read, i) for i in range(10)])]:
                self.assertEqual(code, 200)
                self.assertEqual(total, 1000)
                samples.append(elapsed)
        samples.sort()
        p95 = samples[max(0, int(0.95 * len(samples)) - 1)]
        print(
            'catalogue p95=%.3fs max=%.3fs n=%d env=%s %s'
            % (p95, samples[-1], len(samples), platform.system(), platform.machine()),
            flush=True,
        )
        self.assertLess(p95, 1.0, 'p95 catalogue read was %.3fs on %s %s' % (p95, platform.system(), platform.machine()))
