from repository import transactions
'SQL persistence operations for ingestion, review and catalogue reads.'
import time
from sqlalchemy import or_, update, text
from models.schema import Account, Course, Job, Candidate, SourceDocument, FieldEvidence, CANDIDATE_SCHEMA_VERSION
from observe import normalize_job_usage

def list_jobs(db, page, page_size, statuses):
    query = db.query(Job).order_by(Job.created_at.desc())
    if statuses:
        query = query.filter(Job.status.in_(statuses))
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return (rows, total)

def list_candidates(db, job_filter, page, page_size, statuses):
    query = db.query(Candidate).filter(Candidate.status.in_(statuses)).order_by(Candidate.id)
    if job_filter:
        query = query.filter(Candidate.job_id == job_filter)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return (rows, total)

def get_course(course_id, db):
    return db.get(Course, course_id)

def check_connection(db):
    return db.execute(text('SELECT 1'))

def job_by_request_key(db, request_key):
    return db.query(Job).filter_by(request_key=request_key).first()

def add_job(db, job):
    return db.add(job)

def commit(db):
    return transactions.commit(db)

def rollback(db):
    return db.rollback()

def expired_running_jobs(db, lease_stale):
    return db.query(Job).filter(Job.status == 'running', lease_stale).all()

def interrupt_stale_job(db, job, lease_stale, result):
    return db.execute(update(Job).where(Job.id == job.id, Job.status == 'running', lease_stale).values(status='interrupted', lease_token=None, lease_until=None, started_at=None, result=result))

def clear_terminal_leases(db):
    return db.execute(update(Job).where(Job.status.in_(('queued', 'succeeded', 'partial', 'failed', 'interrupted')), or_(Job.lease_token.isnot(None), Job.lease_until.isnot(None), Job.started_at.isnot(None))).values(lease_token=None, lease_until=None, started_at=None))

def refresh_session(db):
    return db.expire_all()

def get_job(db, job_id):
    return db.get(Job, job_id)

def requeue_interrupted_job(db, job):
    return db.execute(update(Job).where(Job.id == job.id, Job.status == 'interrupted').values(status='queued', lease_token=None, lease_until=None, started_at=None, attempt=Job.attempt + 1, result=None, created_at=time.time()))

def lock_candidate(candidate_id, db):
    return db.query(Candidate).filter_by(id=candidate_id).with_for_update().first()

def add_course(course, db):
    return db.add(course)

def flush(db):
    return transactions.flush(db)

def delete_course_evidence(course, db):
    return db.query(FieldEvidence).filter_by(course_id=course.id).delete()

def latest_source_document(db, source_url):
    return db.query(SourceDocument).filter_by(canonical_url=source_url).order_by(SourceDocument.retrieved_at.desc()).first()

def add_reviewed_evidence(candidate, course, db, field, now, source, text, user):
    return db.add(FieldEvidence(course_id=course.id, candidate_id=candidate.id, source_document_id=source.id if source else None, field_name=field, excerpt=text[:2000], reviewed_by=user.id, reviewed_at=now))

def oldest_queued_job(db):
    return db.query(Job).filter_by(status='queued').order_by(Job.created_at).first()

def claim_queued_job(db, job, token):
    return db.execute(update(Job).where(Job.id == job.id, Job.status == 'queued').values(status='running', lease_token=token, lease_until=time.time() + 120, started_at=time.time()))

def renew_lease(body, db, job_id, now):
    return db.execute(update(Job).where(Job.id == job_id, Job.status == 'running', Job.lease_token == body.get('lease_token'), Job.lease_until >= now, Job.started_at >= now - 300).values(lease_until=now + 120))

def lock_job(db, job_id):
    return db.query(Job).filter_by(id=job_id).with_for_update().first()

def complete_running_job(body, db, job):
    return db.execute(update(Job).where(Job.id == job.id, Job.status == 'running').values(status=body.status, lease_token=None, lease_until=None, started_at=None))

def candidate_for_job(db, job, key):
    return db.query(Candidate).filter_by(job_id=job.id, source_key=key).order_by(Candidate.id).first()

def open_candidate_for_key(db, key):
    return db.query(Candidate).filter_by(source_key=key).filter(Candidate.status.in_(['pending', 'held'])).order_by(Candidate.id).first()

def rejected_candidate_for_key(db, key):
    return db.query(Candidate).filter_by(source_key=key, status='rejected').order_by(Candidate.id).first()

def get_matched_course(db, matched_id):
    return db.get(Course, matched_id)

def add_completed_candidate(data, db, job, key, reason, status):
    return db.add(Candidate(job_id=job.id, source_key=key, data=data, status=status, schema_version=CANDIDATE_SCHEMA_VERSION, review_reason=reason))

def source_document_by_hash(db, digest_key, url):
    return db.query(SourceDocument).filter_by(canonical_url=url, content_hash=digest_key).first()

def add_source_document(db, digest_key, item, job, stamp, url):
    return db.add(SourceDocument(job_id=job.id, canonical_url=url, content_hash=digest_key, retrieved_at=stamp if stamp is not None else 0, extraction_status=item.get('extraction_status') or 'failed', title=(item.get('title') or '')[:300], snippet=(item.get('snippet') or '')[:2000]))

def catalogue_save_job(body, db):
    return db.get(Job, body.job_id)

def first_operator(db):
    return db.query(Account).filter_by(role='operator').order_by(Account.email).first()

def expire_jobs(db):
    now = time.time()
    lease_stale = or_(Job.lease_until.is_(None), Job.lease_until < now, Job.started_at.is_(None), Job.started_at < now - 300)
    expired = expired_running_jobs(db, lease_stale)
    changed = False
    for job in expired:
        prior = job.result if isinstance(job.result, dict) else {}
        warnings = [str(item)[:500] for item in prior.get('warnings') or [] if item]
        warning = 'Worker lease expired. Retry explicitly to avoid hidden API spending.'
        if warning not in warnings:
            warnings.append(warning)
        result = {'warnings': warnings[-30:], 'usage': normalize_job_usage(prior.get('usage')), 'sources': [item for item in prior.get('sources') or [] if isinstance(item, dict)][:5]}
        if 'candidate_count' in prior:
            result['candidate_count'] = prior.get('candidate_count')
        updated = interrupt_stale_job(db, job, lease_stale, result)
        if updated.rowcount == 1:
            changed = True
    leftover = clear_terminal_leases(db)
    if leftover.rowcount:
        changed = True
    if changed:
        commit(db)
        refresh_session(db)
    elif expired:
        rollback(db)

def claim_specific_job(db, job_id, token, now):
    from shared.discovery_limits import SERVERLESS_LEASE_SECONDS
    changed = db.execute(update(Job).where(Job.id == job_id, Job.status == 'queued').values(status='running', lease_token=token, lease_until=now + SERVERLESS_LEASE_SECONDS, started_at=now))
    db.commit()
    return changed.rowcount == 1
