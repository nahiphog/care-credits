"""Scheduled discovery orchestrates policy over an isolated persistence boundary."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Base
from models.account import Account
from models.ingestion import Job
from services import schedule_service as schedule


class ScheduleLayerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.db.add(Account(email='operator@example.org', name='Operator', password_hash='unused', role='operator'))
        self.db.commit()
        self.topics = patch.object(schedule, 'load_topics', return_value=[{'query': 'GP CPD topic one', 'max_results': 2}, {'query': 'GP CPD topic two', 'max_results': 1}])
        self.ceiling = patch.object(schedule, 'daily_ceiling', return_value=1)
        self.day = patch.object(schedule, 'local_today', return_value='2026-10-30')
        self.topics.start(); self.ceiling.start(); self.day.start()

    def tearDown(self):
        self.topics.stop(); self.ceiling.stop(); self.day.stop()
        self.db.close(); self.engine.dispose()

    def test_ceiling_and_duplicate_requests_do_not_replay_spend(self):
        first = schedule.enqueue_daily(self.db)
        self.assertEqual((first['enqueued'], first['skipped']), (1, 1))
        second = schedule.enqueue_daily(self.db)
        self.assertEqual((second['enqueued'], second['skipped']), (0, 2))
        self.assertEqual(self.db.query(Job).count(), 1)
        self.assertEqual(schedule.daily_jobs_used(self.db, '2026-10-30'), 1)

    def test_force_retries_failed_jobs_only_and_increments_attempt(self):
        schedule.enqueue_daily(self.db)
        job = self.db.query(Job).one()
        job.status = 'failed'; job.result = {'warnings': ['old']}; self.db.commit()
        with patch('services.ingestion_job_service.expire_jobs') as expire:
            result = schedule.enqueue_daily(self.db, force=True)
            expire.assert_called_once_with(self.db)
        self.assertEqual(result['enqueued'], 1)
        self.assertEqual(job.attempt, 2)
        self.assertIsNone(job.result)
        job.status = 'succeeded'; self.db.commit()
        with patch('services.ingestion_job_service.expire_jobs'):
            self.assertEqual(schedule.enqueue_daily(self.db, force=True)['enqueued'], 0)
