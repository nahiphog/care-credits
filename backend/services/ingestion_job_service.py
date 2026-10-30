import os
import secrets
import time
from domain.persistence import PersistenceConflict
from models.schema import Job
from domain.errors import DomainError
from domain.passwords import digest
from services.rate_limit import throttle
from serializers.common import job_json
from repository import discovery_repository as repository
from services.schedule_service import daily_ceiling, enqueue_daily, load_topics, local_today
from infrastructure.scraper_client import execute as execute_scraper
from services import discovery_status_service
from services.discovery_status_service import _paid_scrape_ready
from services.discovery_status_service import _reject_tavily_spend_without_model
from services.ingestion_completion_service import complete

def _claim_idle(reason):
    return {'_idle_reason': reason}

def create_job(body, request_key, user=None, db=None):
    _reject_tavily_spend_without_model()
    if os.getenv('SERVERLESS_MODE') == 'true' and body.max_results != 1:
        raise DomainError(422, 'Serverless discovery supports one source per run.')
    key = request_key
    if not 8 <= len(key) <= 100:
        raise DomainError(422, 'Supply an Idempotency-Key of 8ÃƒÆ’Ã†’Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬\xa0ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†’ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†’Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†’Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†’ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†’Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†’Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒ…Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†’ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒ…Ã¢â‚¬Å“100 characters.')
    request_key = digest(user.id + ':' + key)
    existing = repository.job_by_request_key(db, request_key)
    if existing:
        if existing.query != body.query or existing.max_results != body.max_results:
            raise DomainError(409, 'That request key belongs to another query.')
        return job_json(existing)
    throttle(db, 'jobs:' + user.id, 10, 3600)
    job = Job(account_id=user.id, request_key=request_key, query=body.query, max_results=body.max_results)
    repository.add_job(db, job)
    try:
        repository.commit(db)
    except PersistenceConflict:
        repository.rollback(db)
        raise DomainError(409, 'Request already received; refresh jobs.')
    return job_json(job)

def expire_jobs(db):
    return repository.expire_jobs(db)

def jobs(page=1, page_size=20, status=None, user=None, db=None):
    expire_jobs(db)
    if page < 1 or not 1 <= page_size <= 50:
        raise DomainError(422, 'Invalid pagination.')
    allowed = {'queued', 'running', 'succeeded', 'partial', 'failed', 'interrupted'}
    raw_status = (status or '').strip()
    statuses: list[str] | None
    if not raw_status:
        statuses = None
    else:
        parts = [part.strip() for part in raw_status.split(',') if part.strip()]
        if not parts or any((part not in allowed for part in parts)):
            raise DomainError(422, 'Invalid job status filter.')
        statuses = [name for name in ('queued', 'running', 'succeeded', 'partial', 'failed', 'interrupted') if name in parts]
    rows, total = repository.list_jobs(db, page, page_size, statuses)
    return {'items': [job_json(j) for j in rows], 'total': total, 'page': page, 'page_size': page_size, 'status': statuses}

def job_detail(job_id, user=None, db=None):
    expire_jobs(db)
    job = repository.get_job(db, job_id)
    if not job:
        raise DomainError(404, 'Job not found.')
    return job_json(job)

def retry_job(job_id, user=None, db=None):
    _reject_tavily_spend_without_model()
    expire_jobs(db)
    job = repository.get_job(db, job_id)
    if not job:
        raise DomainError(404, 'Job not found.')
    changed = repository.requeue_interrupted_job(db, job)
    if changed.rowcount != 1:
        repository.rollback(db)
        raise DomainError(409, 'Only interrupted jobs can be retried.')
    repository.commit(db)
    return job_json(repository.get_job(db, job_id))

def claim(db=None):
    expire_jobs(db)
    scraper = discovery_status_service._scraper_service_status()
    if not _paid_scrape_ready(scraper):
        return _claim_idle('not_ready')
    lost_races = 0
    while True:
        job = repository.oldest_queued_job(db)
        if not job:
            return _claim_idle('lost_lease' if lost_races else 'empty')
        token = secrets.token_urlsafe(24)
        result = repository.claim_queued_job(db, job, token)
        repository.commit(db)
        if result.rowcount == 1:
            return {'id': job.id, 'query': job.query, 'max_results': job.max_results, 'lease_token': token}
        lost_races += 1
        repository.refresh_session(db)

def heartbeat(job_id, body, db=None):
    now = time.time()
    result = repository.renew_lease(body, db, job_id, now)
    repository.commit(db)
    if result.rowcount != 1:
        raise DomainError(409, 'Job lease is no longer active.')
    return {'ok': True}

def scrape_topics(user=None):
    try:
        topics = load_topics()
    except ValueError as exc:
        raise DomainError(503, str(exc))
    return {'topics': topics, 'ceiling': daily_ceiling(), 'day': local_today(), 'source': 'config/scrape_topics.json'}

def trigger_daily_scrape(force=False, user=None, db=None):
    if os.getenv('SERVERLESS_MODE') == 'true':
        raise DomainError(409, 'Use individual bounded discovery runs on this deployment.')
    _reject_tavily_spend_without_model()
    result = enqueue_daily(db, force=force)
    if result.get('error'):
        raise DomainError(503, result['error'])
    return result

def run_serverless_job(job_id, user=None, db=None):
    if os.getenv('SERVERLESS_MODE') != 'true':
        raise DomainError(404, 'Request-based discovery is not enabled.')
    _reject_tavily_spend_without_model()
    expire_jobs(db)
    job = repository.get_job(db, job_id)
    if not job:
        raise DomainError(404, 'Job not found.')
    if job.status in ('succeeded', 'partial', 'failed'):
        return job_json(job)
    if job.max_results != 1:
        raise DomainError(422, 'Create a new job with one source.')
    if job.status != 'queued':
        raise DomainError(409, 'Job already running or requires an explicit retry.')
    # A conservative project-wide daily attempt ceiling includes manual retries.
    # Terminal idempotent reads above never consume budget or call either provider.
    try:
        daily_limit = int(os.getenv('DISCOVERY_DAILY_RUN_LIMIT', '10'))
    except ValueError:
        raise DomainError(503, 'Discovery daily limit is invalid.')
    if not 1 <= daily_limit <= 100:
        raise DomainError(503, 'Discovery daily limit must be between 1 and 100.')
    throttle(db, 'discovery-project-day', daily_limit, 86400)
    token = secrets.token_urlsafe(24)
    from shared.discovery_limits import SERVERLESS_LEASE_SECONDS
    claimed_at = time.time()
    if not repository.claim_specific_job(db, job_id, token, claimed_at):
        raise DomainError(409, 'Job already running or requires an explicit retry.')
    payload = execute_scraper({'id': job_id, 'query': job.query, 'max_results': 1, 'lease_token': token,
                              'expires_at': claimed_at + SERVERLESS_LEASE_SECONDS})
    complete(job_id, payload, db)
    repository.refresh_session(db)
    return job_json(repository.get_job(db, job_id))
