"""Profile split/backfill invariants, using disposable in-memory SQLite only."""
import sys
import unittest
from pathlib import Path
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Base
from database.profile_migration import upgrade_profile_schema
from models.account import Account
from models.profile import AccountProfile
from models.session import LoginSession
from models.schema_version import SchemaVersion


class ProfileMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        # Start from the existing deployed schema: no account_profiles table.
        Base.metadata.create_all(self.engine, tables=[table for table in Base.metadata.sorted_tables if table.name != 'account_profiles'])
        self.db = Session(self.engine)
        self.db.execute(Account.__table__.insert().values(
            id='existing-account', email='doctor@example.org', password_hash='unchanged-hash',
            name='Original doctor', city='Kuala Lumpur', state='Selangor',
            latitude=3.14, longitude=101.69, location_consent_at=1000,
            public_enabled=True, public_slug='preserved-public-link', bio='Existing biography',
            role='operator', identity_issuer='issuer', identity_subject='subject', created_at=1234,
        ))
        self.db.add(LoginSession(token_hash='preserved-token', account_id='existing-account', expires_at=9999999999))
        self.db.add(SchemaVersion(version=17))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def migrate(self):
        upgrade_profile_schema(self.db)
        self.db.commit()

    def test_additive_backfill_preserves_identity_sessions_and_public_links(self):
        self.assertNotIn('account_profiles', inspect(self.engine).get_table_names())
        self.migrate()
        account = self.db.get(Account, 'existing-account')
        self.assertEqual(account.password_hash, 'unchanged-hash')
        self.assertEqual(account.role, 'operator')
        self.assertEqual(account.identity_subject, 'subject')
        self.assertEqual(account.public_slug, 'preserved-public-link')
        self.assertEqual(account.profile_record.account_id, account.id)
        self.assertEqual(account.profile_record.name, 'Original doctor')
        self.assertEqual(account.profile_record.latitude, 3.14)
        self.assertEqual(self.db.get(LoginSession, 'preserved-token').account_id, account.id)
        self.assertIn('name', {column['name'] for column in inspect(self.engine).get_columns('accounts')})
        # Migration helper never silently stamps a version or commits for its caller.
        self.assertEqual([row.version for row in self.db.query(SchemaVersion)], [17])

    def test_backfill_is_idempotent_and_profile_is_canonical_in_python_and_sql(self):
        self.migrate()
        profile = self.db.get(AccountProfile, 'existing-account')
        profile.name = 'Canonical new name'
        profile.latitude = None
        self.db.commit()
        self.migrate()
        account = self.db.get(Account, 'existing-account')
        self.assertEqual(account.name, 'Canonical new name')
        self.assertIsNone(account.latitude)
        self.assertEqual(self.db.query(Account).filter(Account.name == 'Canonical new name').count(), 1)
        self.assertEqual(self.db.query(Account).filter(Account.latitude.is_(None)).count(), 1)
        self.assertEqual(self.db.query(AccountProfile).count(), 1)
        self.assertEqual(self.db.query(Account).join(AccountProfile).filter(Account.name == 'Canonical new name').count(), 1)
        self.assertEqual(self.db.execute(select(Account.__table__.c.name)).scalar_one(), 'Original doctor')

    def test_compatibility_writes_preserve_rollback_columns_and_new_profile_creation(self):
        self.migrate()
        account = self.db.get(Account, 'existing-account')
        account.name = 'Changed by API'
        account.city = 'Penang'
        account.latitude = None
        self.db.add(Account(id='new-account', email='new@example.org', password_hash='hash', name='New doctor'))
        self.db.commit()
        self.assertEqual(account.profile_record.city, 'Penang')
        legacy = self.db.execute(select(Account.__table__.c.name).where(Account.__table__.c.id == account.id)).scalar_one()
        self.assertEqual(legacy, 'Changed by API')
        self.assertEqual(self.db.get(AccountProfile, 'new-account').name, 'New doctor')
        self.assertEqual(self.db.get(AccountProfile, 'new-account').city, 'Kuala Lumpur')

    def test_profiles_load_in_one_query(self):
        self.migrate()
        for i in range(5):
            self.db.add(Account(email=f'doc{i}@example.org', password_hash='hash', name=f'Doctor {i}'))
        self.db.commit(); self.db.expunge_all()
        statements = []
        def count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.engine, 'before_cursor_execute', count)
        try:
            names = [account.name for account in self.db.query(Account).all()]
        finally:
            event.remove(self.engine, 'before_cursor_execute', count)
        self.assertEqual(len(names), 6)
        self.assertEqual(len(statements), 1)

    def test_mapping_modules_do_not_export_persistence_services(self):
        from models import schema
        import portal_models
        self.assertFalse(hasattr(schema, 'fill_course'))
        self.assertFalse(hasattr(schema, 'purge_expired_source_text'))
        self.assertIs(portal_models.Account, schema.Account)
        self.assertTrue(callable(portal_models.fill_course))

    def test_explicit_migration_stamps_v19_and_backfills_v17(self):
        from database.migrations import migrate_schema
        migrate_schema(self.db)
        self.assertEqual(max(row.version for row in self.db.query(SchemaVersion)), 19)
        self.assertEqual(self.db.get(AccountProfile, 'existing-account').name, 'Original doctor')
        migrate_schema(self.db)
        self.assertEqual(self.db.query(AccountProfile).count(), 1)

    def test_unversioned_existing_accounts_are_backfilled_before_stamping(self):
        from database.migrations import migrate_schema
        self.db.query(SchemaVersion).delete(); self.db.commit()
        migrate_schema(self.db)
        self.assertEqual(max(row.version for row in self.db.query(SchemaVersion)), 19)
        self.assertEqual(self.db.get(AccountProfile, 'existing-account').public_slug, 'preserved-public-link')


class LegacyBooleanMigrationTests(unittest.TestCase):
    def test_status_backfill_preserves_true_and_false_legacy_values(self):
        from sqlalchemy import text
        from database.migrations import _add_signup_status, _add_attendance_status_and_attempts
        engine = create_engine('sqlite:///:memory:')
        try:
            with Session(engine) as db:
                db.execute(text('CREATE TABLE doctor_records (id VARCHAR PRIMARY KEY, signed_up BOOLEAN NOT NULL, attended BOOLEAN NOT NULL)'))
                db.execute(text('CREATE TABLE ingestion_jobs (id VARCHAR PRIMARY KEY)'))
                db.execute(text('CREATE TABLE field_evidence (id VARCHAR PRIMARY KEY)'))
                db.execute(text("INSERT INTO doctor_records VALUES ('yes', true, true), ('no', false, false)"))
                db.commit()
                _add_signup_status(db)
                _add_attendance_status_and_attempts(db)
                records = {row.id: (row.signup_status, row.attendance_status) for row in db.execute(text('SELECT * FROM doctor_records'))}
                self.assertEqual(records['yes'], ('signed_up', 'attended'))
                self.assertEqual(records['no'], ('not_recorded', 'not_recorded'))
                # Rerunning an explicit upgrade must not overwrite later user choices.
                db.execute(text("UPDATE doctor_records SET signup_status='cancelled' WHERE id='yes'")); db.commit()
                _add_signup_status(db)
                self.assertEqual(db.execute(text("SELECT signup_status FROM doctor_records WHERE id='yes'")).scalar(), 'cancelled')
        finally:
            engine.dispose()
