import csv
import io
import json
import math
import os
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from contextlib import asynccontextmanager
from datetime import date, datetime
from email.message import EmailMessage
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, or_, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from database import Base, engine, get_db, SessionLocal
from portal_models import (
    Account, LoginSession, Course, Record, RecordHistory, Job, Candidate, Audit, SchemaVersion,
    DigestPreference, AffiliationCertificate, FieldEvidence, SourceDocument,
    SCHEMA_VERSION, FILTER_FIELDS, fill_course, CANDIDATE_SCHEMA_VERSION,
    purge_expired_source_text, listed_filter, retrieved_stamp,
)
from security import current_user, operator, worker, password_hash, password_matches, digest, throttle
from shared.contracts import Training, public_web_url, validate_evidence
from shared.model_defaults import env_or_provisional, using_provisional
from catalogue import (
    source_key, course_public, exact_course, near_neighbours,
    save_new_candidate, link_existing, publish_new_event,
    training_payload, resolve_review_course, auto_publish_new,
    reopen_review_candidate, open_review_candidate, refresh_diff,
)
from observe import setup as setup_logs, request_line, job_line, log as app_log, normalize_job_usage
from jev import decide_existence, JevError, api_key as typesafe_key, confidence_floor, unit_interval
from schedule import daily_ceiling, enqueue_daily, load_topics, local_today
from digest import (
    ensure_preference, preference_json, progress_snapshot, run_due_digests,
)
from certificates import issue_certificate, certificate_json, render_html as certificate_html, render_pdf as certificate_pdf
from suggestions import suggestions_for
from errors import envelope, http_exception_handler, validation_exception_handler, request_id
from oauth import (
    authorize_url,
    configured as google_oauth,
    exchange_code,
    issue_session,
    public_frontend_base,
    upsert_account,
    OAuthError,
)


def today():
    return datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date()


def client_host(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return 'unknown'


def production_env() -> bool:
    """True when APP_ENV is production (strip + casefold so padding/Production still harden cookies)."""
    return (os.getenv('APP_ENV') or '').strip().casefold() == 'production'


def initialize():
    if os.getenv('DEMO_MODE') == 'true' and production_env():
        raise RuntimeError('Demo mode cannot run in production')
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        migrate_schema(db)
        if os.getenv('DEMO_MODE') == 'true':
            from seed_demo import seed
            seed(db)


def migrate_schema(db):
    versions = db.query(SchemaVersion).all()
    current = max((v.version for v in versions), default=0)
    if current == 0:
        db.add(SchemaVersion(version=SCHEMA_VERSION))
        db.commit()
        return
    if current == 1:
        _add_course_filter_columns(db)
        for course in db.query(Course).all():
            fill_course(course, course.data or {})
        db.add(SchemaVersion(version=2))
        current = 2
    if current == 2:
        _add_candidate_review_reason(db)
        db.add(SchemaVersion(version=3))
        current = 3
        db.commit()
    if current == 3:
        # DigestPreference / DigestSend / AffiliationCertificate created via create_all.
        db.add(SchemaVersion(version=4))
        current = 4
        db.commit()
    if current == 4:
        _add_signup_status(db)
        db.add(SchemaVersion(version=5))
        current = 5
        db.commit()
    if current == 5:
        _add_account_state(db)
        db.add(SchemaVersion(version=6))
        current = 6
        db.commit()
    if current == 6:
        _add_account_identity(db)
        db.add(SchemaVersion(version=7))
        current = 7
        db.commit()
    if current == 7:
        _add_review_and_record_origin(db)
        db.add(SchemaVersion(version=8))
        current = 8
        db.commit()
    if current == 8:
        _add_source_documents_and_job_limits(db)
        db.add(SchemaVersion(version=9))
        current = 9
        db.commit()
    if current == 9:
        _add_attendance_status_and_attempts(db)
        db.add(SchemaVersion(version=10))
        current = 10
        db.commit()
    if current == 10:
        _add_account_coordinates(db)
        db.add(SchemaVersion(version=11))
        current = 11
        db.commit()
    if current == 11:
        _add_created_at_and_digest_counts(db)
        db.add(SchemaVersion(version=12))
        current = 12
        db.commit()
    if current == 12:
        _add_candidate_resulting_course(db)
        db.add(SchemaVersion(version=13))
        current = 13
        db.commit()
    if current == 13:
        _add_candidate_schema_version(db)
        db.add(SchemaVersion(version=14))
        current = 14
        db.commit()
    if current == 14:
        _add_publication_status(db)
        db.add(SchemaVersion(version=15))
        current = 15
        db.commit()
    if current == 15:
        _add_session_schedule(db)
        db.add(SchemaVersion(version=16))
        current = 16
        db.commit()
    if current == 16:
        _add_digest_backoff(db)
        db.add(SchemaVersion(version=17))
        current = 17
        db.commit()
    if current != SCHEMA_VERSION:
        raise RuntimeError('Unsupported portal schema. Apply the matching migration.')


def _add_course_filter_columns(db):
    existing = {column['name'] for column in inspect(db.get_bind()).get_columns('courses')}
    statements = [
        ('title', "VARCHAR DEFAULT '' NOT NULL"),
        ('provider', "VARCHAR DEFAULT '' NOT NULL"),
        ('description', "VARCHAR DEFAULT '' NOT NULL"),
        ('start_date', 'VARCHAR'),
        ('city', 'VARCHAR'),
        ('state', 'VARCHAR'),
        ('country', "VARCHAR DEFAULT 'MY' NOT NULL"),
        ('mode', "VARCHAR DEFAULT 'online' NOT NULL"),
        ('latitude', 'FLOAT'),
        ('longitude', 'FLOAT'),
        ('fee', 'FLOAT'),
        ('currency', 'VARCHAR'),
        ('points', 'FLOAT'),
        ('credit_label', 'VARCHAR'),
        ('difficulty', 'VARCHAR'),
    ]
    for name, definition in statements:
        if name not in existing:
            db.execute(text(f'ALTER TABLE courses ADD COLUMN {name} {definition}'))
    db.commit()


def _add_candidate_review_reason(db):
    existing = {column['name'] for column in inspect(db.get_bind()).get_columns('course_candidates')}
    if 'review_reason' not in existing:
        db.execute(text("ALTER TABLE course_candidates ADD COLUMN review_reason VARCHAR DEFAULT '' NOT NULL"))
    db.commit()


def _add_signup_status(db):
    existing = {column['name'] for column in inspect(db.get_bind()).get_columns('doctor_records')}
    if 'signup_status' not in existing:
        db.execute(text("ALTER TABLE doctor_records ADD COLUMN signup_status VARCHAR DEFAULT 'not_recorded' NOT NULL"))
        db.execute(text("UPDATE doctor_records SET signup_status = 'signed_up' WHERE signed_up = 1"))
    db.commit()


def _add_account_state(db):
    existing = {column['name'] for column in inspect(db.get_bind()).get_columns('accounts')}
    if 'state' not in existing:
        db.execute(text("ALTER TABLE accounts ADD COLUMN state VARCHAR DEFAULT '' NOT NULL"))
    db.commit()


def _add_account_identity(db):
    existing = {column['name'] for column in inspect(db.get_bind()).get_columns('accounts')}
    if 'identity_issuer' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN identity_issuer VARCHAR'))
    if 'identity_subject' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN identity_subject VARCHAR'))
    db.commit()


def _add_review_and_record_origin(db):
    courses = {column['name'] for column in inspect(db.get_bind()).get_columns('courses')}
    if 'verification_status' not in courses:
        db.execute(text("ALTER TABLE courses ADD COLUMN verification_status VARCHAR DEFAULT 'unverified' NOT NULL"))
    if 'reviewed_by' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN reviewed_by VARCHAR'))
    if 'reviewed_at' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN reviewed_at FLOAT'))
    records = {column['name'] for column in inspect(db.get_bind()).get_columns('doctor_records')}
    if 'signed_up_at' not in records:
        db.execute(text('ALTER TABLE doctor_records ADD COLUMN signed_up_at FLOAT'))
    if 'points_origin' not in records:
        db.execute(text("ALTER TABLE doctor_records ADD COLUMN points_origin VARCHAR DEFAULT '' NOT NULL"))
    candidates = {column['name'] for column in inspect(db.get_bind()).get_columns('course_candidates')}
    if 'reviewed_at' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN reviewed_at FLOAT'))
    db.commit()


def _add_source_documents_and_job_limits(db):
    bind = db.get_bind()
    jobs = {column['name'] for column in inspect(bind).get_columns('ingestion_jobs')}
    if 'max_results' not in jobs:
        db.execute(text('ALTER TABLE ingestion_jobs ADD COLUMN max_results INTEGER DEFAULT 5 NOT NULL'))
    candidates = {column['name'] for column in inspect(bind).get_columns('course_candidates')}
    if 'version' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN version INTEGER DEFAULT 1 NOT NULL'))
    if 'source_documents' not in inspect(bind).get_table_names():
        SourceDocument.__table__.create(bind)
    db.commit()


def _add_attendance_status_and_attempts(db):
    bind = db.get_bind()
    records = {column['name'] for column in inspect(bind).get_columns('doctor_records')}
    if 'attendance_status' not in records:
        db.execute(text("ALTER TABLE doctor_records ADD COLUMN attendance_status VARCHAR DEFAULT 'not_recorded' NOT NULL"))
        db.execute(text("UPDATE doctor_records SET attendance_status = 'attended' WHERE attended = 1"))
    jobs = {column['name'] for column in inspect(bind).get_columns('ingestion_jobs')}
    if 'attempt' not in jobs:
        db.execute(text('ALTER TABLE ingestion_jobs ADD COLUMN attempt INTEGER DEFAULT 1 NOT NULL'))
    evidence = {column['name'] for column in inspect(bind).get_columns('field_evidence')}
    if 'source_document_id' not in evidence:
        db.execute(text('ALTER TABLE field_evidence ADD COLUMN source_document_id VARCHAR'))
    db.commit()


def _add_account_coordinates(db):
    existing = {column['name'] for column in inspect(db.get_bind()).get_columns('accounts')}
    if 'latitude' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN latitude FLOAT'))
    if 'longitude' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN longitude FLOAT'))
    if 'location_consent_at' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN location_consent_at FLOAT'))
    db.commit()


def _add_created_at_and_digest_counts(db):
    bind = db.get_bind()
    accounts = {column['name'] for column in inspect(bind).get_columns('accounts')}
    if 'created_at' not in accounts:
        db.execute(text('ALTER TABLE accounts ADD COLUMN created_at FLOAT'))
        db.execute(text('UPDATE accounts SET created_at = 0 WHERE created_at IS NULL'))
    courses = {column['name'] for column in inspect(bind).get_columns('courses')}
    if 'created_at' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN created_at FLOAT'))
        db.execute(text('UPDATE courses SET created_at = updated_at WHERE created_at IS NULL'))
    sends = {column['name'] for column in inspect(bind).get_columns('digest_sends')}
    if 'event_count' not in sends:
        db.execute(text('ALTER TABLE digest_sends ADD COLUMN event_count INTEGER DEFAULT 0 NOT NULL'))
    if 'recorded_points_snapshot' not in sends:
        db.execute(text('ALTER TABLE digest_sends ADD COLUMN recorded_points_snapshot FLOAT DEFAULT 0 NOT NULL'))
    db.commit()


def _add_candidate_resulting_course(db):
    candidates = {column['name'] for column in inspect(db.get_bind()).get_columns('course_candidates')}
    if 'resulting_course_id' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN resulting_course_id VARCHAR'))
    db.commit()


def _add_candidate_schema_version(db):
    candidates = {column['name'] for column in inspect(db.get_bind()).get_columns('course_candidates')}
    if 'schema_version' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN schema_version INTEGER DEFAULT 1 NOT NULL'))
    db.commit()


def _add_publication_status(db):
    courses = {column['name'] for column in inspect(db.get_bind()).get_columns('courses')}
    if 'publication_status' not in courses:
        db.execute(text("ALTER TABLE courses ADD COLUMN publication_status VARCHAR DEFAULT 'published' NOT NULL"))
    if 'cancellation_status' not in courses:
        db.execute(text("ALTER TABLE courses ADD COLUMN cancellation_status VARCHAR DEFAULT 'active' NOT NULL"))
    db.commit()


def _add_session_schedule(db):
    courses = {column['name'] for column in inspect(db.get_bind()).get_columns('courses')}
    if 'end_date' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN end_date VARCHAR'))
    if 'timezone' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN timezone VARCHAR'))
    if 'venue' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN venue VARCHAR'))
    db.commit()


def _add_digest_backoff(db):
    prefs = {column['name'] for column in inspect(db.get_bind()).get_columns('digest_preferences')}
    if 'fail_count' not in prefs:
        db.execute(text('ALTER TABLE digest_preferences ADD COLUMN fail_count INTEGER DEFAULT 0 NOT NULL'))
    if 'next_retry_at' not in prefs:
        db.execute(text('ALTER TABLE digest_preferences ADD COLUMN next_retry_at FLOAT'))
    db.commit()


@asynccontextmanager
async def lifespan(app):
    initialize()
    import asyncio

    stop = asyncio.Event()
    tasks = []

    async def daily_scrape_loop():
        while not stop.is_set():
            try:
                if _paid_scrape_ready():
                    with SessionLocal() as db:
                        result = enqueue_daily(db)
                    if result.get('error'):
                        app_log.warning('daily_scrape error=%s', str(result['error'])[:200])
                    elif result.get('enqueued'):
                        app_log.info(
                            'daily_scrape day=%s enqueued=%s skipped=%s ceiling=%s',
                            result.get('day'),
                            result.get('enqueued'),
                            result.get('skipped'),
                            result.get('ceiling'),
                        )
            except Exception as exc:
                app_log.warning('daily_scrape failed message=%s', str(exc)[:200])
            try:
                await asyncio.wait_for(stop.wait(), timeout=3600)
            except asyncio.TimeoutError:
                continue

    async def digest_loop():
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    run_due_digests(db)
            except Exception as exc:
                app_log.warning('digest_loop failed message=%s', str(exc)[:200])
            try:
                await asyncio.wait_for(stop.wait(), timeout=3600)
            except asyncio.TimeoutError:
                continue

    async def retention_loop():
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    # Expire aged-stuck running leases before purge so null/expired
                    # lease_until rows become interrupted and retention can blank them.
                    expire_jobs(db)
                    purge_expired_source_text(db)
            except Exception as exc:
                app_log.warning('retention_loop failed message=%s', str(exc)[:200])
            try:
                await asyncio.wait_for(stop.wait(), timeout=86400)
            except asyncio.TimeoutError:
                continue

    if os.getenv('DAILY_SCRAPE_ENABLED', 'true').lower() == 'true':
        tasks.append(asyncio.create_task(daily_scrape_loop()))
    if os.getenv('DIGEST_ENABLED', 'true').lower() == 'true':
        tasks.append(asyncio.create_task(digest_loop()))
    tasks.append(asyncio.create_task(retention_loop()))
    yield
    stop.set()
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=2)
        except Exception:
            task.cancel()


app = FastAPI(title='CareCredits', version='0.5.0', lifespan=lifespan)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return envelope(500, 'Request failed.', request)


setup_logs()

DEFAULT_ALLOWED_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:3010,http://127.0.0.1:3010,http://localhost:3020,http://127.0.0.1:3020,http://localhost:3021,http://127.0.0.1:3021,http://localhost:3030,http://127.0.0.1:3030,http://localhost:3040,http://127.0.0.1:3040'


def normalize_origin(value: str | None) -> str:
    """Strip whitespace/trailing slash; opaque browser Origin `null` stays rejected.

    Scheme and host are case-insensitive (RFC 6454), so allowlist comparison casefolds.
    """
    cleaned = (value or '').strip().rstrip('/')
    if not cleaned or cleaned.casefold() == 'null':
        return ''
    return cleaned.casefold()


def origin_allowed(origin: str | None, allowed: list[str] | set[str] | tuple[str, ...]) -> bool:
    normalized = normalize_origin(origin)
    if not normalized:
        return False
    allowlist = {normalize_origin(item) for item in allowed if normalize_origin(item)}
    return normalized in allowlist


@app.middleware('http')
async def request_boundary(request: Request, call_next):
    started = time.perf_counter()
    request.state.request_id = secrets.token_hex(8)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not request.url.path.startswith('/internal/'):
        origins = [item for item in os.getenv('ALLOWED_ORIGINS', DEFAULT_ALLOWED_ORIGINS).split(',') if item.strip()]
        # Strip client header like Origin — padded `1` from proxies must not block real mutations.
        if (request.headers.get('x-care-client') or '').strip() != '1' or not origin_allowed(
            request.headers.get('origin'), origins
        ):
            return envelope(403, 'Request origin not allowed.', request)
    try:
        result = await call_next(request)
    except Exception:
        return envelope(500, 'Request failed.', request)
    result.headers['Cache-Control'] = 'no-store'
    result.headers['X-Content-Type-Options'] = 'nosniff'
    rid = request_id(request)
    result.headers['X-Request-Id'] = rid
    duration_ms = int((time.perf_counter() - started) * 1000)
    request_line(rid, request.method, request.url.path, result.status_code, duration_ms)
    return result


def _display_name(value: str) -> str:
    cleaned = (value or '').strip()
    if len(cleaned) < 2 or len(cleaned) > 100:
        raise ValueError('Enter a display name of 2–100 characters.')
    return cleaned


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(default='Doctor', min_length=1, max_length=120)

    @field_validator('email')
    @classmethod
    def email_check(cls, value):
        value = value.strip().lower()
        if '@' not in value or '.' not in value.split('@')[-1] or any(c.isspace() for c in value):
            raise ValueError('Enter a valid email address')
        return value

    @field_validator('name')
    @classmethod
    def name_check(cls, value):
        return _display_name(value)


class ProfileChange(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(max_length=100)
    state: str = Field(default='', max_length=100)
    bio: str = Field(max_length=1000)
    public_enabled: bool
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @field_validator('name')
    @classmethod
    def name_check(cls, value):
        return _display_name(value)

    @field_validator('city', 'state', 'bio')
    @classmethod
    def trim_text(cls, value):
        return (value or '').strip() if isinstance(value, str) else value

    @field_validator('latitude', 'longitude', mode='before')
    @classmethod
    def coordinates_reject_bool(cls, value):
        # JSON true/false must not become 1.0/0.0 near-me coordinates (parity with Training coords).
        if isinstance(value, bool):
            raise ValueError('Coordinates must be numbers.')
        return value

    @model_validator(mode='after')
    def coordinates_together(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Latitude and longitude must be supplied together.')
        return self


class RecordChange(BaseModel):
    signed_up: bool = False
    signup_status: Literal['not_recorded', 'signed_up', 'cancelled'] | None = None
    attended: bool = False
    attendance_status: Literal['not_recorded', 'attended'] | None = None
    attended_on: date | None = None
    points: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    credit_label: str = Field(default='CPD', min_length=1, max_length=30)
    notes: str = Field(default='', max_length=5000)
    public: bool = False
    version: int = Field(default=0, ge=0)

    @field_validator('points', mode='before')
    @classmethod
    def points_reject_bool(cls, value):
        # JSON true/false must not become 1.0/0.0 recorded CPD (parity with Jev/usage bool reject).
        if isinstance(value, bool):
            raise ValueError('Points must be a number.')
        return value


class NewJob(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    max_results: int = Field(default=5, ge=1, le=5)

    @field_validator('query')
    @classmethod
    def trim(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('Enter a search topic')
        return value.strip()

    @field_validator('max_results', mode='before')
    @classmethod
    def max_results_reject_bool(cls, value):
        # JSON true must not become max_results=1 and invent a paid Search size.
        if isinstance(value, bool):
            raise ValueError('max_results must be an integer from 1 to 5.')
        return value


class TavilySource(BaseModel):
    url: str = Field(max_length=2000)
    title: str = Field(default='', max_length=300)
    snippet: str = Field(default='', max_length=2000)
    extraction_status: str = Field(default='failed', max_length=40)
    verification_status: str = Field(default='unverified', max_length=40)
    retrieved_at: str | None = Field(default=None, max_length=80)


class ExtractionReceipt(BaseModel):
    model_config = {'protected_namespaces': ()}
    model_id: str = Field(min_length=1, max_length=200)
    endpoint_host: str = Field(pattern=r'^[A-Za-z0-9.-]+$', max_length=253)
    completed_at: datetime
    candidate_count: int = Field(ge=1, le=4)


class CompleteJob(BaseModel):
    extractions: list[ExtractionReceipt] = Field(default_factory=list, max_length=5)
    lease_token: str = Field(min_length=1, max_length=200)
    # Dicts so optional `_judgment` survives Training validation (extra=forbid on Training).
    candidates: list[dict] = Field(default_factory=list, max_length=20)
    sources: list[TavilySource] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    status: Literal['succeeded', 'partial', 'failed']
    usage: dict = Field(default_factory=dict)

    @field_validator('candidates')
    @classmethod
    def candidates_are_trainings(cls, rows):
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Each candidate must be an object.')
            payload = {key: value for key, value in row.items() if not str(key).startswith('_')}
            validate_evidence(Training(**payload))
        return rows

    @model_validator(mode='after')
    def terminal_honesty(self):
        token = (self.lease_token or '').strip()
        if not token:
            raise ValueError('lease_token is required.')
        self.lease_token = token
        # failed is a hard terminal; keep evidence via partial when candidates exist.
        if self.status == 'failed' and self.candidates:
            raise ValueError('failed jobs cannot include candidates; use partial.')
        return self


def _complete_candidate_payload(raw: dict) -> tuple[dict, str, str]:
    """Build stored candidate data + status/reason from a complete payload (optional `_judgment`)."""
    payload = {key: value for key, value in raw.items() if not str(key).startswith('_')}
    training = validate_evidence(Training(**payload))
    data = training.model_dump(mode='json')
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
    return data, status, reason


def _merge_candidate_data(existing_data: dict | None, data: dict) -> dict:
    """Refresh fields but keep omitted `_*` metadata (judgment, refresh diff, fixture labels)."""
    merged = dict(data)
    for key, value in (existing_data or {}).items():
        if str(key).startswith('_') and key not in merged:
            merged[key] = value
    return merged


REVIEW_FIELDS = (
    'title', 'provider', 'description', 'start_date', 'end_date', 'timezone', 'venue',
    'city', 'state', 'mode', 'fee', 'currency', 'points', 'credit_label', 'difficulty',
    'prerequisites', 'registration_url',
)


class Review(BaseModel):
    action: Literal['publish', 'reject', 'hold']
    reason: str = Field(default='', max_length=500)
    version: int = Field(default=0, ge=0)
    corrections: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def require_hold_reason(self):
        if self.action in ('hold', 'reject') and len(self.reason.strip()) < 3:
            raise ValueError('Hold and reject require a reason of at least 3 characters.')
        extra = set(self.corrections) - set(REVIEW_FIELDS)
        if extra:
            raise ValueError('Unsupported correction fields.')
        if len(self.corrections) > 20 or len(self.evidence) > 20:
            raise ValueError('Too many corrections.')
        return self


def profile(account):
    return {k: getattr(account, k) for k in ('id', 'email', 'name', 'city', 'state', 'latitude', 'longitude', 'location_consent_at', 'created_at', 'role', 'bio', 'public_enabled', 'public_slug')}


def record_json(record):
    if not record:
        return None
    return {
        k: getattr(record, k)
        for k in (
            'signed_up', 'signup_status', 'signed_up_at', 'attended', 'attendance_status', 'attended_on',
            'points', 'points_origin', 'credit_label', 'notes', 'public', 'version',
        )
    }


def records_for(db, account_id, course_ids=None):
    query = db.query(Record).filter_by(account_id=account_id)
    if course_ids is not None:
        if not course_ids:
            return {}
        query = query.filter(Record.course_id.in_(course_ids))
    return {row.course_id: row for row in query}


def public_source_payload(item):
    data = item.model_dump() if hasattr(item, 'model_dump') else dict(item)
    data['url'] = public_web_url(data.get('url'))
    return data


def job_json(job):
    result = job.result
    if isinstance(result, dict):
        result = dict(result)
        result['sources'] = [public_source_payload(item) for item in result.get('sources') or [] if isinstance(item, dict)]
        # Re-normalize stored usage so older dirty rows cannot invent spend in the UI/logs.
        if 'usage' in result:
            result['usage'] = normalize_job_usage(result.get('usage'))
    return {
        'id': job.id,
        # SDD §10 names the 202 field job_id; keep id for existing clients.
        'job_id': job.id,
        'query': job.query,
        'status': job.status,
        'created_at': job.created_at,
        'max_results': job.max_results,
        'attempt': job.attempt,
        'result': result,
    }


def course_json(course, record=None, field_evidence=None):
    # Full source text and model configuration stay in operator review only.
    data = {k: v for k, v in (course.data or {}).items() if k not in ('source_text', 'model_weights_url', 'model_license_url')}
    for field in FILTER_FIELDS:
        data[field] = getattr(course, field)
    data['source_url'] = public_web_url(data.get('source_url'))
    data['registration_url'] = public_web_url(data.get('registration_url'))
    evidence_rows = []
    if field_evidence is not None:
        evidence_rows = [
            {'field_name': row.field_name, 'excerpt': row.excerpt, 'reviewed_at': row.reviewed_at}
            for row in field_evidence
        ]
    return {
        'id': course.id,
        **data,
        'demo': course.demo,
        'verification_status': course.verification_status or 'unverified',
        'publication_status': course.publication_status or 'published',
        'cancellation_status': course.cancellation_status or 'active',
        'reviewed_at': course.reviewed_at,
        'field_evidence': evidence_rows,
        'record': record_json(record),
    }


def audit(db, account_id, action, entity, changed):
    db.add(Audit(account_id=account_id, action=action, entity_id=entity, changed=changed))


AUDIT_HIDDEN = {'notes', 'password', 'password_hash', 'token', 'secret', 'api_key'}


def audit_json(row: Audit) -> dict:
    changed = row.changed if isinstance(row.changed, dict) else {}
    return {
        'id': row.id,
        'action': row.action,
        'entity_id': row.entity_id,
        'changed': {key: value for key, value in changed.items() if key not in AUDIT_HIDDEN},
        'at': row.created_at,
    }


def paginated_audit(db: Session, query, page: int, page_size: int):
    if page < 1 or not 1 <= page_size <= 50:
        raise HTTPException(422, 'Invalid pagination.')
    total = query.count()
    rows = query.order_by(Audit.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [audit_json(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


class CatalogueLookup(BaseModel):
    candidate: Training


class CatalogueDecide(BaseModel):
    candidate: Training
    matches: list[dict] | None = Field(default=None, max_length=5)


class CatalogueSave(BaseModel):
    candidate: Training
    judgment: dict = Field(default_factory=dict)
    job_id: str | None = None


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/health/live')
def health_live():
    return {'status': 'live'}


@app.get('/health/ready')
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Database is unavailable.')
    return {'status': 'ready', 'database': 'ready'}


@app.get('/api/v1/config')
def config():
    return {
        'demo': os.getenv('DEMO_MODE') == 'true',
        'signup_enabled': os.getenv('ALLOW_SIGNUP') == 'true',
        'oauth_google': google_oauth(),
    }


def _env_int_value(raw):
    try:
        value = int((raw or '').strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _scraper_service_status():
    base = (os.getenv('SCRAPER_HEALTH_URL') or '').strip().rstrip('/')
    if not base:
        return {'status': 'unconfigured', 'reachable': False, 'tavily_configured': False, 'model_ready': False}
    try:
        with urlopen(base + '/health/ready', timeout=2) as response:
            payload = json.loads(response.read() or b'{}')
    except HTTPError as exc:
        raw = exc.read() if exc.code == 503 else b'{}'
        try:
            payload = json.loads(raw or b'{}')
        except (TypeError, ValueError):
            return {'status': 'unreachable', 'reachable': False, 'tavily_configured': False, 'model_ready': False}
    except (TimeoutError, URLError, ValueError, TypeError, UnicodeError):
        return {'status': 'unreachable', 'reachable': False, 'tavily_configured': False, 'model_ready': False}
    if not isinstance(payload, dict):
        return {'status': 'unreachable', 'reachable': False, 'tavily_configured': False, 'model_ready': False}
    return {
        'status': 'ready' if payload.get('status') == 'ready' else 'not_ready',
        'reachable': True,
        'tavily_configured': bool(payload.get('tavily_configured')),
        'model_ready': bool(payload.get('model_ready')),
    }


PAID_SCRAPE_BLOCKED = 'Live discovery stays off until Tavily and the open-weight model are ready.'


def _paid_scrape_ready(scraper=None):
    """Auto daily scrape spends Tavily; require the same live gate as /live enqueue."""
    scraper = scraper if scraper is not None else _scraper_service_status()
    return bool(scraper.get('tavily_configured') and scraper.get('model_ready'))


def _reject_tavily_spend_without_model():
    """Keep curl/API aligned with UI paid_scrape_ready: fail closed until Tavily+model are ready."""
    if not _paid_scrape_ready():
        raise HTTPException(409, PAID_SCRAPE_BLOCKED)


@app.get('/api/v1/admin/services')
def services(user=Depends(operator), db: Session = Depends(get_db)):
    database = 'ready'
    try:
        db.execute(text('SELECT 1'))
    except Exception:
        database = 'unavailable'
    scraper = _scraper_service_status()
    return {
        'backend': 'ready' if database == 'ready' else 'degraded',
        'database': database,
        'database_owner': 'backend',
        'scraper': scraper,
        'paid_scrape_ready': _paid_scrape_ready(scraper),
        'frontend': 'this portal',
    }


@app.get('/api/v1/admin/integrations')
def integrations(user=Depends(operator)):
    weights = env_or_provisional('MODEL_WEIGHTS_URL') or None
    license_url = env_or_provisional('MODEL_LICENSE_URL') or None
    input_chars = _env_int_value(env_or_provisional('MODEL_MAX_INPUT_CHARS'))
    output_tokens = _env_int_value(env_or_provisional('MODEL_MAX_OUTPUT_TOKENS'))
    return {
        'model_id': env_or_provisional('MODEL_ID') or None,
        'model_publisher': env_or_provisional('MODEL_PUBLISHER') or None,
        'model_host': env_or_provisional('MODEL_HOST') or None,
        'model_weights_url': public_web_url(weights),
        'model_license_url': public_web_url(license_url),
        'model_identity_provisional': using_provisional('MODEL_ID'),
        'model_publisher_provisional': using_provisional('MODEL_PUBLISHER'),
        'model_host_provisional': using_provisional('MODEL_HOST'),
        'model_weights_provisional': using_provisional('MODEL_WEIGHTS_URL'),
        'model_license_provisional': using_provisional('MODEL_LICENSE_URL'),
        'model_open_weight_confirmed': os.getenv('MODEL_OPEN_WEIGHT_CONFIRMED') == 'true',
        'model_caps_configured': bool(input_chars and output_tokens),
        'model_caps_provisional': using_provisional('MODEL_MAX_INPUT_CHARS') or using_provisional('MODEL_MAX_OUTPUT_TOKENS'),
        'model_max_input_chars': input_chars,
        'model_max_output_tokens': output_tokens,
        'model_key_configured': bool((os.getenv('MODEL_API_KEY') or '').strip() or os.getenv('MODEL_KEY_CONFIGURED') == 'true'),
        'typesafe_configured': bool(typesafe_key()),
        'scraper_token_configured': bool((os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip()),
        'google_oauth': google_oauth(),
        'catalogue_auto_publish_new': auto_publish_new(),
    }


@app.post('/api/v1/auth/register', status_code=201)
def register(body: Credentials, request: Request, db: Session = Depends(get_db)):
    if os.getenv('ALLOW_SIGNUP') != 'true':
        raise HTTPException(403, 'Registration is disabled. Contact the application operator.')
    throttle(db, 'register:' + client_host(request), 10, 3600)
    account = Account(email=body.email, name=body.name, password_hash=password_hash(body.password))
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This address cannot be registered. Try signing in.')
    return {'message': 'Account created. Please sign in.'}


_DUMMY = password_hash('not-an-account-password')


def _maybe_reseed_demo_login(db, email, password):
    """DEMO_MODE: documented password refreshes fixture accounts even when the hash already matches."""
    if os.getenv('DEMO_MODE') != 'true':
        return
    from seed_demo import DEMO_EMAILS, DEMO_PASSWORD, seed
    if email in DEMO_EMAILS and password == DEMO_PASSWORD:
        seed(db)


def _session_cookie_kwargs():
    return {
        'httponly': True,
        'secure': production_env(),
        'samesite': 'lax',
        'max_age': 28800,
        'path': '/',
    }


def _oauth_state_cookie_kwargs():
    return {
        'httponly': True,
        'secure': production_env(),
        'samesite': 'lax',
        'max_age': 600,
        'path': '/',
    }


def _delete_session_cookie(response: Response, name: str):
    # Match set_cookie flags so production Secure cookies actually clear.
    response.delete_cookie(
        name,
        path='/',
        httponly=True,
        secure=production_env(),
        samesite='lax',
    )


@app.post('/api/v1/auth/login')
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    throttle(db, 'login-ip:' + client_host(request), 30, 300)
    throttle(db, 'login-email:' + body.email, 10, 300)
    # Reseed before the hash check so overwritten role/name/password still accept documented demo login.
    _maybe_reseed_demo_login(db, body.email, body.password)
    account = db.query(Account).filter_by(email=body.email).first()
    valid = password_matches(body.password, account.password_hash if account else _DUMMY)
    if not account or not valid:
        raise HTTPException(401, 'Email or password is incorrect.')
    # Mint a fresh session id and drop any presented cookie session (session fixation / account switch).
    token = issue_session(db, account, request.cookies.get('care_session'))
    response.set_cookie('care_session', token, **_session_cookie_kwargs())
    # Drop leftover Google CSRF state so password login matches successful OAuth callback cleanup.
    _delete_session_cookie(response, 'oauth_state')
    return profile(account)


@app.get('/api/v1/auth/oauth/google')
def google_start(request: Request, response: Response):
    state = secrets.token_urlsafe(24)
    try:
        url = authorize_url(state)
    except OAuthError as exc:
        # Match callback failure paths: drop leftover oauth_state on unconfigured start.
        return _oauth_callback_error(request, exc.status_code, exc.detail)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie('oauth_state', state, **_oauth_state_cookie_kwargs())
    return response


def _oauth_callback_error(request: Request, status_code: int, message: str):
    """Envelope for OAuth callback failures; always drop leftover oauth_state."""
    response = envelope(status_code, message, request)
    _delete_session_cookie(response, 'oauth_state')
    return response


@app.get('/api/v1/auth/oauth/google/callback')
def google_callback(request: Request, db: Session = Depends(get_db), code: str = '', state: str = '', error: str = ''):
    expected = request.cookies.get('oauth_state', '')
    # Strip padded PUBLIC_FRONTEND_BASE (parity with oauth.redirect_uri / digest BFF preference).
    frontend = public_frontend_base()
    if error:
        dest = RedirectResponse(frontend + '/live?oauth=denied', status_code=302)
        _delete_session_cookie(dest, 'oauth_state')
        return dest
    # Match start endpoint: unconfigured Google stays 503 (no KeyError on missing env).
    if not google_oauth():
        return _oauth_callback_error(request, 503, 'Google sign-in is not configured.')
    # Same IP budget as password login so Google callback cannot mint sessions unbounded.
    # Browser navigations must not land on a raw JSON 429 — map throttle to /live like state failures.
    try:
        throttle(db, 'login-ip:' + client_host(request), 30, 300)
    except HTTPException as exc:
        if exc.status_code == 429:
            dest = RedirectResponse(frontend + '/live?oauth=failed', status_code=302)
            _delete_session_cookie(dest, 'oauth_state')
            return dest
        raise
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        # Browser callback — surface on /live like provider/account failures (not a raw JSON page).
        dest = RedirectResponse(frontend + '/live?oauth=failed', status_code=302)
        _delete_session_cookie(dest, 'oauth_state')
        return dest
    try:
        identity = exchange_code(code)
        account = upsert_account(db, identity, os.getenv('ALLOW_SIGNUP') == 'true')
        token = issue_session(db, account, request.cookies.get('care_session'))
    except OAuthError as exc:
        # Browser landed on the callback URL — map provider/account failures to the demo shell.
        if exc.status_code in (401, 403):
            dest = RedirectResponse(frontend + '/live?oauth=failed', status_code=302)
            _delete_session_cookie(dest, 'oauth_state')
            return dest
        return _oauth_callback_error(request, exc.status_code, exc.detail)
    dest = RedirectResponse(frontend + '/live', status_code=302)
    dest.set_cookie('care_session', token, **_session_cookie_kwargs())
    _delete_session_cookie(dest, 'oauth_state')
    return dest


@app.post('/api/v1/auth/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    db.query(LoginSession).filter_by(token_hash=digest(request.cookies.get('care_session', ''))).delete()
    db.commit()
    _delete_session_cookie(response, 'care_session')
    # Drop leftover OAuth CSRF state so the next sign-in cannot reuse a prior Google start cookie.
    _delete_session_cookie(response, 'oauth_state')
    return {'ok': True}


@app.get('/api/v1/me')
def me(user=Depends(current_user)):
    return profile(user)


@app.patch('/api/v1/me')
def change_profile(body: ProfileChange, user=Depends(current_user), db: Session = Depends(get_db)):
    values = body.model_dump()
    user.latitude = values.pop('latitude')
    user.longitude = values.pop('longitude')
    user.location_consent_at = time.time() if user.latitude is not None else None
    for k, v in values.items():
        setattr(user, k, v)
    audit(db, user.id, 'profile_changed', user.id, {'public_enabled': body.public_enabled, 'has_coordinates': user.latitude is not None})
    db.commit()
    return profile(user)


def distance(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, d)))


def _contains(column, value):
    escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return column.ilike(f'%{escaped}%', escape='\\')


@app.get('/api/v1/trainings')
def trainings(
    q: str = '',
    city: str = '',
    state: str = '',
    mode: str = '',
    difficulty: str = '',
    verification_status: str = '',
    publication_status: str = '',
    max_fee: float | None = None,
    max_fee_myr: float | None = None,
    min_points: float | None = None,
    period: Literal['upcoming', 'past', 'all'] = 'upcoming',
    date_from: date | None = None,
    date_to: date | None = None,
    include_unknown: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: int | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    if page < 1 or not 1 <= page_size <= 50 or (latitude is None) != (longitude is None):
        raise HTTPException(422, 'Invalid pagination or location filter.')
    # SDD §10: radius requires coordinates. Do not silently ignore radius_km without a point.
    if radius_km is not None and latitude is None:
        raise HTTPException(422, 'Radius requires coordinates.')
    if latitude is not None:
        # Nearby default 25 km when coords are present but radius omitted (SDD §8).
        effective_radius = 25 if radius_km is None else radius_km
        if effective_radius not in (10, 25, 50, 100):
            raise HTTPException(422, 'Invalid pagination or location filter.')
    else:
        effective_radius = None
    if latitude is not None and (not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise HTTPException(422, 'Invalid coordinates.')
    if max_fee is not None and max_fee_myr is not None and max_fee != max_fee_myr:
        raise HTTPException(422, 'Use a single fee filter.')
    fee_limit = max_fee_myr if max_fee_myr is not None else max_fee
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, 'date_from cannot be after date_to.')
    if any(v is not None and (not math.isfinite(v) or v < 0) for v in (fee_limit, min_points)):
        raise HTTPException(422, 'Invalid price or points filter.')
    if mode and mode not in ('in_person', 'online', 'hybrid'):
        raise HTTPException(422, 'Invalid mode filter.')
    if difficulty and difficulty not in ('beginner', 'intermediate', 'advanced'):
        raise HTTPException(422, 'Invalid difficulty filter.')
    if verification_status and verification_status not in ('unverified', 'source_reviewed'):
        raise HTTPException(422, 'Invalid verification_status filter.')
    # Catalogue search never lists cancelled sessions; allow published filter only (or omit).
    if publication_status and publication_status != 'published':
        raise HTTPException(422, 'Invalid publication_status filter.')
    query = db.query(Course).filter(listed_filter())
    if q:
        like = _contains(Course.title, q) | _contains(Course.provider, q) | _contains(Course.description, q)
        query = query.filter(like)
    # Near-me Hybrid/Any/Online must still list pure online even when city/state filters are set
    # (Discover/workspace often keep profile city alongside Near me). Hard AND city would hide
    # online rows with null/mismatched city and defeat SDD §8 inclusion.
    near_me_includes_online = latitude is not None and mode in ('', 'online', 'hybrid')
    if city:
        city_match = _contains(Course.city, city)
        query = query.filter(or_(city_match, Course.mode == 'online') if near_me_includes_online else city_match)
    if state:
        state_match = _contains(Course.state, state)
        query = query.filter(or_(state_match, Course.mode == 'online') if near_me_includes_online else state_match)
    if mode:
        # Near-me + Hybrid: SDD §8 online/hybrid inclusion. Pure online has no distance but must
        # still appear; an equality filter on hybrid alone made nearby.append(online) dead code.
        if latitude is not None and mode == 'hybrid':
            query = query.filter(Course.mode.in_(('hybrid', 'online')))
        else:
            query = query.filter(Course.mode == mode)
    if difficulty:
        query = query.filter(Course.difficulty == difficulty)
    if verification_status:
        query = query.filter(Course.verification_status == verification_status)
    if publication_status:
        query = query.filter(Course.publication_status == publication_status)
    today_s = today().isoformat()
    if period == 'upcoming':
        query = query.filter(or_(Course.start_date >= today_s, Course.start_date.is_(None)) if include_unknown else Course.start_date >= today_s)
    elif period == 'past':
        query = query.filter(or_(Course.start_date < today_s, Course.start_date.is_(None)) if include_unknown else Course.start_date < today_s)
    if date_from:
        query = query.filter(or_(Course.start_date >= date_from.isoformat(), Course.start_date.is_(None)) if include_unknown else Course.start_date >= date_from.isoformat())
    if date_to:
        query = query.filter(or_(Course.start_date <= date_to.isoformat(), Course.start_date.is_(None)) if include_unknown else Course.start_date <= date_to.isoformat())
    if fee_limit is not None:
        affordable = and_(Course.currency == 'MYR', Course.fee <= fee_limit)
        query = query.filter(or_(Course.fee.is_(None), affordable) if include_unknown else affordable)
    if min_points is not None:
        enough = Course.points >= min_points
        query = query.filter(or_(Course.points.is_(None), enough) if include_unknown else enough)
    if latitude is not None:
        delta_lat = effective_radius / 111
        delta_lon = effective_radius / (111 * max(0.2, abs(math.cos(math.radians(latitude)))))
        nearby = [
            and_(
                Course.latitude.isnot(None),
                Course.latitude.between(latitude - delta_lat, latitude + delta_lat),
                Course.longitude.between(longitude - delta_lon, longitude + delta_lon),
            )
        ]
        if mode in ('', 'online', 'hybrid'):
            nearby.append(Course.mode == 'online')
        if city or state:
            nearby.append(and_(Course.mode != 'online', Course.latitude.is_(None)))
        query = query.filter(or_(*nearby))
    query = query.order_by(Course.start_date.is_(None), Course.start_date, Course.id)
    if latitude is None:
        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        records = records_for(db, user.id, [course.id for course in rows])
        items = [{**course_json(course, records.get(course.id)), 'distance_km': None} for course in rows]
    else:
        scored = []
        for course in query.all():
            distance_km = None
            if course.mode != 'online' and course.latitude is not None and course.longitude is not None:
                distance_km = round(distance(latitude, longitude, course.latitude, course.longitude), 1)
                if distance_km > effective_radius:
                    continue
            scored.append((course, distance_km))
        # Near-me: nearest venue first; unknown distance (city match / online) after measured rows.
        scored.sort(
            key=lambda item: (
                item[1] is None,
                item[1] if item[1] is not None else 0.0,
                item[0].start_date is None,
                item[0].start_date or '',
                item[0].id,
            )
        )
        total = len(scored)
        page_rows = scored[(page - 1) * page_size:page * page_size]
        records = records_for(db, user.id, [course.id for course, _ in page_rows])
        items = [{**course_json(course, records.get(course.id)), 'distance_km': distance_km} for course, distance_km in page_rows]
    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'applied_filters': {
            'q': q or None, 'city': city or None, 'state': state or None, 'mode': mode or None,
            'difficulty': difficulty or None,
            'verification_status': verification_status or None,
            'publication_status': publication_status or None,
            'max_fee_myr': fee_limit, 'min_points': min_points,
            'period': period, 'date_from': date_from.isoformat() if date_from else None,
            'date_to': date_to.isoformat() if date_to else None, 'include_unknown': include_unknown,
            'latitude': latitude, 'longitude': longitude, 'radius_km': effective_radius,
        },
    }


@app.get('/api/v1/trainings/{course_id}')
def detail(course_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, 'Training not found.')
    return course_json(
        course,
        db.query(Record).filter_by(account_id=user.id, course_id=course_id).first(),
        db.query(FieldEvidence).filter_by(course_id=course_id).all(),
    )


@app.put('/api/v1/me/trainings/{course_id}')
def save_record(course_id: str, body: RecordChange, user=Depends(current_user), db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, 'Training not found.')
    # Honour status OR legacy bool (heal not_recorded + attended=true drift on write).
    attendance = 'attended' if (body.attendance_status == 'attended' or body.attended) else 'not_recorded'
    body.attended = attendance == 'attended'
    if body.attended:
        if not body.attended_on or body.attended_on > today():
            raise HTTPException(422, 'Choose a completion date that is not in the future.')
        if course.start_date and body.attended_on < date.fromisoformat(course.start_date):
            raise HTTPException(422, 'Attendance cannot be before the training date.')
    else:
        body.attended_on = None
        body.public = False
    values = body.model_dump(mode='json', exclude={'version'})
    record = db.query(Record).filter_by(account_id=user.id, course_id=course_id).first()
    status = values.pop('signup_status', None)
    if status == 'cancelled':
        pass
    elif status == 'signed_up' or values.get('signed_up'):
        # Heal not_recorded + signed_up=true drift; cancelled already preferred above.
        status = 'signed_up'
    elif status == 'not_recorded' or status is None:
        # Omitted signup_status + signed_up=false clears to not_recorded.
        # Never invent cancel — REG-01 cancel requires an explicit signup_status=cancelled.
        status = 'not_recorded'
    else:
        # Unexpected leftover string (should not pass Literal); heal from bool only.
        status = 'signed_up' if values.get('signed_up') else 'not_recorded'
    prior = (record.signup_status if record else None) or 'not_recorded'
    # Honour legacy signed_up bool drift: treat as signed_up when status stayed not_recorded.
    if prior == 'not_recorded' and record and record.signed_up:
        prior = 'signed_up'
    if status == 'cancelled' and prior not in ('signed_up', 'cancelled'):
        raise HTTPException(422, 'Cancel sign-up only after a recorded provider sign-up.')
    values['signup_status'] = status
    values['signed_up'] = status == 'signed_up'
    values['attendance_status'] = attendance
    values['attended'] = attendance == 'attended'
    if status == 'signed_up':
        values['signed_up_at'] = (record.signed_up_at if record and record.signed_up_at else time.time())
    elif record:
        values['signed_up_at'] = record.signed_up_at
    values['points_origin'] = 'self_reported' if values.get('points') is not None else ''
    if record:
        old = record_json(record)
        comparable = {k: v for k, v in values.items() if k in old}
        if all(old[k] == comparable[k] for k in comparable):
            return old
        changed = db.execute(update(Record).where(Record.id == record.id, Record.version == body.version).values(**values, version=Record.version+1))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'This record changed. Reopen it before saving.')
        db.add(RecordHistory(record_id=record.id, account_id=user.id, changed={k: old[k] for k in ('signup_status', 'attendance_status', 'attended', 'attended_on', 'points', 'credit_label')}))
    else:
        if body.version != 0:
            raise HTTPException(409, 'Record version does not match.')
        record = Record(account_id=user.id, course_id=course_id, **values)
        db.add(record)
    try:
        db.flush()
        audit(db, user.id, 'training_record_changed', record.id, {k:v for k,v in values.items() if k != 'notes'})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'This record changed. Refresh and try again.')
    db.refresh(record)
    return record_json(record)


@app.get('/api/v1/me/trainings')
def my_trainings(
    signup_status: Literal['not_recorded', 'signed_up', 'cancelled'] | None = None,
    attendance_status: Literal['not_recorded', 'attended'] | None = None,
    attended: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    if page < 1 or not 1 <= page_size <= 50:
        raise HTTPException(422, 'Invalid pagination.')
    query = db.query(Record, Course).join(Course, Record.course_id == Course.id).filter(Record.account_id == user.id)
    if signup_status == 'signed_up':
        # Honour legacy signed_up bool; cancelled wins over a drifted true bool (progress / PROG-02).
        query = query.filter(
            Record.signup_status != 'cancelled',
            or_(Record.signup_status == 'signed_up', Record.signed_up.is_(True)),
        )
    elif signup_status == 'cancelled':
        query = query.filter(Record.signup_status == 'cancelled')
    elif signup_status == 'not_recorded':
        query = query.filter(Record.signup_status == 'not_recorded', Record.signed_up.is_(False))
    elif signup_status:
        query = query.filter(Record.signup_status == signup_status)
    if attendance_status == 'attended':
        # Same OR as legacy attended= / progress / public so UI filters do not miss bool drift.
        query = query.filter(or_(Record.attendance_status == 'attended', Record.attended.is_(True)))
    elif attendance_status == 'not_recorded':
        query = query.filter(Record.attendance_status != 'attended', Record.attended.is_(False))
    elif attendance_status:
        query = query.filter(Record.attendance_status == attendance_status)
    elif attended is not None:
        # Honour attendance_status when the legacy attended bool drifts (same as progress / public).
        if attended:
            query = query.filter(or_(Record.attendance_status == 'attended', Record.attended.is_(True)))
        else:
            query = query.filter(Record.attendance_status != 'attended', Record.attended.is_(False))
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        'items': [course_json(c, r) for r, c in rows],
        'total': total,
        'page': page,
        'page_size': page_size,
    }


@app.get('/api/v1/me/progress')
def progress(year: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    # year=0 must not falsy-coerce into the current calendar year (match certificates/CSV).
    year = today().year if year is None else year
    if not 1900 <= year <= 2200:
        raise HTTPException(422, 'Invalid year.')
    # Same attended_on / start_date year rules as digest and certificates (no drift residual).
    return progress_snapshot(db, user.id, year)


@app.get('/api/v1/me/trainings/{course_id}/history')
def record_history(course_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter_by(account_id=user.id, course_id=course_id).first()
    if not record:
        return {'items': []}
    rows = db.query(RecordHistory).filter_by(record_id=record.id, account_id=user.id).order_by(RecordHistory.created_at.desc()).limit(20).all()
    return {'items': [{'at': row.created_at, **(row.changed or {})} for row in rows]}


@app.get('/api/v1/me/suggestions')
def me_suggestions(user=Depends(current_user), db: Session = Depends(get_db)):
    return suggestions_for(db, user)


class DigestChange(BaseModel):
    opted_in: bool
    # Omit to keep the stored cadence; defaulting to 14 would wipe a custom NTF-01 preference.
    cadence_days: int | None = Field(default=None, ge=7, le=60)


@app.get('/api/v1/me/digest')
def get_digest(user=Depends(current_user), db: Session = Depends(get_db)):
    return preference_json(ensure_preference(db, user.id))


@app.patch('/api/v1/me/digest')
def patch_digest(body: DigestChange, user=Depends(current_user), db: Session = Depends(get_db)):
    pref = ensure_preference(db, user.id)
    was_out = not pref.opted_in
    pref.opted_in = body.opted_in
    if body.cadence_days is not None:
        pref.cadence_days = body.cadence_days
    if body.opted_in:
        pref.unsubscribed_at = None
        # Fresh opt-in after unsubscribe/backoff must not stay blocked by a prior fail timer.
        if was_out:
            pref.fail_count = 0
            pref.next_retry_at = None
    else:
        pref.unsubscribed_at = time.time()
    db.commit()
    return preference_json(pref)


class CertificateIssue(BaseModel):
    # None = calendar year in Asia/Kuala_Lumpur; 0 must not coerce via `or`.
    year: int | None = Field(default=None, ge=1900, le=2200)


@app.post('/api/v1/me/certificates', status_code=201)
def create_certificate(body: CertificateIssue, user=Depends(current_user), db: Session = Depends(get_db)):
    year = today().year if body.year is None else body.year
    try:
        row = issue_certificate(db, user, year)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return certificate_json(row)


@app.get('/api/v1/me/certificates/{certificate_id}')
def download_certificate(certificate_id: str, format: str = 'pdf', user=Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(AffiliationCertificate, certificate_id)
    if not row or row.account_id != user.id:
        raise HTTPException(404, 'Certificate not found.')
    kind = (format or 'pdf').strip().lower()
    if kind not in ('pdf', 'html'):
        raise HTTPException(422, 'Certificate format must be pdf or html.')
    if kind == 'html':
        return Response(
            certificate_html(user, row),
            media_type='text/html; charset=utf-8',
            headers={'Content-Disposition': f'inline; filename="carecredits-{row.year}-{row.id[:8]}.html"'},
        )
    # PDF downloads use attachment so Content-Disposition filename is honoured by browsers.
    return Response(
        certificate_pdf(user, row),
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="carecredits-{row.year}-{row.id[:8]}.pdf"'},
    )


UNSUBSCRIBE_OK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Unsubscribed — CareCredits</title>
<style>
  body { font-family: Georgia, serif; color: #10233f; max-width: 36rem; margin: 3rem auto; padding: 0 1.25rem; }
  h1 { font-size: 1.6rem; }
  p { line-height: 1.5; color: #3d536b; }
</style>
</head>
<body>
  <h1>You are unsubscribed</h1>
  <p>CareCredits will not send another biweekly digest unless you opt in again from your signed-in portal.</p>
  <p>This page does not require a CareCredits account. No catalogue search or Tavily call ran.</p>
</body>
</html>"""

UNSUBSCRIBE_INVALID_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Unsubscribe link invalid — CareCredits</title>
<style>
  body { font-family: Georgia, serif; color: #10233f; max-width: 36rem; margin: 3rem auto; padding: 0 1.25rem; }
  h1 { font-size: 1.6rem; }
  p { line-height: 1.5; color: #3d536b; }
</style>
</head>
<body>
  <h1>Unsubscribe link invalid</h1>
  <p>This CareCredits digest unsubscribe link is missing, blank, or no longer valid.</p>
  <p>If you still receive digests, open a newer email or sign in and turn off the biweekly digest. No catalogue search or Tavily call ran.</p>
</body>
</html>"""


def _wants_unsubscribe_json(request: Request) -> bool:
    accept = (request.headers.get('accept') or '').lower()
    return 'application/json' in accept and 'text/html' not in accept


@app.get('/api/v1/digest/unsubscribe')
def digest_unsubscribe(request: Request, token: str | None = None, db: Session = Depends(get_db)):
    # Blank/whitespace tokens are invalid (email clients sometimes strip or truncate).
    cleaned = (token or '').strip()
    if not cleaned:
        if _wants_unsubscribe_json(request):
            return envelope(404, 'Unsubscribe link is invalid or expired.', request)
        return HTMLResponse(UNSUBSCRIBE_INVALID_HTML, status_code=404)
    pref = db.query(DigestPreference).filter_by(unsubscribe_token=cleaned).first()
    if not pref:
        if _wants_unsubscribe_json(request):
            return envelope(404, 'Unsubscribe link is invalid or expired.', request)
        return HTMLResponse(UNSUBSCRIBE_INVALID_HTML, status_code=404)
    pref.opted_in = False
    pref.unsubscribed_at = time.time()
    db.commit()
    payload = {'opted_in': False, 'message': 'You are unsubscribed from CareCredits digests.'}
    if _wants_unsubscribe_json(request):
        return payload
    return HTMLResponse(UNSUBSCRIBE_OK_HTML)


@app.post('/api/v1/admin/digests/run')
def admin_run_digests(user=Depends(operator), db: Session = Depends(get_db)):
    # Beyond job throttle: bound manual digest sends so a busy operator UI cannot hammer mail.
    throttle(db, 'digests:' + user.id, 20, 300)
    return run_due_digests(db)


@app.get('/api/v1/me/export/{kind}')
def export(
    kind: Literal['csv', 'eml'],
    year: int | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    if year is not None and not 1900 <= year <= 2200:
        raise HTTPException(422, 'Invalid year.')
    rows = db.query(Record, Course).join(Course, Record.course_id == Course.id).filter(Record.account_id == user.id).all()
    if year is not None:
        year_key = str(year)
        scoped = []
        for r, c in rows:
            attended = getattr(r, 'attendance_status', None) == 'attended' or bool(r.attended)
            # Match PROG-01: attended rows use attended_on year; open/other rows use course start_date year.
            if attended:
                if r.attended_on and str(r.attended_on).startswith(year_key):
                    scoped.append((r, c))
            elif (c.start_date or '').startswith(year_key):
                scoped.append((r, c))
        rows = scoped
    def cell(value):
        value = str(value or '')
        # Strip BOM / zero-width / Unicode spaces / line-breaks before formula detection (CSV/Excel injection).
        visible = value.lstrip(
            ' \t\r\n\x0b\x0c\ufeff\u200b\u200c\u200d\u2060'
            '\u00a0\u1680\u180e\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
            '\u2028\u2029\u202f\u205f\u3000'
            # Bidi marks / embeddings / overrides / isolates can hide =+@- from Excel.
            '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
            # Soft hyphen / CGJ / Arabic letter mark also hide formula starters in some Excel builds.
            '\u00ad\u034f\u061c'
        )
        # ASCII formula starters plus fullwidth / Unicode minus forms Excel may still treat as formulas.
        starters = (
            '=', '+', '-', '@',
            '\uff1d', '\uff0b', '\uff0d', '\uff20',
            '\u2212',  # MINUS SIGN
            '\ufe63',  # SMALL HYPHEN-MINUS
        )
        return "'" + value if visible[:1] in starters else value
    suffix = f'-{year}' if year is not None else ''
    if kind == 'csv':
        stream = io.StringIO()
        writer = csv.writer(stream)
        # Owner export is complete for tracking fields; private notes stay out of CSV and the public profile.
        writer.writerow([
            'Training', 'Provider', 'Session date', 'Signed up', 'Signup status', 'Attended',
            'Attendance status', 'Completed on', 'Recorded points', 'Credit label', 'Source', 'Evidence status',
        ])
        for r, c in rows:
            signup_status = getattr(r, 'signup_status', None) or ('signed_up' if r.signed_up else 'not_recorded')
            attendance_status = getattr(r, 'attendance_status', None) or ('attended' if r.attended else 'not_recorded')
            attended = attendance_status == 'attended' or bool(r.attended)
            # Match progress_snapshot / PROG-02: cancelled must not look open if signed_up bool drifted.
            signed_up = signup_status != 'cancelled' and (signup_status == 'signed_up' or bool(r.signed_up))
            writer.writerow([
                cell(c.title),
                cell(c.provider),
                cell(c.start_date or ''),
                signed_up,
                cell(signup_status),
                attended,
                cell(attendance_status),
                cell(r.attended_on or ''),
                r.points if r.points is not None else '',
                cell(r.credit_label),
                cell(public_web_url((c.data or {}).get('source_url')) or ''),
                'Self-reported',
            ])
        content, mime = stream.getvalue(), 'text/csv; charset=utf-8'
    else:
        message = EmailMessage()
        subject_year = f' ({year})' if year is not None else ''
        message['Subject'] = f'My CPD training record{subject_year}'
        message['X-Unsent'] = '1'
        lines = ['My personal training record (self-reported, not independently verified):', '']
        if year is not None:
            lines.append(f'Year filter: {year} (attended_on for attended rows; session start_date otherwise).')
            lines.append('')
        attended_lines = []
        for r, c in rows:
            if getattr(r, 'attendance_status', None) == 'attended' or r.attended:
                attended_lines.append(
                    f"{c.title} | {r.attended_on} | {r.points if r.points is not None else 'Not recorded'} {r.credit_label}"
                )
        if attended_lines:
            lines.extend(attended_lines)
        else:
            # Honest empty body: header-only CSV already discloses emptiness; EML must say so explicitly.
            if year is not None:
                lines.append(f'No attended records for {year}.')
            else:
                lines.append('No attended records yet.')
        message.set_content('\n'.join(lines))
        content, mime = message.as_bytes(), 'message/rfc822'
    return Response(
        content,
        media_type=mime,
        headers={'Content-Disposition': f'attachment; filename="carecredits-record{suffix}.{kind}"'},
    )


@app.get('/api/v1/public/{slug}')
def public_profile(slug: str, db: Session = Depends(get_db)):
    account = db.query(Account).filter_by(public_slug=slug, public_enabled=True).first()
    if not account:
        raise HTTPException(404, 'This training profile is private or unavailable.')
    items = []
    for r, c in db.query(Record, Course).join(Course, Record.course_id == Course.id).filter(Record.account_id == account.id, Record.public.is_(True)):
        # Honour attendance_status when the legacy attended bool drifts (same as progress / UI).
        if not (getattr(r, 'attendance_status', None) == 'attended' or r.attended):
            continue
        raw = (c.data or {}).get('source_url')
        items.append({'title': c.title, 'provider': c.provider, 'attended_on': r.attended_on, 'source_url': public_web_url(raw), 'demo': c.demo})
    return {'name': account.name, 'bio': account.bio, 'items': items, 'evidence_status': 'Self-reported training history; not independently verified.'}


@app.get('/api/v1/me/audit')
def my_audit(page: int = 1, page_size: int = 20, user=Depends(current_user), db: Session = Depends(get_db)):
    return paginated_audit(db, db.query(Audit).filter_by(account_id=user.id), page, page_size)


@app.get('/api/v1/admin/audit')
def admin_audit(page: int = 1, page_size: int = 20, user=Depends(operator), db: Session = Depends(get_db)):
    return paginated_audit(db, db.query(Audit), page, page_size)


@app.post('/api/v1/admin/ingestion-jobs', status_code=202)
def create_job(body: NewJob, request: Request, user=Depends(operator), db: Session = Depends(get_db)):
    _reject_tavily_spend_without_model()
    key = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(key) <= 100:
        raise HTTPException(422, 'Supply an Idempotency-Key of 8–100 characters.')
    request_key = digest(user.id + ':' + key)
    existing = db.query(Job).filter_by(request_key=request_key).first()
    if existing:
        if existing.query != body.query or existing.max_results != body.max_results:
            raise HTTPException(409, 'That request key belongs to another query.')
        return job_json(existing)
    throttle(db, 'jobs:' + user.id, 10, 3600)
    job = Job(account_id=user.id, request_key=request_key, query=body.query, max_results=body.max_results)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Request already received; refresh jobs.')
    return job_json(job)


def expire_jobs(db):
    # Clear lease fields so interrupted rows cannot look leased; retry/force requeue from a clean idle state.
    # Keep any usage/sources already reported on the running job — do not invent spend, but do not wipe it.
    # Conditional UPDATE so a concurrent heartbeat that extends lease_until wins the race.
    # Fail closed: null/missing lease_until or started_at on running is aged-stuck
    # (null lease_until never matches lease_until < now; null started_at cannot complete).
    now = time.time()
    # Match heartbeat/complete: started_at older than 5 minutes is aged-stuck even if lease_until is future.
    lease_stale = or_(
        Job.lease_until.is_(None),
        Job.lease_until < now,
        Job.started_at.is_(None),
        Job.started_at < now - 300,
    )
    expired = db.query(Job).filter(Job.status == 'running', lease_stale).all()
    changed = False
    for job in expired:
        prior = job.result if isinstance(job.result, dict) else {}
        warnings = [str(item)[:500] for item in (prior.get('warnings') or []) if item]
        warning = 'Worker lease expired. Retry explicitly to avoid hidden API spending.'
        if warning not in warnings:
            warnings.append(warning)
        result = {
            'warnings': warnings[-30:],
            'usage': normalize_job_usage(prior.get('usage')),
            'sources': [item for item in (prior.get('sources') or []) if isinstance(item, dict)][:5],
        }
        if 'candidate_count' in prior:
            result['candidate_count'] = prior.get('candidate_count')
        updated = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == 'running', lease_stale)
            .values(
                status='interrupted',
                lease_token=None,
                lease_until=None,
                started_at=None,
                result=result,
            )
        )
        if updated.rowcount == 1:
            changed = True
    # Defense in depth after terminal/interrupted lease-clear: idle rows must not look leased
    # (manual test fixtures, older code paths, or a lost race leaving lease fields behind).
    leftover = db.execute(
        update(Job)
        .where(
            Job.status.in_(('queued', 'succeeded', 'partial', 'failed', 'interrupted')),
            or_(
                Job.lease_token.isnot(None),
                Job.lease_until.isnot(None),
                Job.started_at.isnot(None),
            ),
        )
        .values(lease_token=None, lease_until=None, started_at=None)
    )
    if leftover.rowcount:
        changed = True
    if changed:
        db.commit()
        db.expire_all()
    elif expired:
        # Heartbeat extended every candidate row after the SELECT; drop the stale read.
        db.rollback()


@app.get('/api/v1/admin/ingestion-jobs')
def jobs(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    user=Depends(operator),
    db: Session = Depends(get_db),
):
    expire_jobs(db)
    if page < 1 or not 1 <= page_size <= 50:
        raise HTTPException(422, 'Invalid pagination.')
    allowed = {'queued', 'running', 'succeeded', 'partial', 'failed', 'interrupted'}
    raw_status = (status or '').strip()
    statuses: list[str] | None
    if not raw_status:
        statuses = None
    else:
        parts = [part.strip() for part in raw_status.split(',') if part.strip()]
        if not parts or any(part not in allowed for part in parts):
            raise HTTPException(422, 'Invalid job status filter.')
        statuses = [name for name in (
            'queued', 'running', 'succeeded', 'partial', 'failed', 'interrupted'
        ) if name in parts]
    query = db.query(Job).order_by(Job.created_at.desc())
    if statuses:
        query = query.filter(Job.status.in_(statuses))
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        'items': [job_json(j) for j in rows],
        'total': total,
        'page': page,
        'page_size': page_size,
        'status': statuses,
    }


@app.get('/api/v1/admin/ingestion-jobs/{job_id}')
def job_detail(job_id: str, user=Depends(operator), db: Session = Depends(get_db)):
    expire_jobs(db)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    return job_json(job)


@app.post('/api/v1/admin/ingestion-jobs/{job_id}/retry', status_code=202)
def retry_job(job_id: str, user=Depends(operator), db: Session = Depends(get_db)):
    _reject_tavily_spend_without_model()
    expire_jobs(db)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    # Clear stale result so queued/running UI cannot show prior attempt usage as current.
    # Refresh created_at so retention treats the retry as fresh work (parity with force requeue).
    changed = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == 'interrupted')
        .values(
            status='queued',
            lease_token=None,
            lease_until=None,
            started_at=None,
            attempt=Job.attempt + 1,
            result=None,
            created_at=time.time(),
        )
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Only interrupted jobs can be retried.')
    db.commit()
    return job_json(db.get(Job, job_id))


@app.get('/api/v1/admin/candidates')
def candidates(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    job_id: str | None = None,
    user=Depends(operator),
    db: Session = Depends(get_db),
):
    if page < 1 or not 1 <= page_size <= 50:
        raise HTTPException(422, 'Invalid pagination.')
    allowed = {'pending', 'held', 'rejected'}
    raw_status = (status or '').strip()
    if not raw_status or raw_status == 'awaiting':
        statuses = ['pending', 'held']
    else:
        parts = [part.strip() for part in raw_status.split(',') if part.strip()]
        if not parts or any(part not in allowed for part in parts):
            raise HTTPException(422, 'Invalid candidate status filter.')
        # Stable order for applied-filter honesty in the response.
        statuses = [name for name in ('pending', 'held', 'rejected') if name in parts]
    job_filter = (job_id or '').strip() or None
    query = db.query(Candidate).filter(Candidate.status.in_(statuses)).order_by(Candidate.id)
    if job_filter:
        query = query.filter(Candidate.job_id == job_filter)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        'items': [{
            'id': c.id,
            'job_id': c.job_id,
            'data': c.data,
            'status': c.status,
            'reason': c.review_reason or '',
            'version': c.version,
            'schema_version': c.schema_version,
            'resulting_course_id': c.resulting_course_id,
        } for c in rows],
        'total': total,
        'page': page,
        'page_size': page_size,
        'status': statuses,
        'job_id': job_filter,
    }


@app.post('/api/v1/admin/candidates/{candidate_id}/review')
def review(candidate_id: str, body: Review, user=Depends(operator), db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter_by(id=candidate_id).with_for_update().first()
    if not candidate:
        raise HTTPException(404, 'Candidate not found.')
    # published is terminal; rejected can return to hold/publish (hold → reject → hold → publish).
    if candidate.status == 'published':
        if body.action == 'publish':
            return {
                'status': candidate.status,
                'reason': candidate.review_reason or '',
                'version': candidate.version,
                'resulting_course_id': candidate.resulting_course_id,
            }
        raise HTTPException(409, 'This candidate is already published. Refresh.')
    if candidate.status not in ('pending', 'held', 'rejected'):
        raise HTTPException(409, 'This candidate cannot be reviewed. Refresh.')
    # Exact version only — default 0 must not bypass optimistic locking after hold/publish races.
    if body.version != candidate.version:
        raise HTTPException(409, 'This candidate changed. Refresh before reviewing.')
    reason = body.reason.strip()
    now = time.time()
    if body.action == 'publish':
        data = dict(candidate.data or {})
        if body.corrections:
            source_text = str(data.get('source_text') or '')
            # Whitespace-only source_text cannot support verbatim excerpts (CandidateCard parity).
            if not source_text.strip():
                raise HTTPException(422, 'Source text is missing. Reject, hold, or ingest a better source.')
            evidence = dict(data.get('evidence') or {})
            for field, value in body.corrections.items():
                excerpt = str(body.evidence.get(field) or '').strip()
                if not excerpt or excerpt not in source_text:
                    raise HTTPException(422, 'Correction for ' + field + ' needs a verbatim source excerpt.')
                if field in ('fee', 'points') and value not in ('', None):
                    try:
                        data[field] = float(value)
                    except ValueError:
                        raise HTTPException(422, 'Correction for ' + field + ' must be a number.')
                else:
                    data[field] = value
                evidence[field] = excerpt
            data['evidence'] = evidence
            candidate.data = data
        try:
            training = validate_evidence(Training(**training_payload(data)))
        except ValueError:
            raise HTTPException(422, 'Source evidence is incomplete. Reject or ingest a better source.')
        payload = training.model_dump(mode='json')
        is_fixture = bool((candidate.data or {}).get('_fixture'))
        course = resolve_review_course(db, candidate)
        next_key = source_key(payload)
        if course:
            # Keep identity aligned after title/date drift so the next exact lookup cannot fork a duplicate.
            # Cancelled collisions re-list that session (parity with unmatched publish); live collisions 409.
            if next_key != course.source_key:
                conflict = exact_course(db, next_key)
                if conflict and conflict.id != course.id:
                    # Honour either cancel column (listed_filter parity) so cancellation_status
                    # drift cannot 409 a re-list while the row stays hidden from doctors.
                    if (conflict.publication_status or '') == 'cancelled' or (
                        conflict.cancellation_status or ''
                    ) == 'cancelled':
                        course = conflict
                    else:
                        raise HTTPException(409, 'Another catalogue session already uses this identity. Refresh.')
            fill_course(course, payload, demo=True if is_fixture else None)
            if next_key != course.source_key:
                course.source_key = next_key
        else:
            conflict = exact_course(db, next_key)
            if conflict:
                # Re-list a cancelled session that matches the corrected identity; 409 only for live rows.
                if (conflict.publication_status or '') == 'cancelled' or (
                    conflict.cancellation_status or ''
                ) == 'cancelled':
                    course = conflict
                    fill_course(course, payload, demo=True if is_fixture else None)
                else:
                    raise HTTPException(409, 'Another catalogue session already uses this identity. Refresh.')
            else:
                course = fill_course(Course(source_key=next_key), payload, demo=is_fixture)
                db.add(course)
        db.flush()
        candidate.resulting_course_id = course.id
        # Align live candidate identity with the published course so later source_key upserts stay on this row.
        # Preserve DEMO fixture keys (demo-candidate-*) so DEMO_MODE reseed can still find published fixtures.
        if not is_fixture and not str(candidate.source_key or '').startswith('demo-candidate-'):
            candidate.source_key = next_key
        # Operator publish re-lists a previously cancelled session (cancel only hides from search).
        course.publication_status = 'published'
        course.cancellation_status = 'active'
        course.verification_status = 'source_reviewed'
        course.reviewed_by = user.id
        course.reviewed_at = now
        db.query(FieldEvidence).filter_by(course_id=course.id).delete()
        source_url = str(payload.get('source_url') or '').split('#')[0]
        source = db.query(SourceDocument).filter_by(canonical_url=source_url).order_by(SourceDocument.retrieved_at.desc()).first() if source_url else None
        for field, excerpt in (payload.get('evidence') or {}).items():
            text = str(excerpt or '').strip()
            if not text:
                continue
            db.add(FieldEvidence(
                course_id=course.id,
                candidate_id=candidate.id,
                source_document_id=source.id if source else None,
                field_name=field,
                excerpt=text[:2000],
                reviewed_by=user.id,
                reviewed_at=now,
            ))
        candidate.status = 'published'
    elif body.action == 'hold':
        candidate.status = 'held'
    else:
        candidate.status = 'rejected'
    candidate.review_reason = reason
    candidate.reviewed_by = user.id
    candidate.reviewed_at = now
    candidate.version = candidate.version + 1
    audit(db, user.id, 'candidate_' + candidate.status, candidate.id, {'reason': reason})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Another catalogue session already uses this identity. Refresh.')
    return {'status': candidate.status, 'reason': candidate.review_reason, 'version': candidate.version, 'resulting_course_id': candidate.resulting_course_id}


@app.post('/api/v1/admin/trainings/{course_id}/cancel')
def cancel_training(course_id: str, user=Depends(operator), db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, 'Training not found.')
    course.publication_status = 'cancelled'
    course.cancellation_status = 'cancelled'
    course.updated_at = time.time()
    audit(db, user.id, 'course_cancelled', course.id, {'publication_status': 'cancelled'})
    db.commit()
    return course_json(course)


CLAIM_REASON_HEADER = 'X-Care-Claim-Reason'


def _claim_idle(reason: str) -> Response:
    """204 with an honest idle reason for worker logs/UI (not_ready | empty | lost_lease)."""
    return Response(status_code=204, headers={CLAIM_REASON_HEADER: reason})


@app.post('/internal/v1/jobs/claim', dependencies=[Depends(worker)])
def claim(db: Session = Depends(get_db)):
    # Expire dead leases even when paid scrape is not ready so crashed jobs do not stay
    # running until the daily retention tick (worker still polls claim every few seconds).
    expire_jobs(db)
    scraper = _scraper_service_status()
    if not _paid_scrape_ready(scraper):
        return _claim_idle('not_ready')
    # One worker process is the default; conditional claims also prevent double ownership.
    # Keep walking the queued list when a race loses the first row so leftover jobs
    # are not skipped until the next poll.
    lost_races = 0
    while True:
        job = db.query(Job).filter_by(status='queued').order_by(Job.created_at).first()
        if not job:
            return _claim_idle('lost_lease' if lost_races else 'empty')
        token = secrets.token_urlsafe(24)
        result = db.execute(update(Job).where(Job.id == job.id, Job.status == 'queued').values(status='running', lease_token=token, lease_until=time.time()+120, started_at=time.time()))
        db.commit()
        if result.rowcount == 1:
            return {'id': job.id, 'query': job.query, 'max_results': job.max_results, 'lease_token': token}
        lost_races += 1
        db.expire_all()


@app.post('/internal/v1/jobs/{job_id}/heartbeat', dependencies=[Depends(worker)])
def heartbeat(job_id: str, body: dict, db: Session = Depends(get_db)):
    now = time.time()
    result = db.execute(update(Job).where(Job.id == job_id, Job.status == 'running', Job.lease_token == body.get('lease_token'), Job.lease_until >= now, Job.started_at >= now-300).values(lease_until=now+120))
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(409, 'Job lease is no longer active.')
    return {'ok': True}


@app.post('/internal/v1/jobs/{job_id}/complete', dependencies=[Depends(worker)])
def complete(job_id: str, body: CompleteJob, db: Session = Depends(get_db)):
    job = db.query(Job).filter_by(id=job_id).with_for_update().first()
    if not job:
        raise HTTPException(409, 'Job lease does not match.')
    # Terminal first so idempotent retries stay 200 after lease fields are cleared.
    if job.status in ('succeeded', 'partial', 'failed'):
        if job.lease_token is not None or job.lease_until is not None or job.started_at is not None:
            job.lease_token = None
            job.lease_until = None
            job.started_at = None
            db.commit()
        return {'status': job.status}
    job_token = job.lease_token or ''
    # Reject blank tokens so a corrupted running row without a lease cannot be completed.
    if not job_token or not secrets.compare_digest(job_token.encode(), body.lease_token.encode()):
        raise HTTPException(409, 'Job lease does not match.')
    # Null lease_until/started_at is aged-stuck — same fail-closed posture as expire_jobs.
    if (
        job.status != 'running'
        or job.lease_until is None
        or job.lease_until < time.time()
        or job.started_at is None
        or job.started_at < time.time() - 300
    ):
        raise HTTPException(409, 'Job lease expired.')
    # Only running → succeeded|partial|failed (Literal); interrupted/queued need explicit retry.
    # Clear lease fields on terminal complete (parity with expire_jobs interrupted cleanup).
    changed = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == 'running')
        .values(status=body.status, lease_token=None, lease_until=None, started_at=None)
    )
    if changed.rowcount != 1:
        db.rollback()
        return {'status': db.get(Job, job_id).status}
    job.lease_token = None
    job.lease_until = None
    job.started_at = None
    seen = set()
    for raw in body.candidates:
        try:
            data, status, reason = _complete_candidate_payload(raw)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        key = source_key(data)
        if key in seen:
            continue
        seen.add(key)
        same_job = db.query(Candidate).filter_by(job_id=job.id, source_key=key).order_by(Candidate.id).first()
        # Prefer an already-open review card. UUID ids are not insertion-ordered, so do not
        # pick a rejected row as "existing" just because its id sorts first.
        open_row = (
            db.query(Candidate)
            .filter_by(source_key=key)
            .filter(Candidate.status.in_(['pending', 'held']))
            .order_by(Candidate.id)
            .first()
        )
        rejected_row = (
            None
            if open_row
            else (
                db.query(Candidate)
                .filter_by(source_key=key, status='rejected')
                .order_by(Candidate.id)
                .first()
            )
        )
        # Prefer one open identity. Do not reopen this job's rejected into a second pending
        # when another open row already owns the source_key (CAT-02 no-fork).
        if open_row and same_job and same_job.status == 'rejected' and same_job.id != open_row.id:
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
            # Bare refresh preserves prior uncertain/exists hold and operator holds.
            # Explicit decision=new reopens to pending.
            if incoming_decision == 'new':
                target_status, target_reason = 'pending', ''
            elif status == 'held' or decision in ('uncertain', 'exists'):
                target_status = 'held'
                if status == 'held':
                    target_reason = reason
                elif decision == 'uncertain':
                    target_reason = (
                        'Jev uncertain: ' + str(merged_judgment.get('warning') or 'needs operator review')
                    )[:500]
                elif decision == 'exists':
                    target_reason = 'Jev marked exists; review refresh before overwriting published fields.'
                else:
                    target_reason = target.review_reason or ''
            elif not incoming_judgment and target.status == 'held':
                # Connect-down / bare complete must not clear an operator hold on a `new` row.
                target_status = 'held'
                target_reason = target.review_reason or ''
            else:
                target_status, target_reason = 'pending', ''
            # Exists soft-refresh must keep published-vs-proposed honesty when fields change.
            matched_id = target.resulting_course_id or target.data.get('_matched_course_id')
            if target_status == 'held' and decision == 'exists' and matched_id:
                matched = db.get(Course, matched_id)
                if matched:
                    bare = {k: v for k, v in target.data.items() if not str(k).startswith('_')}
                    target.data = {
                        **target.data,
                        '_matched_course_id': matched.id,
                        '_refresh_diff': refresh_diff(matched, bare),
                    }
                    target.resulting_course_id = matched.id
            # Always bump so CandidateCard remounts on evidence refresh (pending→pending too).
            reopen_review_candidate(target, status=target_status, reason=target_reason)
            continue
        matched = exact_course(db, key)
        if matched:
            # Connect-down / bare complete still holds a refresh against the published row.
            judgment = data.get('_judgment') if isinstance(data.get('_judgment'), dict) else {}
            judgment = {
                **judgment,
                'decision': 'exists',
                'matched_session_id': matched.id,
            }
            bare = {k: v for k, v in data.items() if not str(k).startswith('_')}
            link_existing(
                db,
                job.account_id,
                Training(**bare),
                matched,
                judgment,
                job.id,
            )
            continue
        db.add(
            Candidate(
                job_id=job.id,
                source_key=key,
                data=data,
                status=status,
                schema_version=CANDIDATE_SCHEMA_VERSION,
                review_reason=reason,
            )
        )
    job.status = body.status
    sources = [public_source_payload(item) for item in body.sources]
    usage = normalize_job_usage(body.usage)
    job.result = {
        'extractions': [item.model_dump(mode='json') for item in body.extractions],
        'candidate_count': len(seen),
        'warnings': [w[:500] for w in body.warnings],
        'usage': usage,
        'sources': sources,
    }
    for item in sources:
        url = (item.get('url') or '').split('#')[0]
        if not url:
            continue
        digest_key = digest(url + '|' + (item.get('snippet') or '')[:500])
        if not db.query(SourceDocument).filter_by(canonical_url=url, content_hash=digest_key).first():
            # Prefer scraper retrieval time when present so DISC-03 / retention match job sources.
            # Missing/unparseable stamps fail closed as already-expired (0), never invent "now".
            stamp = retrieved_stamp(item)
            db.add(SourceDocument(
                job_id=job.id,
                canonical_url=url,
                content_hash=digest_key,
                retrieved_at=stamp if stamp is not None else 0,
                extraction_status=item.get('extraction_status') or 'failed',
                title=(item.get('title') or '')[:300],
                snippet=(item.get('snippet') or '')[:2000],
            ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'A review candidate for this session already exists. Refresh.')
    job_line(
        job.id,
        job.status,
        len(seen),
        len(body.sources),
        usage,
        len(body.warnings),
    )
    return {'status': job.status}


@app.get('/internal/v1/catalogue/connect', dependencies=[Depends(worker)])
def catalogue_connect(db: Session = Depends(get_db)):
    try:
        db.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Catalogue database is unavailable.')
    return {
        'status': 'connected',
        'database': 'ready',
        'typesafe_configured': bool(typesafe_key()),
        'local_day': local_today(),
    }


@app.post('/internal/v1/catalogue/lookup', dependencies=[Depends(worker)])
def catalogue_lookup(body: CatalogueLookup, db: Session = Depends(get_db)):
    try:
        training = validate_evidence(body.candidate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    data = training.model_dump(mode='json')
    key = source_key(data)
    exact = exact_course(db, key)
    neighbours = [] if exact else near_neighbours(db, data)
    return {
        'source_key': key,
        'exact': course_public(exact) if exact else None,
        'matches': [course_public(row) for row in neighbours],
    }


@app.post('/internal/v1/catalogue/decide', dependencies=[Depends(worker)])
def catalogue_decide(body: CatalogueDecide, db: Session = Depends(get_db)):
    try:
        training = validate_evidence(body.candidate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    data = training.model_dump(mode='json')
    key = source_key(data)
    exact = exact_course(db, key)
    if exact:
        judgment = {
            'decision': 'exists',
            'confidence': 1.0,
            'probabilities': {'exists': 1.0, 'new': 0.0, 'uncertain': 0.0},
            'matched_session_id': exact.id,
            'warning': None,
            'source_key': key,
        }
    else:
        matches = body.matches if body.matches is not None else [course_public(row) for row in near_neighbours(db, data)]
        try:
            judgment = decide_existence(data, matches)
        except JevError as exc:
            raise HTTPException(exc.status_code, exc.detail)
        judgment['source_key'] = key
    pending = open_review_candidate(db, key)
    if pending:
        pending.data = {**(pending.data or {}), '_judgment': judgment}
        if pending.status == 'rejected':
            # Keep decide from leaving a rejected row while a later save expects an open review card.
            decision = judgment.get('decision')
            new_status = 'held' if decision in ('uncertain', 'exists') else 'pending'
            reason = (
                ('Jev uncertain: ' + str(judgment.get('warning') or 'needs operator review'))[:500]
                if new_status == 'held' and decision == 'uncertain'
                else (
                    'Jev marked exists; review refresh before overwriting published fields.'
                    if new_status == 'held'
                    else ''
                )
            )
            reopen_review_candidate(pending, status=new_status, reason=reason)
        db.commit()
        judgment['candidate_id'] = pending.id
    return judgment


@app.post('/internal/v1/catalogue/save', dependencies=[Depends(worker)])
def catalogue_save(body: CatalogueSave, db: Session = Depends(get_db)):
    try:
        training = validate_evidence(body.candidate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    judgment = body.judgment or {}
    decision = judgment.get('decision')
    job = db.get(Job, body.job_id) if body.job_id else None
    if body.job_id and not job:
        raise HTTPException(404, 'Job not found.')
    account_id = job.account_id if job else None
    if not account_id:
        op = db.query(Account).filter_by(role='operator').order_by(Account.email).first()
        if not op:
            raise HTTPException(503, 'No operator account available to own catalogue saves.')
        account_id = op.id
    data = training.model_dump(mode='json')
    key = source_key(data)
    if decision == 'exists':
        matched_id = judgment.get('matched_session_id')
        course = db.get(Course, matched_id) if matched_id else exact_course(db, key)
        if not course:
            raise HTTPException(404, 'Matched catalogue session was not found.')
        try:
            candidate = link_existing(db, account_id, training, course, judgment, body.job_id)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'A refresh candidate for this session already exists. Refresh.')
        return {'status': 'exists', 'candidate_id': candidate.id, 'course_id': course.id, 'decision': 'exists'}
    if decision == 'uncertain':
        try:
            candidate = save_new_candidate(db, account_id, training, judgment, body.job_id)
            db.commit()
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {'status': 'held', 'candidate_id': candidate.id, 'decision': 'uncertain'}
    if decision != 'new':
        raise HTTPException(422, 'Judgment decision must be exists, new, or uncertain.')
    # Clamp NaN/inf so junk confidence cannot bypass the auto-publish floor.
    confidence = unit_interval(judgment.get('confidence'), 0.0)
    # Auto-publish is only for high-confidence new rows; low confidence stays pending for review.
    if not auto_publish_new() or confidence < confidence_floor():
        try:
            candidate = save_new_candidate(db, account_id, training, judgment, body.job_id)
            db.commit()
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'Event already exists in the catalogue.')
        return {'status': 'pending', 'candidate_id': candidate.id, 'decision': 'new'}
    try:
        candidate, course = publish_new_event(db, account_id, training, judgment, body.job_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Event already exists in the catalogue.')
    return {'status': 'published', 'candidate_id': candidate.id, 'course_id': course.id, 'decision': 'new'}


@app.get('/api/v1/admin/scrape-topics')
def scrape_topics(user=Depends(operator)):
    try:
        topics = load_topics()
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    return {
        'topics': topics,
        'ceiling': daily_ceiling(),
        'day': local_today(),
        'source': 'config/scrape_topics.json',
    }


@app.post('/api/v1/admin/daily-scrape', status_code=202)
def trigger_daily_scrape(force: bool = False, user=Depends(operator), db: Session = Depends(get_db)):
    _reject_tavily_spend_without_model()
    result = enqueue_daily(db, force=force)
    if result.get('error'):
        raise HTTPException(503, result['error'])
    return result
