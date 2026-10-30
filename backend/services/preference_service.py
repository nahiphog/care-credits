"""Digest subscription policy and availability."""
import os
import time
from domain.errors import DomainError
from repository import digest_repository as store
from services.digest_service import ensure_preference, preference_json

from domain.config import digest_available


def get_digest(db, user):
    return {**preference_json(ensure_preference(db, user.id)), 'available': digest_available()}


def patch_digest(db, user, opted_in, cadence_days=None):
    if opted_in and not digest_available():
        raise DomainError(503, 'Automatic digest delivery is not available on this deployment.')
    pref = ensure_preference(db, user.id)
    was_out = not pref.opted_in
    pref.opted_in = opted_in
    if cadence_days is not None:
        pref.cadence_days = cadence_days
    if opted_in:
        pref.unsubscribed_at = None
        # Fresh opt-in after unsubscribe/backoff must not stay blocked by a prior fail timer.
        if was_out:
            pref.fail_count = 0
            pref.next_retry_at = None
    else:
        pref.unsubscribed_at = time.time()
    store.save(db)
    return {**preference_json(pref), 'available': digest_available()}



def unsubscribe(db, token):
    cleaned = (token or '').strip()
    pref = store.preference_by_token(db, cleaned) if cleaned else None
    if not pref:
        raise DomainError(404, 'Unsubscribe link is invalid or expired.')
    pref.opted_in = False
    pref.unsubscribed_at = time.time()
    store.save(db)
    return {'opted_in': False, 'message': 'You are unsubscribed from CareCredits digests.'}
