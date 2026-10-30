"""Explicit startup/migration and local process lifecycle."""
import asyncio
import os
from contextlib import asynccontextmanager
from database import Base, engine, SessionLocal
from database.migrations import migrate_schema
from domain.config import production_env, digest_available
from observe import log


def initialize():
    if os.getenv('DEMO_MODE') == 'true' and production_env():
        raise RuntimeError('Demo mode cannot run in production')
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        migrate_schema(db)
        if os.getenv('DEMO_MODE') == 'true':
            from seed_demo import seed
            seed(db)


@asynccontextmanager
async def lifespan(app):
    if os.getenv('SERVERLESS_MODE') == 'true':
        # DDL runs explicitly before promotion, never concurrently on cold starts.
        yield
        return
    initialize()
    from services.maintenance_service import maintain
    from services.digest_service import run_due_digests
    from services.discovery_status_service import _paid_scrape_ready
    from services.schedule_service import enqueue_daily
    stop = asyncio.Event()

    def daily(db):
        if _paid_scrape_ready():
            enqueue_daily(db)

    async def periodic(operation, seconds):
        while not stop.is_set():
            try:
                def execute():
                    with SessionLocal() as db:
                        operation(db)
                await asyncio.to_thread(execute)
            except Exception as exc:
                log.warning('periodic_task=%s failure_type=%s', operation.__name__, type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass

    tasks = [asyncio.create_task(periodic(maintain, 86400))]
    if os.getenv('DAILY_SCRAPE_ENABLED', 'true').lower() == 'true':
        tasks.append(asyncio.create_task(periodic(daily, 3600)))
    if digest_available():
        tasks.append(asyncio.create_task(periodic(run_due_digests, 3600)))
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
