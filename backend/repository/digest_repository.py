"""Database operations for progress totals, digest scheduling and delivery history."""
from sqlalchemy import func
from models import Account, Course, DigestPreference, DigestSend, Record
from repository.model_helpers import listed_filter


def records_for_account(db, account_id):
    return db.query(Record).filter_by(account_id=account_id).all()


def courses_by_ids(db, ids):
    return db.query(Course).filter(Course.id.in_(ids)).all() if ids else []


def upcoming_courses(db, today, city, limit):
    query = db.query(Course).filter(listed_filter(), Course.start_date != None, Course.start_date >= today)
    rows = []
    if city:
        rows = query.filter(func.lower(func.trim(Course.city)) == city).order_by(Course.start_date).limit(limit).all()
    return rows or query.order_by(Course.start_date).limit(limit).all()


def preference_for(db, account_id):
    return db.get(DigestPreference, account_id)


def preference_by_token(db, token):
    return db.query(DigestPreference).filter_by(unsubscribe_token=token).first()


def create_preference(db, **values):
    pref = DigestPreference(**values)
    db.add(pref)
    save(db, pref)
    return pref


def opted_in_preferences(db):
    return db.query(DigestPreference).filter_by(opted_in=True).all()


def add_send(db, **values):
    row = DigestSend(**values)
    db.add(row)
    return row


def account_by_id(db, account_id):
    return db.get(Account, account_id)


def save(db, row=None):
    db.commit()
    if row is not None:
        db.refresh(row)
