"""Catalogue persistence and retention operations; ORM mappings stay passive."""
import os
import time
from sqlalchemy import and_
from models.schema import Course, Record, Job, Candidate, SourceDocument, FieldEvidence

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

