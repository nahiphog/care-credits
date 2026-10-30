"""At-most-once automated dispatch per account/cadence; uncertain sends need review."""
from sqlalchemy.exc import IntegrityError
from models import DigestDispatch

def rollback(db):
    db.rollback()

def refresh(db, pref):
    db.refresh(pref)


def claim(db, key, account_id, now):
    try:
        db.add(DigestDispatch(key=key, account_id=account_id, state='sending', attempted_at=now))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def finish(db, key, state, now):
    row = db.get(DigestDispatch, key)
    row.state = state
    row.finished_at = now
    db.commit()
