"""Translate storage conflicts at the repository boundary."""
from sqlalchemy.exc import IntegrityError
from domain.persistence import PersistenceConflict


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        raise PersistenceConflict('A conflicting record already exists.') from exc


def flush(db):
    try:
        db.flush()
    except IntegrityError as exc:
        raise PersistenceConflict('A conflicting record already exists.') from exc
