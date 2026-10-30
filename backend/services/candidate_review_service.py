import time
from domain.persistence import PersistenceConflict
from models.schema import Course
from repository.model_helpers import fill_course
from domain.errors import DomainError
from domain.training_validation import validate_training
from serializers.common import course_json
from repository.audit_repository import audit
from repository import discovery_repository as repository
from services.catalogue_review import source_key, exact_course, training_payload, resolve_review_course

def candidates(page=1, page_size=20, status=None, job_id=None, user=None, db=None):
    if page < 1 or not 1 <= page_size <= 50:
        raise DomainError(422, 'Invalid pagination.')
    allowed = {'pending', 'held', 'rejected', 'published'}
    raw_status = (status or '').strip()
    if not raw_status or raw_status == 'awaiting':
        statuses = ['pending', 'held']
    else:
        parts = [part.strip() for part in raw_status.split(',') if part.strip()]
        if not parts or any((part not in allowed for part in parts)):
            raise DomainError(422, 'Invalid candidate status filter.')
        statuses = [name for name in ('pending', 'held', 'rejected', 'published') if name in parts]
    job_filter = (job_id or '').strip() or None
    rows, total = repository.list_candidates(db, job_filter, page, page_size, statuses)
    return {'items': [{'id': c.id, 'job_id': c.job_id, 'data': c.data, 'status': c.status, 'reason': c.review_reason or '', 'version': c.version, 'schema_version': c.schema_version, 'resulting_course_id': c.resulting_course_id} for c in rows], 'total': total, 'page': page, 'page_size': page_size, 'status': statuses, 'job_id': job_filter}

def review(candidate_id, body, user=None, db=None):
    candidate = repository.lock_candidate(candidate_id, db)
    if not candidate:
        raise DomainError(404, 'Candidate not found.')
    if candidate.status == 'published':
        if body.action == 'publish' and (not body.corrections):
            return {'status': candidate.status, 'reason': candidate.review_reason or '', 'version': candidate.version, 'resulting_course_id': candidate.resulting_course_id}
        if body.action != 'publish':
            raise DomainError(409, 'Published courses can only be corrected or cancelled.')
    was_published = candidate.status == 'published'
    previous = dict(candidate.data or {})
    if candidate.status not in ('pending', 'held', 'rejected', 'published'):
        raise DomainError(409, 'This candidate cannot be reviewed. Refresh.')
    if body.version != candidate.version:
        raise DomainError(409, 'This candidate changed. Refresh before reviewing.')
    reason = body.reason.strip()
    now = time.time()
    if body.action == 'publish':
        data = dict(candidate.data or {})
        if body.corrections:
            source_text = str(data.get('source_text') or '')
            if not source_text.strip():
                raise DomainError(422, 'Source text is missing. Reject, hold, or ingest a better source.')
            evidence = dict(data.get('evidence') or {})
            for field, value in body.corrections.items():
                excerpt = str(body.evidence.get(field) or '').strip()
                if not excerpt or excerpt not in source_text:
                    raise DomainError(422, 'Correction for ' + field + ' needs a verbatim source excerpt.')
                if field in ('fee', 'points') and value not in ('', None):
                    try:
                        data[field] = float(value)
                    except ValueError:
                        raise DomainError(422, 'Correction for ' + field + ' must be a number.')
                else:
                    data[field] = value
                evidence[field] = excerpt
            data['evidence'] = evidence
            candidate.data = data
        try:
            training = validate_training(training_payload(data))
        except ValueError:
            raise DomainError(422, 'Source evidence is incomplete. Reject or ingest a better source.')
        payload = training
        is_fixture = bool((candidate.data or {}).get('_fixture'))
        course = resolve_review_course(db, candidate)
        next_key = source_key(payload)
        if course:
            if next_key != course.source_key:
                conflict = exact_course(db, next_key)
                if conflict and conflict.id != course.id:
                    if (conflict.publication_status or '') == 'cancelled' or (conflict.cancellation_status or '') == 'cancelled':
                        course = conflict
                    else:
                        raise DomainError(409, 'Another catalogue session already uses this identity. Refresh.')
            fill_course(course, payload, demo=True if is_fixture else None)
            if next_key != course.source_key:
                course.source_key = next_key
        else:
            conflict = exact_course(db, next_key)
            if conflict:
                if (conflict.publication_status or '') == 'cancelled' or (conflict.cancellation_status or '') == 'cancelled':
                    course = conflict
                    fill_course(course, payload, demo=True if is_fixture else None)
                else:
                    raise DomainError(409, 'Another catalogue session already uses this identity. Refresh.')
            else:
                course = fill_course(Course(source_key=next_key), payload, demo=is_fixture)
                repository.add_course(course, db)
        repository.flush(db)
        candidate.resulting_course_id = course.id
        if not is_fixture and (not str(candidate.source_key or '').startswith('demo-candidate-')):
            candidate.source_key = next_key
        course.publication_status = 'published'
        course.cancellation_status = 'active'
        course.verification_status = 'source_reviewed'
        course.reviewed_by = user.id
        course.reviewed_at = now
        repository.delete_course_evidence(course, db)
        source_url = str(payload.get('source_url') or '').split('#')[0]
        source = repository.latest_source_document(db, source_url) if source_url else None
        for field, excerpt in (payload.get('evidence') or {}).items():
            text = str(excerpt or '').strip()
            if not text:
                continue
            repository.add_reviewed_evidence(candidate, course, db, field, now, source, text, user)
        candidate.status = 'published'
    elif body.action == 'hold':
        candidate.status = 'held'
    else:
        candidate.status = 'rejected'
    candidate.review_reason = reason
    candidate.reviewed_by = user.id
    candidate.reviewed_at = now
    candidate.version = candidate.version + 1
    audit(db, user.id, 'candidate_corrected' if was_published else 'candidate_' + candidate.status, candidate.id, {'reason': reason, 'corrections': {field: {'before': previous.get(field), 'after': candidate.data.get(field)} for field in body.corrections}})
    try:
        repository.commit(db)
    except PersistenceConflict:
        repository.rollback(db)
        raise DomainError(409, 'Another catalogue session already uses this identity. Refresh.')
    return {'status': candidate.status, 'reason': candidate.review_reason, 'version': candidate.version, 'resulting_course_id': candidate.resulting_course_id}

def cancel_training(course_id, user=None, db=None):
    course = repository.get_course(course_id, db)
    if not course:
        raise DomainError(404, 'Training not found.')
    course.publication_status = 'cancelled'
    course.cancellation_status = 'cancelled'
    course.updated_at = time.time()
    audit(db, user.id, 'course_cancelled', course.id, {'publication_status': 'cancelled'})
    repository.commit(db)
    return course_json(course)
