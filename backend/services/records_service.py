"""Learning-record rules and orchestration; no HTTP or ORM queries."""
import time
from datetime import date
from types import SimpleNamespace
from domain.config import today
from domain.errors import DomainError
from repository import learning_repository as records
from repository.audit_repository import audit
from serializers.common import record_json, course_json
from services.progress_service import progress_snapshot

def save_record(db, user, course_id, changes):
    body = SimpleNamespace(**changes)
    course = records.course_by_id(db, course_id)
    if not course:
        raise DomainError(404, 'Training not found.')
    # Honour status OR legacy bool (heal not_recorded + attended=true drift on write).
    attendance = 'attended' if (body.attendance_status == 'attended' or body.attended) else 'not_recorded'
    body.attended = attendance == 'attended'
    if body.attended:
        if not body.attended_on or body.attended_on > today():
            raise DomainError(422, 'Choose a completion date that is not in the future.')
        if course.start_date and body.attended_on < date.fromisoformat(course.start_date):
            raise DomainError(422, 'Attendance cannot be before the training date.')
    else:
        body.attended_on = None
        body.public = False
    values = vars(body).copy()
    values.pop('version', None)
    if values.get('attended_on') is not None:
        values['attended_on'] = values['attended_on'].isoformat()
    record = records.record_for(db, user.id, course_id)
    status = values.pop('signup_status', None)
    if status == 'cancelled':
        pass
    elif status == 'signed_up' or values.get('signed_up'):
        # Heal not_recorded + signed_up=true drift; cancelled already preferred above.
        status = 'signed_up'
    elif status == 'not_recorded' or status is None:
        # Omitted signup_status + signed_up=false clears to not_recorded.
        # Never invent cancel — REG-01 cancel requires an explicit signup_status=cancelled.
        status = 'not_recorded'
    else:
        # Unexpected leftover string (should not pass Literal); heal from bool only.
        status = 'signed_up' if values.get('signed_up') else 'not_recorded'
    prior = (record.signup_status if record else None) or 'not_recorded'
    # Honour legacy signed_up bool drift: treat as signed_up when status stayed not_recorded.
    if prior == 'not_recorded' and record and record.signed_up:
        prior = 'signed_up'
    if status == 'cancelled' and prior not in ('signed_up', 'cancelled'):
        raise DomainError(422, 'Cancel sign-up only after a recorded provider sign-up.')
    values['signup_status'] = status
    values['signed_up'] = status == 'signed_up'
    values['attendance_status'] = attendance
    values['attended'] = attendance == 'attended'
    if status == 'signed_up':
        values['signed_up_at'] = (record.signed_up_at if record and record.signed_up_at else time.time())
    elif record:
        values['signed_up_at'] = record.signed_up_at
    values['points_origin'] = 'self_reported' if values.get('points') is not None else ''
    if record:
        old = record_json(record)
        comparable = {k: v for k, v in values.items() if k in old}
        if all(old[k] == comparable[k] for k in comparable):
            return old
        changed = records.update_record_version(db, record, body.version, values)
        if not changed:
            records.rollback(db)
            raise DomainError(409, 'This record changed. Reopen it before saving.')
        records.add_history(db, record.id, user.id, {k: old[k] for k in ('signup_status', 'attendance_status', 'attended', 'attended_on', 'points', 'credit_label')})
    else:
        if body.version != 0:
            raise DomainError(409, 'Record version does not match.')
        record = records.add_record(db, user.id, course_id, values)
    try:
        records.flush(db)
        audit(db, user.id, 'training_record_changed', record.id, {k:v for k,v in values.items() if k != 'notes'})
        records.save(db)
    except records.IntegrityError:
        records.rollback(db)
        raise DomainError(409, 'This record changed. Refresh and try again.')
    records.refresh(db, record)
    return record_json(record)



def my_trainings(db, user, signup_status=None, attendance_status=None, attended=None, page=1, page_size=20):
    if page < 1 or not 1 <= page_size <= 50:
        raise DomainError(422, 'Invalid pagination.')
    rows, total = records.page_records(db, user.id, signup_status, attendance_status, attended, page, page_size)
    return {'items': [course_json(c, r) for r, c in rows], 'total': total, 'page': page, 'page_size': page_size}


def progress(db, user, year=None):
    year = today().year if year is None else year
    if not 1900 <= year <= 2200:
        raise DomainError(422, 'Invalid year.')
    return progress_snapshot(db, user.id, year)


def record_history(db, user, course_id):
    record = records.record_for(db, user.id, course_id)
    if not record:
        return {'items': []}
    rows = records.history_for(db, record.id, user.id)
    return {'items': [{'at': row.created_at, **(row.changed or {})} for row in rows]}
