"""Portal schema v17. Digest send backoff plus session schedule on flattened Course."""
import os
import time
import uuid
from sqlalchemy import Column, String, Float, Boolean, Integer, JSON, ForeignKey, UniqueConstraint, and_
from database import Base

SCHEMA_VERSION = 17
CANDIDATE_SCHEMA_VERSION = 1


def uid():
    return uuid.uuid4().hex


class Account(Base):
    __tablename__ = 'accounts'
    __table_args__ = (UniqueConstraint('identity_issuer', 'identity_subject'),)
    id = Column(String, primary_key=True, default=uid)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    city = Column(String, default='Kuala Lumpur', nullable=False)
    state = Column(String, default='', nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_consent_at = Column(Float, nullable=True)
    identity_issuer = Column(String, nullable=True)
    identity_subject = Column(String, nullable=True)
    role = Column(String, default='doctor', nullable=False)
    public_enabled = Column(Boolean, default=False, nullable=False)
    public_slug = Column(String, unique=True, default=uid, nullable=False)
    bio = Column(String, default='', nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash = Column(String, primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    expires_at = Column(Float, nullable=False)


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


FILTER_FIELDS = (
    'title', 'provider', 'description', 'start_date', 'end_date', 'timezone', 'venue',
    'city', 'state', 'country', 'mode', 'latitude', 'longitude', 'fee', 'currency',
    'points', 'credit_label', 'difficulty',
)


def fill_course(course, data, demo=None):
    payload = dict(data)
    start = payload.get('start_date')
    if hasattr(start, 'isoformat'):
        payload['start_date'] = start.isoformat()
    end = payload.get('end_date')
    if hasattr(end, 'isoformat'):
        payload['end_date'] = end.isoformat()
        end = payload['end_date']
    course.data = payload
    course.title = (payload.get('title') or '')[:200]
    course.provider = (payload.get('provider') or '')[:200]
    course.description = (payload.get('description') or '')[:3000]
    course.start_date = payload.get('start_date')
    course.end_date = end
    course.timezone = (payload.get('timezone') or None)
    if course.timezone:
        course.timezone = str(course.timezone)[:80]
    course.venue = (payload.get('venue') or None)
    if course.venue:
        course.venue = str(course.venue)[:200]
    course.city = payload.get('city')
    course.state = payload.get('state')
    course.country = payload.get('country') or 'MY'
    course.mode = payload.get('mode') or 'online'
    course.latitude = payload.get('latitude')
    course.longitude = payload.get('longitude')
    fee = payload.get('fee')
    points = payload.get('points')
    if fee is not None and fee < 0:
        raise ValueError('Fee cannot be negative.')
    if points is not None and points < 0:
        raise ValueError('Points cannot be negative.')
    if end and course.start_date and str(end) < str(course.start_date):
        raise ValueError('End date cannot be before start date.')
    course.fee = fee
    course.currency = payload.get('currency')
    course.points = points
    course.credit_label = payload.get('credit_label')
    course.difficulty = payload.get('difficulty')
    if not course.publication_status:
        course.publication_status = 'published'
    if not course.cancellation_status:
        course.cancellation_status = 'active'
    if demo is not None:
        course.demo = demo
    course.updated_at = time.time()
    return course


def listed_filter():
    # Honour both cancel columns so a drifted cancellation_status cannot leak into doctor
    # search, digests, suggestions, or Jev near-neighbour matches (exact cancelled still uses exact_course).
    return and_(
        Course.country == 'MY',
        Course.publication_status != 'cancelled',
        Course.cancellation_status != 'cancelled',
    )


class Record(Base):
    __tablename__ = 'doctor_records'
    __table_args__ = (UniqueConstraint('account_id', 'course_id'),)
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    course_id = Column(String, ForeignKey('courses.id'), nullable=False)
    signed_up = Column(Boolean, default=False, nullable=False)
    signup_status = Column(String, default='not_recorded', nullable=False)
    attended = Column(Boolean, default=False, nullable=False)
    attendance_status = Column(String, default='not_recorded', nullable=False)
    attended_on = Column(String, nullable=True)
    points = Column(Float, nullable=True)
    credit_label = Column(String, default='CPD', nullable=False)
    notes = Column(String, default='', nullable=False)
    public = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    signed_up_at = Column(Float, nullable=True)
    points_origin = Column(String, default='', nullable=False)


class RecordHistory(Base):
    __tablename__ = 'record_history'
    id = Column(String, primary_key=True, default=uid)
    record_id = Column(String, ForeignKey('doctor_records.id'), nullable=False, index=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    changed = Column(JSON, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)


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


class Audit(Base):
    __tablename__ = 'portal_audit'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    changed = Column(JSON, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)


class Throttle(Base):
    __tablename__ = 'request_throttle'
    key = Column(String, primary_key=True)
    count = Column(Integer, default=0, nullable=False)


class DigestPreference(Base):
    __tablename__ = 'digest_preferences'
    account_id = Column(String, ForeignKey('accounts.id'), primary_key=True)
    opted_in = Column(Boolean, default=False, nullable=False)
    cadence_days = Column(Integer, default=14, nullable=False)
    last_sent_at = Column(Float, nullable=True)
    unsubscribed_at = Column(Float, nullable=True)
    unsubscribe_token = Column(String, unique=True, default=uid, nullable=False)
    fail_count = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(Float, nullable=True)


class DigestSend(Base):
    __tablename__ = 'digest_sends'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    sent_at = Column(Float, default=time.time, nullable=False)
    status = Column(String, default='queued', nullable=False)
    event_count = Column(Integer, default=0, nullable=False)
    recorded_points_snapshot = Column(Float, default=0, nullable=False)
    provider_message_id = Column(String, nullable=True)
    error = Column(String, default='', nullable=False)
    payload = Column(JSON, nullable=True)


class AffiliationCertificate(Base):
    __tablename__ = 'affiliation_certificates'
    id = Column(String, primary_key=True, default=uid)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    recorded_points_snapshot = Column(Float, nullable=False)
    issued_at = Column(Float, default=time.time, nullable=False)
    document_hash = Column(String, nullable=False)
    disclaimer_version = Column(String, default='CERT-01-v1', nullable=False)


class SchemaVersion(Base):
    __tablename__ = 'portal_schema_version'
    version = Column(Integer, primary_key=True)


def aggregate_credit_labels():
    raw = os.getenv('AGGREGATE_CREDIT_LABELS', 'CPD')
    return {item.strip().upper() for item in raw.split(',') if item.strip()} or {'CPD'}


def counts_toward_cpd(record):
    return record.points is not None and (record.credit_label or '').strip().upper() in aggregate_credit_labels()


def retrieved_stamp(payload):
    """Parse scraper ISO retrieval time as UTC epoch seconds (never local wall-clock skew)."""
    retrieved = (payload or {}).get('retrieved_at')
    if not retrieved or retrieved == 'fixture':
        return None
    text = str(retrieved).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _blank_source_text(payload):
    data = dict(payload or {})
    raw = data.get('source_text')
    if raw is None:
        return None
    # Whitespace-only is already unusable for excerpts — normalize to '' so UI/API agree "missing".
    if not str(raw).strip():
        if raw == '':
            return None
        data['source_text'] = ''
        return data
    data['source_text'] = ''
    return data


def _blank_job_source_snippets(result):
    payload = dict(result or {})
    sources = payload.get('sources')
    if not isinstance(sources, list):
        return None
    next_sources = []
    changed = False
    for item in sources:
        # Truthy snippets (including whitespace-only) blank to '' on purge.
        if isinstance(item, dict) and item.get('snippet'):
            next_sources.append({**item, 'snippet': ''})
            changed = True
        else:
            next_sources.append(item)
    if not changed:
        return None
    payload['sources'] = next_sources
    return payload


def purge_expired_source_text(db, now=None, retain_days=30, batch_size=500):
    """Drop raw pages after 30 days; keep reviewed FieldEvidence excerpts.

    Skips every `running` job and still-fresh `queued` jobs (and their
    candidates/source docs) so a live scrape cannot lose snippets mid-lease.
    Aged never-claimed `queued` rows still purge. Processes tables in batches
    so a large catalogue cannot hold one unbounded load.
    """
    cutoff = (now or time.time()) - retain_days * 86400
    limit = max(1, int(batch_size or 500))

    def _in_flight_active(created_at, status):
        if status == 'running':
            return True
        # Fresh queued work may still be claimed; aged never-claimed rows must purge.
        return status == 'queued' and created_at is not None and created_at >= cutoff

    in_flight = {
        row.id
        for row in db.query(Job.id, Job.created_at, Job.status).filter(Job.status.in_(('queued', 'running')))
        if _in_flight_active(row.created_at, row.status)
    }
    kept = {
        row.source_document_id
        for row in db.query(FieldEvidence.source_document_id).filter(FieldEvidence.source_document_id.isnot(None))
    }
    # Fail closed: missing retrieved_at is treated as expired (same as candidate unparseable stamps).
    last_id = ''
    while True:
        documents = (
            db.query(SourceDocument)
            .filter(SourceDocument.id > last_id)
            .filter((SourceDocument.retrieved_at < cutoff) | (SourceDocument.retrieved_at.is_(None)))
            .order_by(SourceDocument.id)
            .limit(limit)
            .all()
        )
        if not documents:
            break
        for document in documents:
            last_id = document.id
            if document.job_id and document.job_id in in_flight:
                continue
            if document.snippet:
                document.snippet = ''
            if document.id not in kept:
                db.delete(document)
        db.flush()
    job_meta = {row.id: (row.created_at, row.status) for row in db.query(Job.id, Job.created_at, Job.status)}
    last_id = ''
    while True:
        candidates = (
            db.query(Candidate)
            .filter(Candidate.id > last_id)
            .order_by(Candidate.id)
            .limit(limit)
            .all()
        )
        if not candidates:
            break
        for candidate in candidates:
            last_id = candidate.id
            created_at, status = job_meta.get(candidate.job_id) or (None, None)
            if candidate.job_id in in_flight or _in_flight_active(created_at, status):
                continue
            stamp = retrieved_stamp(candidate.data)
            if stamp is None:
                stamp = created_at
            # Fail closed: unparseable retrieved_at with no job fallback is treated as expired.
            if stamp is not None and stamp >= cutoff:
                continue
            payload = _blank_source_text(candidate.data)
            if payload is not None:
                candidate.data = payload
        db.flush()
    last_id = ''
    while True:
        courses = (
            db.query(Course)
            .filter(Course.id > last_id)
            .order_by(Course.id)
            .limit(limit)
            .all()
        )
        if not courses:
            break
        for course in courses:
            last_id = course.id
            stamp = retrieved_stamp(course.data) or course.created_at
            if stamp is not None and stamp >= cutoff:
                continue
            payload = _blank_source_text(course.data)
            if payload is not None:
                course.data = payload
        db.flush()
    last_id = ''
    while True:
        jobs = (
            db.query(Job)
            .filter(Job.id > last_id)
            .filter((Job.created_at < cutoff) | (Job.created_at.is_(None)))
            .order_by(Job.id)
            .limit(limit)
            .all()
        )
        if not jobs:
            break
        for job in jobs:
            last_id = job.id
            if _in_flight_active(job.created_at, job.status):
                continue
            payload = _blank_job_source_snippets(job.result)
            if payload is not None:
                job.result = payload
        db.flush()
    db.commit()
