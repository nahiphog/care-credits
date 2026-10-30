"""Profile and public-sharing use cases."""
import time
from domain.errors import DomainError
from repository import account_repository as accounts
from repository.learning_repository import record_course_pairs
from repository.audit_repository import audit
from serializers.common import profile
from shared.contracts import public_web_url


def change_profile(db, user, changes):
    values = dict(changes)
    user.latitude = values.pop('latitude')
    user.longitude = values.pop('longitude')
    user.location_consent_at = time.time() if user.latitude is not None else None
    for key, value in values.items():
        setattr(user, key, value)
    audit(db, user.id, 'profile_changed', user.id, {'public_enabled': user.public_enabled, 'has_coordinates': user.latitude is not None})
    accounts.save(db)
    return profile(user)


def public_profile(db, slug):
    account = accounts.public_account(db, slug)
    if not account:
        raise DomainError(404, 'This training profile is private or unavailable.')
    items = []
    for record, course in record_course_pairs(db, account.id, public_only=True):
        if not (getattr(record, 'attendance_status', None) == 'attended' or record.attended):
            continue
        items.append({'title': course.title, 'provider': course.provider, 'attended_on': record.attended_on,
                      'source_url': public_web_url((course.data or {}).get('source_url')), 'demo': course.demo})
    return {'name': account.name, 'bio': account.bio, 'items': items, 'evidence_status': 'Self-reported training history; not independently verified.'}
