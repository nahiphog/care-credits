"""Read-only deployment readiness inspection."""
from sqlalchemy import text, inspect
from database import Base
from models import SchemaVersion, SCHEMA_VERSION
from domain.errors import DomainError

def readiness(db):
    try:
        db.execute(text('SELECT 1'))
        current = max((row.version for row in db.query(SchemaVersion).all()), default=0)
        if current != SCHEMA_VERSION:
            raise RuntimeError('Schema version mismatch')
        columns = inspect(db.get_bind()).get_multi_columns(filter_names=[t.name for t in Base.metadata.sorted_tables])
        for table in Base.metadata.sorted_tables:
            if not set(table.c.keys()).issubset({c['name'] for c in columns.get((None, table.name), [])}):
                raise RuntimeError('Schema columns missing')
    except Exception:
        raise DomainError(503, 'Database or application schema is not ready.')
    return {'status': 'ready', 'database': 'ready'}
