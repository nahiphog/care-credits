import math
import heapq
from sqlalchemy import and_, or_
from models.schema import Course, Record, FieldEvidence
from domain.config import today
from repository.model_helpers import listed_filter

def distance(lat1, lon1, lat2, lon2):
    p1, p2 = (math.radians(lat1), math.radians(lat2))
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, d)))

def _contains(column, value):
    escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return column.ilike(f'%{escaped}%', escape='\\')

def search_courses(db, q, city, state, mode, difficulty, verification_status, publication_status, period, date_from, date_to, include_unknown, fee_limit, min_points, latitude, longitude, effective_radius, page, page_size):
    query = db.query(Course).filter(listed_filter())
    if q:
        like = _contains(Course.title, q) | _contains(Course.provider, q) | _contains(Course.description, q)
        query = query.filter(like)
    near_me_includes_online = latitude is not None and mode in ('', 'online', 'hybrid')
    if city:
        city_match = _contains(Course.city, city)
        query = query.filter(or_(city_match, Course.mode == 'online') if near_me_includes_online else city_match)
    if state:
        state_match = _contains(Course.state, state)
        query = query.filter(or_(state_match, Course.mode == 'online') if near_me_includes_online else state_match)
    if mode:
        if latitude is not None and mode == 'hybrid':
            query = query.filter(Course.mode.in_(('hybrid', 'online')))
        else:
            query = query.filter(Course.mode == mode)
    if difficulty:
        query = query.filter(Course.difficulty == difficulty)
    if verification_status:
        query = query.filter(Course.verification_status == verification_status)
    if publication_status:
        query = query.filter(Course.publication_status == publication_status)
    today_s = today().isoformat()
    if period == 'upcoming':
        query = query.filter(or_(Course.start_date >= today_s, Course.start_date.is_(None)) if include_unknown else Course.start_date >= today_s)
    elif period == 'past':
        query = query.filter(or_(Course.start_date < today_s, Course.start_date.is_(None)) if include_unknown else Course.start_date < today_s)
    if date_from:
        query = query.filter(or_(Course.start_date >= date_from.isoformat(), Course.start_date.is_(None)) if include_unknown else Course.start_date >= date_from.isoformat())
    if date_to:
        query = query.filter(or_(Course.start_date <= date_to.isoformat(), Course.start_date.is_(None)) if include_unknown else Course.start_date <= date_to.isoformat())
    if fee_limit is not None:
        # Zero is free in every currency; positive unknown currencies cannot be converted.
        affordable = or_(Course.fee == 0, and_(Course.currency == 'MYR', Course.fee <= fee_limit))
        query = query.filter(or_(Course.fee.is_(None), affordable) if include_unknown else affordable)
    if min_points is not None:
        enough = Course.points >= min_points
        query = query.filter(or_(Course.points.is_(None), enough) if include_unknown else enough)
    if latitude is not None:
        delta_lat = effective_radius / 111
        delta_lon = effective_radius / (111 * max(0.2, abs(math.cos(math.radians(latitude)))))
        nearby = [and_(Course.latitude.isnot(None), Course.latitude.between(latitude - delta_lat, latitude + delta_lat), Course.longitude.between(longitude - delta_lon, longitude + delta_lon))]
        if mode in ('', 'online', 'hybrid'):
            nearby.append(Course.mode == 'online')
        if city or state:
            nearby.append(and_(Course.mode != 'online', Course.latitude.is_(None)))
        query = query.filter(or_(*nearby))
    query = query.order_by(Course.start_date.is_(None), Course.start_date, Course.id)
    if latitude is None:
        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        page_rows = [(course, None) for course in rows]
    else:
        total = 0

        def nearby_rows():
            nonlocal total
            for course in query.yield_per(250):
                distance_km = None
                if course.mode != 'online' and course.latitude is not None and (course.longitude is not None):
                    distance_km = round(distance(latitude, longitude, course.latitude, course.longitude), 1)
                    if distance_km > effective_radius:
                        continue
                total += 1
                yield (course, distance_km)
        nearest = heapq.nsmallest(page * page_size, nearby_rows(), key=lambda item: (item[1] is None, item[1] if item[1] is not None else 0.0, item[0].start_date is None, item[0].start_date or '', item[0].id))
        page_rows = nearest[(page - 1) * page_size:page * page_size]
    return (page_rows, total)

def get_course(course_id, db):
    return db.get(Course, course_id)

def get_personal_record(course_id, db, user):
    return db.query(Record).filter_by(account_id=user.id, course_id=course_id).first()

def course_evidence(course_id, db):
    return db.query(FieldEvidence).filter_by(course_id=course_id).all()
