"""Operational receipts and bounded retention cleanup."""
from models import MaintenanceRun, PasswordReset, LoginSession, DigestDispatch
from sqlalchemy import or_, and_


def digest_attention(db, now):
    return db.query(DigestDispatch).filter(or_(DigestDispatch.state == 'uncertain',
        and_(DigestDispatch.state == 'sending', DigestDispatch.attempted_at < now - 300))).count()

def rollback(db):
    db.rollback()


def start(db, now):
    row = MaintenanceRun(started_at=now, status='running', counts={})
    db.add(row)
    db.commit()
    return row.id


def finish(db, run_id, now, counts, error_type=None):
    row = db.get(MaintenanceRun, run_id)
    row.finished_at = now
    row.status = 'failed' if error_type else 'completed'
    row.counts = counts
    row.error_type = error_type
    db.commit()


def cleanup(db, now):
    counts = {}
    for model, key in [(PasswordReset, 'expired_reset_tokens'), (LoginSession, 'expired_sessions')]:
        ids = [row[0] for row in db.query(model.token_hash).filter(model.expires_at < now).limit(500)]
        counts[key] = db.query(model).filter(model.token_hash.in_(ids)).delete(synchronize_session=False) if ids else 0
    old = [row[0] for row in db.query(MaintenanceRun.id).filter(MaintenanceRun.started_at < now - 30 * 86400).limit(500)]
    counts['expired_receipts'] = db.query(MaintenanceRun).filter(MaintenanceRun.id.in_(old)).delete(synchronize_session=False) if old else 0
    db.commit()
    return counts


def recent(db):
    rows = db.query(MaintenanceRun).order_by(MaintenanceRun.started_at.desc()).limit(20).all()
    return [{'id': r.id, 'started_at': r.started_at, 'finished_at': r.finished_at,
             'status': r.status, 'counts': r.counts, 'error_type': r.error_type} for r in rows]
