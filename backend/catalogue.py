"""Owned-catalogue connect helpers: lookup near neighbours and save new events."""
from __future__ import annotations

import os
from sqlalchemy import or_
from sqlalchemy.orm import Session

from portal_models import (
    Candidate,
    Course,
    FieldEvidence,
    Job,
    uid,
    fill_course,
    CANDIDATE_SCHEMA_VERSION,
    FILTER_FIELDS,
    listed_filter,
)
from security import digest
from shared.contracts import Training, public_web_url, validate_evidence

REFRESH_FIELDS = FILTER_FIELDS + ('prerequisites', 'registration_url')


def open_review_candidate(db: Session, key: str) -> Candidate | None:
    """Prefer pending/held over rejected. UUID ids are not insertion-ordered."""
    open_row = (
        db.query(Candidate)
        .filter_by(source_key=key)
        .filter(Candidate.status.in_(['pending', 'held']))
        .order_by(Candidate.id)
        .first()
    )
    if open_row:
        return open_row
    return (
        db.query(Candidate)
        .filter_by(source_key=key, status='rejected')
        .order_by(Candidate.id)
        .first()
    )


def auto_publish_new() -> bool:
    return (os.getenv('CATALOGUE_AUTO_PUBLISH_NEW') or '').strip().lower() == 'true'


def training_payload(data: dict) -> dict:
    return {key: value for key, value in (data or {}).items() if not str(key).startswith('_')}


def resolve_review_course(db: Session, candidate: Candidate) -> Course | None:
    data = candidate.data or {}
    matched_id = candidate.resulting_course_id or data.get('_matched_course_id')
    if matched_id:
        course = db.get(Course, matched_id)
        if course:
            return course
    return exact_course(db, candidate.source_key)


def course_compare_value(course: Course, field: str):
    if field in ('prerequisites', 'registration_url'):
        return (course.data or {}).get(field)
    return getattr(course, field, None)


def refresh_diff(course: Course, data: dict) -> list[dict]:
    changes = []
    for field in REFRESH_FIELDS:
        published = course_compare_value(course, field)
        proposed = data.get(field)
        if published != proposed:
            changes.append({'field': field, 'published': published, 'proposed': proposed})
    return changes


def reopen_review_candidate(candidate: Candidate, *, status: str, reason: str = '') -> None:
    """Reopen or refresh a review row and bump version so CandidateCard remounts (id+version)."""
    # Clear operator stamps on reject reopen and held→pending (new supersedes a prior hold).
    # held→held refresh keeps stamps; only the reason/diff/version change.
    if candidate.status == 'rejected' or (candidate.status == 'held' and status != 'held'):
        candidate.reviewed_by = None
        candidate.reviewed_at = None
    candidate.status = status
    candidate.review_reason = reason
    candidate.version = int(candidate.version or 1) + 1


def source_key(data: dict) -> str:
    return digest(
        data['source_url'].split('#')[0]
        + '|'
        + data['title'].strip().lower()
        + '|'
        + str(data.get('start_date'))
    )


def course_public(course: Course) -> dict:
    data = dict(course.data or {})
    source = public_web_url(data.get('source_url'))
    return {
        'id': course.id,
        'title': course.title,
        'provider': course.provider,
        'start_date': course.start_date,
        'city': course.city,
        'mode': course.mode,
        'source_url': source,
        'source_key': course.source_key,
        'data': {'source_url': source},
    }


def exact_course(db: Session, key: str) -> Course | None:
    return db.query(Course).filter_by(source_key=key).first()


def near_neighbours(db: Session, candidate: dict, limit: int = 5) -> list[Course]:
    title = (candidate.get('title') or '').strip()
    provider = (candidate.get('provider') or '').strip()
    city = (candidate.get('city') or '').strip()
    start = str(candidate.get('start_date') or '')
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
    # Fuzzy near-match must not feed cancelled/non-MY rows to Jev. Exact cancelled still
    # short-circuits via exact_course so operator publish can re-list that identity.
    rows = (
        db.query(Course)
        .filter(listed_filter(), or_(*clauses))
        .order_by(Course.updated_at.desc())
        .limit(limit * 3)
        .all()
    )
    scored = []
    for row in rows:
        score = 0
        if provider and provider.lower() in (row.provider or '').lower():
            score += 3
        if title and title.lower()[:20] in (row.title or '').lower():
            score += 3
        if city and city.lower() == (row.city or '').lower():
            score += 1
        if start and start == (row.start_date or ''):
            score += 2
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -(item[1].updated_at or 0)))
    # Require a strong overlap (provider+title-ish or title+date) before Jev near-match.
    return [row for score, row in scored if score >= 5][:limit]


def ensure_job(db: Session, account_id: str, query: str = 'catalogue-save') -> Job:
    job = Job(account_id=account_id, request_key='save-' + uid(), query=query)
    db.add(job)
    db.flush()
    return job


def save_new_candidate(db: Session, account_id: str, training: Training, judgment: dict, job_id: str | None = None) -> Candidate:
    data = validate_evidence(training).model_dump(mode='json')
    key = source_key(data)
    if exact_course(db, key):
        raise ValueError('Event already exists in the catalogue.')
    status = 'pending'
    reason = ''
    if judgment.get('decision') == 'uncertain':
        status = 'held'
        reason = ('Jev uncertain: ' + str(judgment.get('warning') or 'needs operator review'))[:500]
    # Reopen rejected same-identity rows instead of forking another review card.
    existing = open_review_candidate(db, key)
    if existing:
        existing.data = {**data, '_judgment': judgment}
        existing.schema_version = CANDIDATE_SCHEMA_VERSION
        # Always bump (pending→pending too) so CandidateCard remounts on evidence refresh.
        reopen_review_candidate(existing, status=status, reason=reason)
        return existing
    if not job_id:
        job_id = ensure_job(db, account_id).id
    candidate = Candidate(
        job_id=job_id,
        source_key=key,
        data={**data, '_judgment': judgment},
        status=status,
        schema_version=CANDIDATE_SCHEMA_VERSION,
        review_reason=reason,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _attach_field_evidence(db: Session, course: Course, candidate: Candidate, data: dict) -> None:
    """Persist source excerpts for auto-published rows (no operator reviewer stamp)."""
    db.query(FieldEvidence).filter_by(course_id=course.id).delete()
    for field, excerpt in (data.get('evidence') or {}).items():
        text = str(excerpt or '').strip()
        if not text:
            continue
        db.add(
            FieldEvidence(
                course_id=course.id,
                candidate_id=candidate.id,
                field_name=field,
                excerpt=text[:2000],
                # EVT-03: auto-publish keeps excerpts without a reviewer stamp (by or at).
                reviewed_by=None,
                reviewed_at=None,
            )
        )


def publish_new_event(db: Session, account_id: str, training: Training, judgment: dict, job_id: str | None = None) -> tuple[Candidate, Course]:
    """Persist a Jev `new` decision into the searchable owned catalogue."""
    data = validate_evidence(training).model_dump(mode='json')
    key = source_key(data)
    if exact_course(db, key):
        raise ValueError('Event already exists in the catalogue.')
    payload = {**data, '_judgment': judgment}
    reason = 'Published via Jev decision=new'
    # Promote the pending/held/rejected review row instead of forking a second published candidate.
    existing = open_review_candidate(db, key)
    if not job_id:
        job_id = (existing.job_id if existing else None) or ensure_job(db, account_id).id
    course = fill_course(Course(source_key=key), data, demo=False)
    db.add(course)
    db.flush()
    if existing:
        # Auto-publish / connect publish promotes the open review row; clear prior operator stamps.
        if existing.status in ('rejected', 'held'):
            existing.reviewed_by = None
            existing.reviewed_at = None
        existing.data = payload
        existing.status = 'published'
        existing.schema_version = CANDIDATE_SCHEMA_VERSION
        existing.resulting_course_id = course.id
        existing.review_reason = reason
        existing.job_id = job_id
        candidate = existing
        # Remount CandidateCard if the row briefly stays visible before queue refresh.
        existing.version = int(existing.version or 1) + 1
    else:
        candidate = Candidate(
            job_id=job_id,
            source_key=key,
            data=payload,
            status='published',
            schema_version=CANDIDATE_SCHEMA_VERSION,
            resulting_course_id=course.id,
            review_reason=reason,
        )
        db.add(candidate)
        db.flush()
    _attach_field_evidence(db, course, candidate, data)
    db.flush()
    return candidate, course


def link_existing(db: Session, account_id: str, training: Training, course: Course, judgment: dict, job_id: str | None = None) -> Candidate:
    data = validate_evidence(training).model_dump(mode='json')
    key = source_key(data)
    payload = {
        **data,
        '_judgment': judgment,
        '_matched_course_id': course.id,
        '_refresh_diff': refresh_diff(course, data),
    }
    reason = 'Jev marked exists; review refresh before overwriting published fields.'
    # Same identity already awaiting review (or previously rejected): refresh instead of forking duplicates.
    existing = open_review_candidate(db, key)
    if existing:
        existing.data = payload
        existing.resulting_course_id = course.id
        existing.schema_version = CANDIDATE_SCHEMA_VERSION
        # Rejected→held (and held refresh) bump version so operator cards remount with new diff/reason.
        reopen_review_candidate(existing, status='held', reason=reason)
        db.flush()
        return existing
    if not job_id:
        job_id = ensure_job(db, account_id, 'catalogue-refresh').id
    candidate = Candidate(
        job_id=job_id,
        source_key=key,
        data=payload,
        status='held',
        schema_version=CANDIDATE_SCHEMA_VERSION,
        resulting_course_id=course.id,
        review_reason=reason,
    )
    db.add(candidate)
    db.flush()
    return candidate
