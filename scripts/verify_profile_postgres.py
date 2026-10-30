"""Verify schema18 against a disposable PostgreSQL schema, leaving live tables intact.

Uses the existing direct connection. Copies accounts/sessions only within the same
database; does not export private rows or provider credentials. Always drops the
randomly named test schema, even after a failed check.
"""
import os
import sys
import uuid
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]


def main():
    settings = dotenv_values(ROOT / '.env.vercel.production')
    url = settings.get('DATABASE_URL_UNPOOLED') or settings.get('POSTGRES_URL_NON_POOLING')
    if not url or '-pooler.' in url:
        raise RuntimeError('A direct PostgreSQL connection is required.')
    os.environ['DATABASE_URL'] = url
    from database import Base
    from models import Account, AccountProfile, LoginSession, SchemaVersion
    from database.migrations import migrate_schema
    schema = 'carecredits_verify_' + uuid.uuid4().hex
    admin = create_engine(url)
    isolated = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for table in ('accounts', 'login_sessions'):
                connection.execute(text(f'CREATE TABLE "{schema}"."{table}" (LIKE public."{table}" INCLUDING ALL)'))
                connection.execute(text(f'INSERT INTO "{schema}"."{table}" SELECT * FROM public."{table}"'))
        isolated = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
        Base.metadata.create_all(isolated)
        Session = sessionmaker(bind=isolated)
        with Session() as db:
            assert db.execute(text('SELECT current_schema()')).scalar() == schema
            before = list(db.execute(text('SELECT * FROM accounts ORDER BY id')))
            sessions = list(db.execute(text('SELECT * FROM login_sessions ORDER BY token_hash')))
            db.add(SchemaVersion(version=17)); db.commit()
            migrate_schema(db)
            assert list(db.execute(text('SELECT * FROM accounts ORDER BY id'))) == before
            assert list(db.execute(text('SELECT * FROM login_sessions ORDER BY token_hash'))) == sessions
            assert db.query(AccountProfile).count() == len(before)
            migrate_schema(db)
            assert db.query(AccountProfile).count() == len(before)
            account = db.query(Account).first()
            if account:
                original = account.name
                account.name = 'Migration verification'
                db.commit(); db.expire_all()
                assert db.get(Account, account.id).profile_record.name == 'Migration verification'
                assert db.execute(text('SELECT name FROM accounts WHERE id=:id'), {'id': account.id}).scalar() == 'Migration verification'
                account.name = original; db.commit()
                db.query(Account).filter(Account.id == account.id).with_for_update(of=Account).first()
                db.rollback()
            print('PostgreSQL migration PASS: legacy rows and sessions preserved, profiles backfilled, rerun idempotent, canonical writes and locking verified.')
    finally:
        if isolated:
            isolated.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


if __name__ == '__main__':
    main()
