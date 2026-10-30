"""Feature orchestration: explicit inputs, domain errors and repository persistence."""
import math
from domain.errors import DomainError
from serializers.common import course_json
from repository.learning_repository import records_for
from repository import catalogue_read_repository as repository

def trainings(q='', city='', state='', mode='', difficulty='', verification_status='', publication_status='', max_fee=None, max_fee_myr=None, min_points=None, period='upcoming', date_from=None, date_to=None, include_unknown=False, latitude=None, longitude=None, radius_km=None, page=1, page_size=20, user=None, db=None):
    if page < 1 or not 1 <= page_size <= 50 or (latitude is None) != (longitude is None):
        raise DomainError(422, 'Invalid pagination or location filter.')
    if radius_km is not None and latitude is None:
        raise DomainError(422, 'Radius requires coordinates.')
    if latitude is not None:
        effective_radius = 25 if radius_km is None else radius_km
        if effective_radius not in (10, 25, 50, 100):
            raise DomainError(422, 'Invalid pagination or location filter.')
    else:
        effective_radius = None
    if latitude is not None and (not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise DomainError(422, 'Invalid coordinates.')
    if max_fee is not None and max_fee_myr is not None and (max_fee != max_fee_myr):
        raise DomainError(422, 'Use a single fee filter.')
    fee_limit = max_fee_myr if max_fee_myr is not None else max_fee
    if date_from and date_to and (date_from > date_to):
        raise DomainError(422, 'date_from cannot be after date_to.')
    if any((v is not None and (not math.isfinite(v) or v < 0) for v in (fee_limit, min_points))):
        raise DomainError(422, 'Invalid price or points filter.')
    if mode and mode not in ('in_person', 'online', 'hybrid'):
        raise DomainError(422, 'Invalid mode filter.')
    if difficulty and difficulty not in ('beginner', 'intermediate', 'advanced'):
        raise DomainError(422, 'Invalid difficulty filter.')
    if verification_status and verification_status not in ('unverified', 'source_reviewed'):
        raise DomainError(422, 'Invalid verification_status filter.')
    if publication_status and publication_status != 'published':
        raise DomainError(422, 'Invalid publication_status filter.')
    page_rows, total = repository.search_courses(db, q, city, state, mode, difficulty, verification_status, publication_status, period, date_from, date_to, include_unknown, fee_limit, min_points, latitude, longitude, effective_radius, page, page_size)
    records = records_for(db, user.id, [course.id for course, _ in page_rows])
    items = [{**course_json(course, records.get(course.id)), 'distance_km': distance_km} for course, distance_km in page_rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size, 'applied_filters': {'q': q or None, 'city': city or None, 'state': state or None, 'mode': mode or None, 'difficulty': difficulty or None, 'verification_status': verification_status or None, 'publication_status': publication_status or None, 'max_fee_myr': fee_limit, 'min_points': min_points, 'period': period, 'date_from': date_from.isoformat() if date_from else None, 'date_to': date_to.isoformat() if date_to else None, 'include_unknown': include_unknown, 'latitude': latitude, 'longitude': longitude, 'radius_km': effective_radius}}

def detail(course_id, user=None, db=None):
    course = repository.get_course(course_id, db)
    if not course:
        raise DomainError(404, 'Training not found.')
    return course_json(course, repository.get_personal_record(course_id, db, user), repository.course_evidence(course_id, db))
