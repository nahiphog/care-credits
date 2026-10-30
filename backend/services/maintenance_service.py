"""Retention policy shared by local scheduling and authenticated cron."""
from repository.model_helpers import purge_expired_source_text
from services.ingestion_job_service import expire_jobs

def maintain(db):
    expire_jobs(db)
    purge_expired_source_text(db)
    return {'status': 'completed'}
