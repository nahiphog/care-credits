from repository import transactions
from sqlalchemy import or_
from models.schema import Candidate, Course, FieldEvidence
from repository.model_helpers import listed_filter

def open_candidate(db, key):
    return db.query(Candidate).filter_by(source_key=key).filter(Candidate.status.in_(['pending', 'held'])).order_by(Candidate.id).first()

def rejected_candidate(db, key):
    return db.query(Candidate).filter_by(source_key=key, status='rejected').order_by(Candidate.id).first()

def get_course(db, matched_id):
    return db.get(Course, matched_id)

def course_by_source_key(db, key):
    return db.query(Course).filter_by(source_key=key).first()

def near_neighbours(db, provider, title, city, start, limit):
    clauses = []
    if provider:
        clauses.append(Course.provider.ilike('%' + provider[:80] + '%'))
    if title:
        token = title.split()[0][:40]
        if len(token) >= 3:
            clauses.append(Course.title.ilike('%' + token + '%'))
    if city:
        clauses.append(Course.city.ilike('%' + city[:80] + '%'))
    if start:
        clauses.append(Course.start_date == start)
    if not clauses:
        return []
    return db.query(Course).filter(listed_filter(), or_(*clauses)).order_by(Course.updated_at.desc()).limit(limit * 3).all()

def add_job(db, job):
    return db.add(job)

def flush(db):
    return transactions.flush(db)

def add_candidate(candidate, db):
    return db.add(candidate)

def delete_course_evidence(course, db):
    return db.query(FieldEvidence).filter_by(course_id=course.id).delete()

def add_unreviewed_evidence(candidate, course, db, field, text):
    return db.add(FieldEvidence(course_id=course.id, candidate_id=candidate.id, field_name=field, excerpt=text[:2000], reviewed_by=None, reviewed_at=None))

def add_course(course, db):
    return db.add(course)
