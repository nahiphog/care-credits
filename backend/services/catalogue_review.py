from __future__ import annotations
import os
from models.schema import Candidate, Course, Job, uid, CANDIDATE_SCHEMA_VERSION
from repository.model_helpers import fill_course, FILTER_FIELDS
from domain.passwords import digest
from domain.training_validation import validate_training
from shared.contracts import public_web_url
from repository import catalogue_repository as repository
REFRESH_FIELDS = FILTER_FIELDS + ('prerequisites', 'registration_url')

def open_review_candidate(db, key):
    """Prefer pending/held over rejected. UUID ids are not insertion-ordered."""
    open_row = repository.open_candidate(db, key)
    if open_row:
        return open_row
    return repository.rejected_candidate(db, key)

def auto_publish_new():
    return (os.getenv('CATALOGUE_AUTO_PUBLISH_NEW') or '').strip().lower() == 'true'

def training_payload(data):
    return {key: value for key, value in (data or {}).items() if not str(key).startswith('_')}

def resolve_review_course(db, candidate):
    data = candidate.data or {}
    matched_id = candidate.resulting_course_id or data.get('_matched_course_id')
    if matched_id:
        course = repository.get_course(db, matched_id)
        if course:
            return course
    return exact_course(db, candidate.source_key)

def course_compare_value(course, field):
    if field in ('prerequisites', 'registration_url'):
        return (course.data or {}).get(field)
    return getattr(course, field, None)

def refresh_diff(course, data):
    changes = []
    for field in REFRESH_FIELDS:
        published = course_compare_value(course, field)
        proposed = data.get(field)
        if published != proposed:
            changes.append({'field': field, 'published': published, 'proposed': proposed})
    return changes

def reopen_review_candidate(candidate, *, status: str, reason: str=''):
    """Reopen or refresh a review row and bump version so CandidateCard remounts (id+version)."""
    if candidate.status == 'rejected' or (candidate.status == 'held' and status != 'held'):
        candidate.reviewed_by = None
        candidate.reviewed_at = None
    candidate.status = status
    candidate.review_reason = reason
    candidate.version = int(candidate.version or 1) + 1

def source_key(data):
    return digest(data['source_url'].split('#')[0] + '|' + data['title'].strip().lower() + '|' + str(data.get('start_date')))

def course_public(course):
    data = dict(course.data or {})
    source = public_web_url(data.get('source_url'))
    return {'id': course.id, 'title': course.title, 'provider': course.provider, 'start_date': course.start_date, 'city': course.city, 'mode': course.mode, 'source_url': source, 'source_key': course.source_key, 'data': {'source_url': source}}

def exact_course(db, key):
    return repository.course_by_source_key(db, key)

def near_neighbours(db, candidate, limit=5):
    title = (candidate.get('title') or '').strip()
    provider = (candidate.get('provider') or '').strip()
    city = (candidate.get('city') or '').strip()
    start = str(candidate.get('start_date') or '')
    rows = repository.near_neighbours(db, provider, title, city, start, limit)
    scored = []
    for row in rows:
        score = 0
        if provider and provider.lower() in (row.provider or '').lower():
            score += 3
        if title and title.lower()[:20] in (row.title or '').lower():
            score += 3
        if city and city.lower() == (row.city or '').lower():
            score += 1
        if start and start == (row.start_date or ''):
            score += 2
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -(item[1].updated_at or 0)))
    return [row for score, row in scored if score >= 5][:limit]

def ensure_job(db, account_id, query='catalogue-save'):
    job = Job(account_id=account_id, request_key='save-' + uid(), query=query)
    repository.add_job(db, job)
    repository.flush(db)
    return job

def save_new_candidate(db, account_id, training, judgment, job_id=None):
    data = validate_training(training)
    key = source_key(data)
    if exact_course(db, key):
        raise ValueError('Event already exists in the catalogue.')
    status = 'pending'
    reason = ''
    if judgment.get('decision') == 'uncertain':
        status = 'held'
        reason = ('Jev uncertain: ' + str(judgment.get('warning') or 'needs operator review'))[:500]
    existing = open_review_candidate(db, key)
    if existing:
        existing.data = {**data, '_judgment': judgment}
        existing.schema_version = CANDIDATE_SCHEMA_VERSION
        reopen_review_candidate(existing, status=status, reason=reason)
        return existing
    if not job_id:
        job_id = ensure_job(db, account_id).id
    candidate = Candidate(job_id=job_id, source_key=key, data={**data, '_judgment': judgment}, status=status, schema_version=CANDIDATE_SCHEMA_VERSION, review_reason=reason)
    repository.add_candidate(candidate, db)
    repository.flush(db)
    return candidate

def _attach_field_evidence(db, course, candidate, data):
    """Persist source excerpts for auto-published rows (no operator reviewer stamp)."""
    repository.delete_course_evidence(course, db)
    for field, excerpt in (data.get('evidence') or {}).items():
        text = str(excerpt or '').strip()
        if not text:
            continue
        repository.add_unreviewed_evidence(candidate, course, db, field, text)

def publish_new_event(db, account_id, training, judgment, job_id=None):
    """Persist a Jev `new` decision into the searchable owned catalogue."""
    data = validate_training(training)
    key = source_key(data)
    if exact_course(db, key):
        raise ValueError('Event already exists in the catalogue.')
    payload = {**data, '_judgment': judgment}
    reason = 'Published via Jev decision=new'
    existing = open_review_candidate(db, key)
    if not job_id:
        job_id = (existing.job_id if existing else None) or ensure_job(db, account_id).id
    course = fill_course(Course(source_key=key), data, demo=False)
    repository.add_course(course, db)
    repository.flush(db)
    if existing:
        if existing.status in ('rejected', 'held'):
            existing.reviewed_by = None
            existing.reviewed_at = None
        existing.data = payload
        existing.status = 'published'
        existing.schema_version = CANDIDATE_SCHEMA_VERSION
        existing.resulting_course_id = course.id
        existing.review_reason = reason
        existing.job_id = job_id
        candidate = existing
        existing.version = int(existing.version or 1) + 1
    else:
        candidate = Candidate(job_id=job_id, source_key=key, data=payload, status='published', schema_version=CANDIDATE_SCHEMA_VERSION, resulting_course_id=course.id, review_reason=reason)
        repository.add_candidate(candidate, db)
        repository.flush(db)
    _attach_field_evidence(db, course, candidate, data)
    repository.flush(db)
    return (candidate, course)

def link_existing(db, account_id, training, course, judgment, job_id=None):
    data = validate_training(training)
    key = source_key(data)
    payload = {**data, '_judgment': judgment, '_matched_course_id': course.id, '_refresh_diff': refresh_diff(course, data)}
    reason = 'Jev marked exists; review refresh before overwriting published fields.'
    existing = open_review_candidate(db, key)
    if existing:
        existing.data = payload
        existing.resulting_course_id = course.id
        existing.schema_version = CANDIDATE_SCHEMA_VERSION
        reopen_review_candidate(existing, status='held', reason=reason)
        repository.flush(db)
        return existing
    if not job_id:
        job_id = ensure_job(db, account_id, 'catalogue-refresh').id
    candidate = Candidate(job_id=job_id, source_key=key, data=payload, status='held', schema_version=CANDIDATE_SCHEMA_VERSION, resulting_course_id=course.id, review_reason=reason)
    repository.add_candidate(candidate, db)
    repository.flush(db)
    return candidate
