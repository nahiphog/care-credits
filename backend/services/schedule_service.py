"""Daily scrape enqueue for the owned-catalogue agent (OPS-02 / DEC-09)."""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from domain.passwords import digest
from repository.schedule_repository import ScheduleRepository


ROOT = Path(__file__).resolve().parents[2]
TOPICS_PATH = Path(os.getenv('SCRAPE_TOPICS_FILE') or ROOT / 'config' / 'scrape_topics.json')
TZ = ZoneInfo('Asia/Kuala_Lumpur')


def local_today() -> str:
    return datetime.now(TZ).date().isoformat()


def daily_request_key(day: str, query: str) -> str:
    """Queryable day-scoped key so the ceiling counts every daily job that day.

    Prefix form `daily:{day}:{digest(query)}` (not an opaque digest of the whole
    string) lets recount include jobs from a prior mid-day topic list swap.
    """
    return f'daily:{day}:{digest(query)}'


def _topic_max_results(raw) -> int | None:
    """Clamp max_results to 1–5, or None when the row is invalid (never invent spend)."""
    # Reject bools (JSON true/false): int(True)==1 would silently clamp instead of skipping.
    if isinstance(raw, bool):
        return None
    if raw in (None, ''):
        return 5
    # Reject non-finite floats before int(): int(inf) raises OverflowError (observe usage parity).
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    try:
        max_results = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(1, min(max_results, 5))


def load_topics() -> list[dict]:
    """Load curated topics; clamp max_results to 1–5 and skip invalid rows.

    No silent topic-count truncate: DAILY_SCRAPE_JOB_CEILING owns the spend bound.
    """
    if not TOPICS_PATH.exists():
        return [{'query': 'GP CPD courses Kuala Lumpur', 'max_results': 5}]
    try:
        data = json.loads(TOPICS_PATH.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('scrape_topics.json is not valid JSON') from exc
    if not isinstance(data, list):
        raise ValueError('scrape_topics.json must be a list of {query,max_results}')
    topics = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_query = item.get('query')
        # Reject bool/number queries: str(True)=='True' / str(123) would invent spend topics.
        if not isinstance(raw_query, str):
            continue
        query = raw_query.strip()
        if not (3 <= len(query) <= 300):
            continue
        max_results = _topic_max_results(item.get('max_results'))
        if max_results is None:
            continue
        topics.append({'query': query, 'max_results': max_results})
    return topics


def daily_ceiling() -> int:
    try:
        return max(1, int(os.getenv('DAILY_SCRAPE_JOB_CEILING', '10')))
    except ValueError:
        return 10


def operator_account(db):
    return ScheduleRepository(db).operator()


def daily_jobs_used(db, day: str) -> int:
    """Count every daily-scrape job for the KL day, independent of the current topic list."""
    return ScheduleRepository(db).count_daily(day)


def enqueue_daily(db, force: bool = False) -> dict:
    """Enqueue one job per curated topic for today, respecting the daily ceiling."""
    # force=true: expire aged-stuck running leases first (parity with retry_job) so they
    # become interrupted and eligible to re-queue. Lazy import avoids the schedule/job-service cycle.
    if force:
        from services.ingestion_job_service import expire_jobs
        expire_jobs(db)
    # Serialize concurrent auto-tick + operator POST so ceiling cannot race across sessions.
    repository = ScheduleRepository(db)
    op = repository.operator(lock=True)
    if not op:
        return {'enqueued': 0, 'skipped': 0, 'day': local_today(), 'error': 'No operator account to own scheduled jobs.'}
    day = local_today()
    try:
        topics = load_topics()
    except ValueError as exc:
        return {'enqueued': 0, 'skipped': 0, 'day': day, 'error': str(exc)}
    ceiling = daily_ceiling()
    enqueued = 0
    skipped = 0
    for topic in topics:
        # Defense in depth: same query/max_results rules as load_topics (patched callers / bad rows).
        raw_query = topic.get('query') if isinstance(topic, dict) else None
        if not isinstance(raw_query, str):
            skipped += 1
            continue
        query = raw_query.strip()
        if not (3 <= len(query) <= 300):
            skipped += 1
            continue
        max_results = _topic_max_results(topic.get('max_results') if isinstance(topic, dict) else None)
        if max_results is None:
            skipped += 1
            continue
        request_key = daily_request_key(day, query)
        existing = repository.find_job(request_key)
        if existing and not force:
            skipped += 1
            continue
        # force=true re-queues idle (interrupted/failed/partial) jobs only — never replay succeeded spend.
        if existing and force and existing.status not in ('interrupted', 'failed', 'partial'):
            skipped += 1
            continue
        if existing and force:
            repository.requeue(existing, query, max_results, time.time())
            enqueued += 1
            continue
        # Re-count from DB so concurrent callers (after lock) and earlier inserts in this
        # transaction cannot push the day past the ceiling — includes jobs from a prior
        # mid-day topic list (whole-day ceiling, not current-key-set only).
        used_today = daily_jobs_used(db, day)
        if used_today >= ceiling:
            skipped += 1
            continue
        if not repository.insert_job(op.id, request_key, query, max_results, time.time()):
            skipped += 1
            continue
        enqueued += 1
    repository.commit()
    return {'enqueued': enqueued, 'skipped': skipped, 'day': day, 'ceiling': ceiling, 'topics': len(topics)}
