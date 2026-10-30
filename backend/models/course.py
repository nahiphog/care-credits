"""Passive ORM mappings for course storage."""
from sqlalchemy import Column, String, Float, Boolean, JSON, ForeignKey, UniqueConstraint
from database import Base
from .common import uid
import time


class Course(Base):
    __tablename__ = 'courses'
    id = Column(String, primary_key=True, default=uid)
    source_key = Column(String, unique=True, nullable=False)
    data = Column(JSON, nullable=False)
    demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)
    updated_at = Column(Float, default=time.time, nullable=False)
    title = Column(String, default='', nullable=False)
    provider = Column(String, default='', nullable=False)
    description = Column(String, default='', nullable=False)
    start_date = Column(String, nullable=True, index=True)
    end_date = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    venue = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    state = Column(String, nullable=True, index=True)
    country = Column(String, default='MY', nullable=False)
    mode = Column(String, default='online', nullable=False, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    fee = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    points = Column(Float, nullable=True)
    credit_label = Column(String, nullable=True)
    difficulty = Column(String, nullable=True, index=True)
    verification_status = Column(String, default='unverified', nullable=False)
    publication_status = Column(String, default='published', nullable=False, index=True)
    cancellation_status = Column(String, default='active', nullable=False)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(Float, nullable=True)



class SourceDocument(Base):
    __tablename__ = 'source_documents'
    __table_args__ = (UniqueConstraint('canonical_url', 'content_hash'),)
    id = Column(String, primary_key=True, default=uid)
    job_id = Column(String, ForeignKey('ingestion_jobs.id'), nullable=True, index=True)
    canonical_url = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    retrieved_at = Column(Float, default=time.time, nullable=False)
    extraction_status = Column(String, default='unknown', nullable=False)
    title = Column(String, default='', nullable=False)
    snippet = Column(String, default='', nullable=False)



class FieldEvidence(Base):
    __tablename__ = 'field_evidence'
    id = Column(String, primary_key=True, default=uid)
    course_id = Column(String, ForeignKey('courses.id'), nullable=True, index=True)
    candidate_id = Column(String, ForeignKey('course_candidates.id'), nullable=True, index=True)
    source_document_id = Column(String, ForeignKey('source_documents.id'), nullable=True, index=True)
    field_name = Column(String, nullable=False)
    excerpt = Column(String, nullable=False)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(Float, nullable=True)

