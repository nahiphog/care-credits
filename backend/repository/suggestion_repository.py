"""Candidate-selection queries for advisory recommendations."""
from sqlalchemy import func
from models import Course
from repository.model_helpers import listed_filter


def candidate_buckets(db, today, city, preferred_mode, skip, limit):
    base = db.query(Course).filter(listed_filter(), Course.start_date != None, Course.start_date >= today)
    # Exclude skip ids before LIMIT so heavy same-city sign-ups cannot empty the city bucket.
    if skip:
        base = base.filter(~Course.id.in_(skip))
    city_match_col = func.lower(func.trim(Course.city)) == city if city else None
    buckets = []
    if city and preferred_mode:
        buckets.append(
            base.filter(city_match_col, Course.mode == preferred_mode).order_by(Course.start_date).limit(limit).all()
        )
    if city:
        buckets.append(base.filter(city_match_col).order_by(Course.start_date).limit(limit * 2).all())
    if preferred_mode:
        buckets.append(base.filter(Course.mode == preferred_mode).order_by(Course.start_date).limit(limit).all())
    buckets.append(base.order_by(Course.start_date).limit(limit * 3).all())
    undated = db.query(Course).filter(listed_filter(), Course.start_date == None, Course.mode == 'online')
    if skip:
        undated = undated.filter(~Course.id.in_(skip))
    buckets.append(undated.order_by(Course.title, Course.id).limit(limit).all())
    return buckets
