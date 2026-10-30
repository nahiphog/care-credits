"""Audit persistence and bounded queries; no HTTP or serialization."""
from models import Audit

def audit(db, account_id, action, entity, changed):
    db.add(Audit(account_id=account_id, action=action, entity_id=entity, changed=changed))

def paginated(db, page, page_size, account_id=None):
    query = db.query(Audit)
    if account_id is not None:
        query = query.filter_by(account_id=account_id)
    total = query.count()
    rows = query.order_by(Audit.created_at.desc(), Audit.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return rows, total
