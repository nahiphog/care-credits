import secrets
import time
from domain.persistence import PersistenceConflict
from models.schema import CANDIDATE_SCHEMA_VERSION
from repository.model_helpers import retrieved_stamp
from domain.errors import DomainError
from domain.passwords import digest
from domain.training_validation import validate_training
from serializers.common import public_source_payload
from repository import discovery_repository as repository
from observe import normalize_job_usage, job_line
from services.catalogue_review import source_key, exact_course, link_existing, reopen_review_candidate, refresh_diff

def _complete_candidate_payload(raw):
    """Build stored candidate data + status/reason from a complete payload (optional `_judgment`)."""
    payload = {key: value for key, value in raw.items() if not str(key).startswith('_')}
    training = validate_training(payload)
    data = training
    judgment = raw.get('_judgment') if isinstance(raw.get('_judgment'), dict) else None
    if judgment:
        data['_judgment'] = judgment
    status = 'pending'
    reason = ''
    if (judgment or {}).get('decision') == 'uncertain':
        status = 'held'
        reason = ('Jev uncertain: ' + str(judgment.get('warning') or 'needs operator review'))[:500]
    elif (judgment or {}).get('decision') == 'exists':
        status = 'held'
        reason = 'Jev marked exists; review refresh before overwriting published fields.'
        if judgment.get('matched_session_id'):
            data['_matched_course_id'] = judgment.get('matched_session_id')
    return (data, status, reason)

def _merge_candidate_data(existing_data, data):
    """Refresh fields but keep omitted `_*` metadata (judgment, refresh diff, fixture labels)."""
    merged = dict(data)
    for key, value in (existing_data or {}).items():
        if str(key).startswith('_') and key not in merged:
            merged[key] = value
    return merged

def complete(job_id, body, db=None):
    job = repository.lock_job(db, job_id)
    if not job:
        raise DomainError(409, 'Job lease does not match.')
    if job.status in ('succeeded', 'partial', 'failed'):
        if job.lease_token is not None or job.lease_until is not None or job.started_at is not None:
            job.lease_token = None
            job.lease_until = None
            job.started_at = None
            repository.commit(db)
        return {'status': job.status}
    job_token = job.lease_token or ''
    if not job_token or not secrets.compare_digest(job_token.encode(), body.lease_token.encode()):
        raise DomainError(409, 'Job lease does not match.')
    if job.status != 'running' or job.lease_until is None or job.lease_until < time.time() or (job.started_at is None) or (job.started_at < time.time() - 300):
        raise DomainError(409, 'Job lease expired.')
    changed = repository.complete_running_job(body, db, job)
    if changed.rowcount != 1:
        repository.rollback(db)
        return {'status': repository.get_job(db, job_id).status}
    job.lease_token = None
    job.lease_until = None
    job.started_at = None
    seen = set()
    for raw in body.candidates:
        try:
            data, status, reason = _complete_candidate_payload(raw)
        except ValueError as exc:
            raise DomainError(422, str(exc))
        key = source_key(data)
        if key in seen:
            continue
        seen.add(key)
        same_job = repository.candidate_for_job(db, job, key)
        open_row = repository.open_candidate_for_key(db, key)
        rejected_row = None if open_row else repository.rejected_candidate_for_key(db, key)
        if open_row and same_job and (same_job.status == 'rejected') and (same_job.id != open_row.id):
            target = open_row
        elif same_job:
            target = same_job
        else:
            target = open_row or rejected_row
        if target:
            incoming_judgment = data.get('_judgment') if isinstance(data.get('_judgment'), dict) else None
            target.data = _merge_candidate_data(target.data, data)
            target.schema_version = CANDIDATE_SCHEMA_VERSION
            merged_judgment = target.data.get('_judgment') if isinstance(target.data.get('_judgment'), dict) else None
            decision = (merged_judgment or {}).get('decision')
            incoming_decision = (incoming_judgment or {}).get('decision')
            if incoming_decision == 'new':
                target_status, target_reason = ('pending', '')
            elif status == 'held' or decision in ('uncertain', 'exists'):
                target_status = 'held'
                if status == 'held':
                    target_reason = reason
                elif decision == 'uncertain':
                    target_reason = ('Jev uncertain: ' + str(merged_judgment.get('warning') or 'needs operator review'))[:500]
                elif decision == 'exists':
                    target_reason = 'Jev marked exists; review refresh before overwriting published fields.'
                else:
                    target_reason = target.review_reason or ''
            elif not incoming_judgment and target.status == 'held':
                target_status = 'held'
                target_reason = target.review_reason or ''
            else:
                target_status, target_reason = ('pending', '')
            matched_id = target.resulting_course_id or target.data.get('_matched_course_id')
            if target_status == 'held' and decision == 'exists' and matched_id:
                matched = repository.get_matched_course(db, matched_id)
                if matched:
                    bare = {k: v for k, v in target.data.items() if not str(k).startswith('_')}
                    target.data = {**target.data, '_matched_course_id': matched.id, '_refresh_diff': refresh_diff(matched, bare)}
                    target.resulting_course_id = matched.id
            reopen_review_candidate(target, status=target_status, reason=target_reason)
            continue
        matched = exact_course(db, key)
        if matched:
            judgment = data.get('_judgment') if isinstance(data.get('_judgment'), dict) else {}
            judgment = {**judgment, 'decision': 'exists', 'matched_session_id': matched.id}
            bare = {k: v for k, v in data.items() if not str(k).startswith('_')}
            link_existing(db, job.account_id, bare, matched, judgment, job.id)
            continue
        repository.add_completed_candidate(data, db, job, key, reason, status)
    job.status = body.status
    sources = [public_source_payload(item) for item in body.sources]
    usage = normalize_job_usage(body.usage)
    job.result = {'extractions': [item for item in body.extractions], 'candidate_count': len(seen), 'warnings': [w[:500] for w in body.warnings], 'usage': usage, 'sources': sources}
    for item in sources:
        url = (item.get('url') or '').split('#')[0]
        if not url:
            continue
        digest_key = digest(url + '|' + (item.get('snippet') or '')[:500])
        if not repository.source_document_by_hash(db, digest_key, url):
            stamp = retrieved_stamp(item)
            repository.add_source_document(db, digest_key, item, job, stamp, url)
    try:
        repository.commit(db)
    except PersistenceConflict:
        repository.rollback(db)
        raise DomainError(409, 'A review candidate for this session already exists. Refresh.')
    job_line(job.id, job.status, len(seen), len(body.sources), usage, len(body.warnings))
    return {'status': job.status}
