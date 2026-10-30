"""Evidence-based enrichment tasks; never substitute invented course claims."""
import time
from domain.errors import DomainError
from repository.catalogue_quality_repository import pending
from serializers.common import public_web_url


def queue(db, page=1):
    if page < 1:
        raise DomainError(422, 'Invalid page.')
    cutoff = time.time() - 30 * 86400
    rows, total = pending(db, cutoff, page, 20)
    items = []
    for course in rows:
        missing = [label for field, label in [('start_date','date or self-paced evidence'), ('points','advertised credits'), ('fee','fee')]
                   if getattr(course, field) is None]
        if course.fee and not (course.currency or '').strip():
            missing.append('currency')
        items.append({'id':course.id, 'title':course.title, 'missing':missing,
                      'last_reviewed_at':course.reviewed_at,
                      'review_due':not course.reviewed_at or course.reviewed_at < cutoff,
                      'source_url':public_web_url((course.data or {}).get('source_url'))})
    return {'items':items, 'total':total, 'page':page, 'page_size':20}
