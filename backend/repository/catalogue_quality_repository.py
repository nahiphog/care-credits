"""Read-only queue of published listings needing evidence or another review."""
from sqlalchemy import or_
from models import Course
from repository.model_helpers import listed_filter


def pending(db, cutoff, page, size):
    query = db.query(Course).filter(listed_filter(), or_(
        Course.start_date.is_(None), Course.points.is_(None), Course.fee.is_(None),
        Course.reviewed_at.is_(None), Course.reviewed_at < cutoff,
        (Course.fee > 0) & (Course.currency.is_(None) | (Course.currency == ''))))
    total = query.count()
    return query.order_by(Course.reviewed_at.asc(), Course.id).offset((page-1)*size).limit(size).all(), total
