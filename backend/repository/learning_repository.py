"""Persistence queries for an account's learning records."""
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from models import Course, Record, RecordHistory


def course_by_id(db, course_id):
    return db.get(Course, course_id)


def record_for(db, account_id, course_id):
    return db.query(Record).filter_by(account_id=account_id, course_id=course_id).first()


def records_for(db, account_id, course_ids=None):
    query = db.query(Record).filter_by(account_id=account_id)
    if course_ids is not None:
        if not course_ids:
            return {}
        query = query.filter(Record.course_id.in_(course_ids))
    return {row.course_id: row for row in query}


def record_course_pairs(db, account_id, public_only=False):
    query = db.query(Record, Course).join(Course, Record.course_id == Course.id).filter(Record.account_id == account_id)
    if public_only:
        query = query.filter(Record.public.is_(True))
    return query.all()


def page_records(db, account_id, signup_status=None, attendance_status=None, attended=None, page=1, page_size=20):
    query = db.query(Record, Course).join(Course, Record.course_id == Course.id).filter(Record.account_id == account_id)
    if signup_status == 'signed_up':
        query = query.filter(Record.signup_status != 'cancelled', or_(Record.signup_status == 'signed_up', Record.signed_up.is_(True)))
    elif signup_status == 'cancelled':
        query = query.filter(Record.signup_status == 'cancelled')
    elif signup_status == 'not_recorded':
        query = query.filter(Record.signup_status == 'not_recorded', Record.signed_up.is_(False))
    elif signup_status:
        query = query.filter(Record.signup_status == signup_status)
    if attendance_status == 'attended' or (not attendance_status and attended is True):
        query = query.filter(or_(Record.attendance_status == 'attended', Record.attended.is_(True)))
    elif attendance_status == 'not_recorded' or (not attendance_status and attended is False):
        query = query.filter(Record.attendance_status != 'attended', Record.attended.is_(False))
    elif attendance_status:
        query = query.filter(Record.attendance_status == attendance_status)
    total = query.count()
    rows = query.order_by(Record.signed_up_at.desc().nullslast(), Record.id).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def update_record_version(db, record, version, values):
    changed = db.execute(update(Record).where(Record.id == record.id, Record.version == version).values(**values, version=Record.version + 1))
    return changed.rowcount == 1


def add_history(db, record_id, account_id, changed):
    db.add(RecordHistory(record_id=record_id, account_id=account_id, changed=changed))


def add_record(db, account_id, course_id, values):
    record = Record(account_id=account_id, course_id=course_id, **values)
    db.add(record)
    return record


def history_for(db, record_id, account_id):
    return db.query(RecordHistory).filter_by(record_id=record_id, account_id=account_id).order_by(RecordHistory.created_at.desc()).limit(20).all()


def flush(db):
    db.flush()


def save(db, record=None):
    db.commit()
    if record is not None:
        db.refresh(record)


def rollback(db):
    db.rollback()


def refresh(db, record):
    db.refresh(record)
