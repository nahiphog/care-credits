"""Explicit additive schema upgrades. Never called by serverless request startup."""
from sqlalchemy import text, inspect
from models import SchemaVersion, SCHEMA_VERSION, Course, Account, Record, Candidate, Job, DigestPreference, SourceDocument
from repository.model_helpers import fill_course

def migrate_schema(db):
    versions = db.query(SchemaVersion).all()
    current = max((v.version for v in versions), default=0)
    if current == 0:
        from .profile_migration import upgrade_profile_schema
        upgrade_profile_schema(db)
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
    if current == 17:
        from database.profile_migration import upgrade_profile_schema
        upgrade_profile_schema(db)
        db.add(SchemaVersion(version=18))
        db.commit()
        current = 18
    if current == 18:
        from models.operations import PasswordReset, MaintenanceRun, DigestDispatch
        for model in (PasswordReset, MaintenanceRun, DigestDispatch):
            model.__table__.create(db.get_bind(), checkfirst=True)
        db.add(SchemaVersion(version=19))
        db.commit()
        current = 19
    if current != SCHEMA_VERSION:
        raise RuntimeError('Unsupported portal schema. Apply the matching migration.')


def _add_course_filter_columns(db):
    existing = {column['name'] for column in inspect(db.connection()).get_columns('courses')}
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
    existing = {column['name'] for column in inspect(db.connection()).get_columns('course_candidates')}
    if 'review_reason' not in existing:
        db.execute(text("ALTER TABLE course_candidates ADD COLUMN review_reason VARCHAR DEFAULT '' NOT NULL"))
    db.commit()


def _add_signup_status(db):
    existing = {column['name'] for column in inspect(db.connection()).get_columns('doctor_records')}
    if 'signup_status' not in existing:
        db.execute(text("ALTER TABLE doctor_records ADD COLUMN signup_status VARCHAR DEFAULT 'not_recorded' NOT NULL"))
        db.execute(text("UPDATE doctor_records SET signup_status = 'signed_up' WHERE signed_up = true"))
    db.commit()


def _add_account_state(db):
    existing = {column['name'] for column in inspect(db.connection()).get_columns('accounts')}
    if 'state' not in existing:
        db.execute(text("ALTER TABLE accounts ADD COLUMN state VARCHAR DEFAULT '' NOT NULL"))
    db.commit()


def _add_account_identity(db):
    existing = {column['name'] for column in inspect(db.connection()).get_columns('accounts')}
    if 'identity_issuer' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN identity_issuer VARCHAR'))
    if 'identity_subject' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN identity_subject VARCHAR'))
    db.commit()


def _add_review_and_record_origin(db):
    courses = {column['name'] for column in inspect(db.connection()).get_columns('courses')}
    if 'verification_status' not in courses:
        db.execute(text("ALTER TABLE courses ADD COLUMN verification_status VARCHAR DEFAULT 'unverified' NOT NULL"))
    if 'reviewed_by' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN reviewed_by VARCHAR'))
    if 'reviewed_at' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN reviewed_at FLOAT'))
    records = {column['name'] for column in inspect(db.connection()).get_columns('doctor_records')}
    if 'signed_up_at' not in records:
        db.execute(text('ALTER TABLE doctor_records ADD COLUMN signed_up_at FLOAT'))
    if 'points_origin' not in records:
        db.execute(text("ALTER TABLE doctor_records ADD COLUMN points_origin VARCHAR DEFAULT '' NOT NULL"))
    candidates = {column['name'] for column in inspect(db.connection()).get_columns('course_candidates')}
    if 'reviewed_at' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN reviewed_at FLOAT'))
    db.commit()


def _add_source_documents_and_job_limits(db):
    bind = db.connection()
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
    bind = db.connection()
    records = {column['name'] for column in inspect(bind).get_columns('doctor_records')}
    if 'attendance_status' not in records:
        db.execute(text("ALTER TABLE doctor_records ADD COLUMN attendance_status VARCHAR DEFAULT 'not_recorded' NOT NULL"))
        db.execute(text("UPDATE doctor_records SET attendance_status = 'attended' WHERE attended = true"))
    jobs = {column['name'] for column in inspect(bind).get_columns('ingestion_jobs')}
    if 'attempt' not in jobs:
        db.execute(text('ALTER TABLE ingestion_jobs ADD COLUMN attempt INTEGER DEFAULT 1 NOT NULL'))
    evidence = {column['name'] for column in inspect(bind).get_columns('field_evidence')}
    if 'source_document_id' not in evidence:
        db.execute(text('ALTER TABLE field_evidence ADD COLUMN source_document_id VARCHAR'))
    db.commit()


def _add_account_coordinates(db):
    existing = {column['name'] for column in inspect(db.connection()).get_columns('accounts')}
    if 'latitude' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN latitude FLOAT'))
    if 'longitude' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN longitude FLOAT'))
    if 'location_consent_at' not in existing:
        db.execute(text('ALTER TABLE accounts ADD COLUMN location_consent_at FLOAT'))
    db.commit()


def _add_created_at_and_digest_counts(db):
    bind = db.connection()
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
    candidates = {column['name'] for column in inspect(db.connection()).get_columns('course_candidates')}
    if 'resulting_course_id' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN resulting_course_id VARCHAR'))
    db.commit()


def _add_candidate_schema_version(db):
    candidates = {column['name'] for column in inspect(db.connection()).get_columns('course_candidates')}
    if 'schema_version' not in candidates:
        db.execute(text('ALTER TABLE course_candidates ADD COLUMN schema_version INTEGER DEFAULT 1 NOT NULL'))
    db.commit()


def _add_publication_status(db):
    courses = {column['name'] for column in inspect(db.connection()).get_columns('courses')}
    if 'publication_status' not in courses:
        db.execute(text("ALTER TABLE courses ADD COLUMN publication_status VARCHAR DEFAULT 'published' NOT NULL"))
    if 'cancellation_status' not in courses:
        db.execute(text("ALTER TABLE courses ADD COLUMN cancellation_status VARCHAR DEFAULT 'active' NOT NULL"))
    db.commit()


def _add_session_schedule(db):
    courses = {column['name'] for column in inspect(db.connection()).get_columns('courses')}
    if 'end_date' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN end_date VARCHAR'))
    if 'timezone' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN timezone VARCHAR'))
    if 'venue' not in courses:
        db.execute(text('ALTER TABLE courses ADD COLUMN venue VARCHAR'))
    db.commit()


def _add_digest_backoff(db):
    prefs = {column['name'] for column in inspect(db.connection()).get_columns('digest_preferences')}
    if 'fail_count' not in prefs:
        db.execute(text('ALTER TABLE digest_preferences ADD COLUMN fail_count INTEGER DEFAULT 0 NOT NULL'))
    if 'next_retry_at' not in prefs:
        db.execute(text('ALTER TABLE digest_preferences ADD COLUMN next_retry_at FLOAT'))
    db.commit()
