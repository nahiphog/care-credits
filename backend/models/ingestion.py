"""Passive ORM mappings for ingestion storage."""
from sqlalchemy import Column, String, Float, Integer, JSON, ForeignKey, UniqueConstraint
from database import Base
from .common import uid, CANDIDATE_SCHEMA_VERSION
import time


class Job(Base):
    __tablename__ = 'ingestion_jobs'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False)
    request_key = Column(String, unique=True, nullable=False)
    query = Column(String, nullable=False)
    status = Column(String, default='queued', nullable=False, index=True)
    created_at = Column(Float, default=time.time, nullable=False)
    lease_token = Column(String, nullable=True)
    lease_until = Column(Float, nullable=True)
    started_at = Column(Float, nullable=True)
    result = Column(JSON, nullable=True)
    max_results = Column(Integer, default=5, nullable=False)
    attempt = Column(Integer, default=1, nullable=False)



class Candidate(Base):
    __tablename__ = 'course_candidates'
    __table_args__ = (UniqueConstraint('job_id', 'source_key'),)
    id = Column(String, primary_key=True, default=uid)
    job_id = Column(String, ForeignKey('ingestion_jobs.id'), nullable=False)
    source_key = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    status = Column(String, default='pending', nullable=False)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(Float, nullable=True)
    review_reason = Column(String, default='', nullable=False)
    version = Column(Integer, default=1, nullable=False)
    schema_version = Column(Integer, default=CANDIDATE_SCHEMA_VERSION, nullable=False)
    resulting_course_id = Column(String, ForeignKey('courses.id'), nullable=True)

