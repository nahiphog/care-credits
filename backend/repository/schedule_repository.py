"""Persistence and concurrency boundaries for scheduled discovery jobs."""
from sqlalchemy.exc import IntegrityError
from models.account import Account
from models.ingestion import Job


class ScheduleRepository:
    def __init__(self, session):
        self.session = session

    def operator(self, lock=False):
        query = self.session.query(Account).filter_by(role='operator').order_by(Account.email)
        return (query.with_for_update(of=Account) if lock else query).first()

    def count_daily(self, day):
        return self.session.query(Job).filter(Job.request_key.like(f'daily:{day}:%')).count()

    def find_job(self, request_key):
        return self.session.query(Job).filter_by(request_key=request_key).first()

    def requeue(self, job, query, max_results, now):
        job.status = 'queued'
        job.query = query
        job.max_results = max_results
        job.lease_token = None
        job.lease_until = None
        job.started_at = None
        job.result = None
        job.created_at = now
        job.attempt = int(job.attempt or 1) + 1

    def insert_job(self, account_id, request_key, query, max_results, now):
        try:
            with self.session.begin_nested():
                self.session.add(Job(account_id=account_id, request_key=request_key,
                                     query=query, max_results=max_results,
                                     status='queued', created_at=now))
            return True
        except IntegrityError:
            return False

    def commit(self):
        self.session.commit()
