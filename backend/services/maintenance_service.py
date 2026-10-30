"""Retention policy shared by local scheduling and authenticated cron."""
from repository.model_helpers import purge_expired_source_text
from services.ingestion_job_service import expire_jobs
from repository import maintenance_repository as store
import time

def maintain(db):
    run_id = store.start(db, time.time())
    counts = {}
    try:
        expire_jobs(db)
        purge_expired_source_text(db)
        counts = store.cleanup(db, time.time())
        from services.scheduled_digest_service import run_batch
        counts['digests'] = run_batch(db)
    except Exception as exc:
        store.rollback(db)
        store.finish(db, run_id, time.time(), counts, type(exc).__name__)
        raise
    store.finish(db, run_id, time.time(), counts)
    return {'status': 'completed', 'run_id': run_id, 'counts': counts}


def status(db):
    rows = store.recent(db)
    for row in rows:
        if row['status'] == 'running' and time.time() - row['started_at'] > 300:
            row['status'] = 'interrupted'
    last_success = next((row for row in rows if row['status'] == 'completed'), None)
    return {'items': rows, 'last_success': last_success, 'digests_needing_review': store.digest_attention(db, time.time()),
            'overdue': not last_success or time.time() - last_success['finished_at'] > 48 * 3600}
