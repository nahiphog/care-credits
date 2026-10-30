from domain.persistence import PersistenceConflict
from domain.errors import DomainError
from domain.training_validation import validate_training
from repository import discovery_repository as repository
from services.catalogue_review import source_key, course_public, exact_course, near_neighbours, save_new_candidate, link_existing, publish_new_event, auto_publish_new, reopen_review_candidate, open_review_candidate
from jev import decide_existence, JevError, api_key as typesafe_key, confidence_floor, unit_interval
from services.schedule_service import local_today

def catalogue_connect(db=None):
    try:
        repository.check_connection(db)
    except Exception:
        raise DomainError(503, 'Catalogue database is unavailable.')
    return {'status': 'connected', 'database': 'ready', 'typesafe_configured': bool(typesafe_key()), 'local_day': local_today()}

def catalogue_lookup(body, db=None):
    try:
        training = validate_training(body.candidate)
    except ValueError as exc:
        raise DomainError(422, str(exc))
    data = training
    key = source_key(data)
    exact = exact_course(db, key)
    neighbours = [] if exact else near_neighbours(db, data)
    return {'source_key': key, 'exact': course_public(exact) if exact else None, 'matches': [course_public(row) for row in neighbours]}

def catalogue_decide(body, db=None):
    try:
        training = validate_training(body.candidate)
    except ValueError as exc:
        raise DomainError(422, str(exc))
    data = training
    key = source_key(data)
    exact = exact_course(db, key)
    if exact:
        judgment = {'decision': 'exists', 'confidence': 1.0, 'probabilities': {'exists': 1.0, 'new': 0.0, 'uncertain': 0.0}, 'matched_session_id': exact.id, 'warning': None, 'source_key': key}
    else:
        matches = body.matches if body.matches is not None else [course_public(row) for row in near_neighbours(db, data)]
        try:
            judgment = decide_existence(data, matches)
        except JevError as exc:
            raise DomainError(exc.status_code, exc.detail)
        judgment['source_key'] = key
    pending = open_review_candidate(db, key)
    if pending:
        pending.data = {**(pending.data or {}), '_judgment': judgment}
        if pending.status == 'rejected':
            decision = judgment.get('decision')
            new_status = 'held' if decision in ('uncertain', 'exists') else 'pending'
            reason = ('Jev uncertain: ' + str(judgment.get('warning') or 'needs operator review'))[:500] if new_status == 'held' and decision == 'uncertain' else 'Jev marked exists; review refresh before overwriting published fields.' if new_status == 'held' else ''
            reopen_review_candidate(pending, status=new_status, reason=reason)
        repository.commit(db)
        judgment['candidate_id'] = pending.id
    return judgment

def catalogue_save(body, db=None):
    try:
        training = validate_training(body.candidate)
    except ValueError as exc:
        raise DomainError(422, str(exc))
    judgment = body.judgment or {}
    decision = judgment.get('decision')
    job = repository.catalogue_save_job(body, db) if body.job_id else None
    if body.job_id and (not job):
        raise DomainError(404, 'Job not found.')
    account_id = job.account_id if job else None
    if not account_id:
        op = repository.first_operator(db)
        if not op:
            raise DomainError(503, 'No operator account available to own catalogue saves.')
        account_id = op.id
    data = training
    key = source_key(data)
    if decision == 'exists':
        matched_id = judgment.get('matched_session_id')
        course = repository.get_matched_course(db, matched_id) if matched_id else exact_course(db, key)
        if not course:
            raise DomainError(404, 'Matched catalogue session was not found.')
        try:
            candidate = link_existing(db, account_id, training, course, judgment, body.job_id)
            repository.commit(db)
        except PersistenceConflict:
            repository.rollback(db)
            raise DomainError(409, 'A refresh candidate for this session already exists. Refresh.')
        return {'status': 'exists', 'candidate_id': candidate.id, 'course_id': course.id, 'decision': 'exists'}
    if decision == 'uncertain':
        try:
            candidate = save_new_candidate(db, account_id, training, judgment, body.job_id)
            repository.commit(db)
        except ValueError as exc:
            raise DomainError(409, str(exc))
        return {'status': 'held', 'candidate_id': candidate.id, 'decision': 'uncertain'}
    if decision != 'new':
        raise DomainError(422, 'Judgment decision must be exists, new, or uncertain.')
    confidence = unit_interval(judgment.get('confidence'), 0.0)
    if not auto_publish_new() or confidence < confidence_floor():
        try:
            candidate = save_new_candidate(db, account_id, training, judgment, body.job_id)
            repository.commit(db)
        except ValueError as exc:
            raise DomainError(409, str(exc))
        except PersistenceConflict:
            repository.rollback(db)
            raise DomainError(409, 'Event already exists in the catalogue.')
        return {'status': 'pending', 'candidate_id': candidate.id, 'decision': 'new'}
    try:
        candidate, course = publish_new_event(db, account_id, training, judgment, body.job_id)
        repository.commit(db)
    except ValueError as exc:
        repository.rollback(db)
        raise DomainError(409, str(exc))
    except PersistenceConflict:
        repository.rollback(db)
        raise DomainError(409, 'Event already exists in the catalogue.')
    return {'status': 'published', 'candidate_id': candidate.id, 'course_id': course.id, 'decision': 'new'}
