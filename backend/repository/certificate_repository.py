"""Certificate storage and immutable audit-snapshot lookup."""
from models import AffiliationCertificate, Audit


def get(db, certificate_id):
    return db.get(AffiliationCertificate, certificate_id)


def snapshot_event(db, row):
    return db.query(Audit).filter_by(action='certificate_issued', entity_id=row.id, account_id=row.account_id).order_by(Audit.created_at).first()


def page_for(db, account_id, year, page, page_size):
    query = db.query(AffiliationCertificate).filter_by(account_id=account_id)
    if year is not None:
        query = query.filter_by(year=year)
    total = query.count()
    rows = query.order_by(AffiliationCertificate.issued_at.desc(), AffiliationCertificate.id).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def create(db, **values):
    row = AffiliationCertificate(**values)
    db.add(row)
    db.flush()
    return row


def save_snapshot(db, row, snapshot):
    db.add(Audit(account_id=row.account_id, action='certificate_issued', entity_id=row.id,
                 changed={'certificate_snapshot': snapshot}))
    db.commit()
    db.refresh(row)
