"""Logical restore drill in a disposable schema; never modifies public rows.

Copies production rows inside the same database, preserves table constraints,
compares row fingerprints without exporting private data, then tests schema19.
This is not proof of Neon's point-in-time recovery retention or an offsite backup.
"""
import os
import sys
import uuid
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]


def main():
    env = dotenv_values(ROOT / '.env.vercel.production')
    url = env.get('DATABASE_URL_UNPOOLED') or env.get('POSTGRES_URL_NON_POOLING')
    if not url or '-pooler.' in url:
        raise RuntimeError('Direct database connection required')
    os.environ['DATABASE_URL'] = url
    from database import Base
    from models import SCHEMA_VERSION, SchemaVersion
    from database.migrations import migrate_schema
    schema = 'carecredits_restore_' + uuid.uuid4().hex
    engine = create_engine(url)
    restored = None
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        restored = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
        Base.metadata.create_all(restored)
        count = 0
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            existing = set(inspect(conn).get_table_names(schema='public'))
            for table in Base.metadata.sorted_tables:
                if table.name not in existing:
                    continue
                # Identifiers come only from the checked-in ORM registry and generated schema.
                columns = ','.join('"' + c.name + '"' for c in table.columns)
                conn.execute(text(f'INSERT INTO "{schema}"."{table.name}" ({columns}) SELECT {columns} FROM public."{table.name}"'))
                def fingerprint(namespace):
                    return conn.execute(text(f'SELECT count(*), md5(coalesce(string_agg(md5(row_to_json(t)::text),\'\' ORDER BY md5(row_to_json(t)::text)),\'\')) FROM "{namespace}"."{table.name}" t')).one()
                assert fingerprint('public') == fingerprint(schema), table.name
                count += 1
        with Session(restored) as db:
            migrate_schema(db)
            migrate_schema(db)
            assert max(row.version for row in db.query(SchemaVersion)) == SCHEMA_VERSION
        print(f'PASS: {count} tables restored with matching row fingerprints; migration idempotent; no live rows changed.')
    finally:
        if restored:
            restored.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


if __name__ == '__main__':
    main()
