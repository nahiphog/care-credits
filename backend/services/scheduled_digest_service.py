"""Bounded cron delivery. SMTP ambiguity never triggers an automatic duplicate."""
import os
import time
from urllib.parse import urlsplit
from services import digest_service
from services import mail_service
from repository import digest_dispatch_repository as dispatch, digest_repository as store


def configured():
    try:
        base = urlsplit((os.getenv('PUBLIC_FRONTEND_BASE') or '').strip())
        valid_base = base.scheme == 'https' and bool(base.hostname) and not base.username and not base.password and not base.query and not base.fragment
    except ValueError:
        valid_base = False
    return (os.getenv('SERVERLESS_DIGEST_ENABLED') == 'true'
            and os.getenv('DIGEST_ENABLED') == 'true' and mail_service.configured() and valid_base)


def run_batch(db):
    if not configured():
        return {'status': 'disabled', 'sent': 0, 'uncertain': 0}
    now = time.time()
    result = {'status': 'completed', 'sent': 0, 'uncertain': 0}
    attempted = 0
    # One message per cron bounds SMTP work; skipped claims do not starve later users.
    for pref in digest_service.due_preferences(db, now)[:100]:
        account = store.account_by_id(db, pref.account_id)
        if not account or account.role != 'doctor':
            continue
        key = account.id + ':' + str(pref.last_sent_at or 0)
        if not dispatch.claim(db, key, account.id, now):
            continue
        # A concurrent unsubscribe wins before delivery begins.
        dispatch.refresh(db, pref)
        if not pref.opted_in:
            dispatch.finish(db, key, 'cancelled', time.time())
            continue
        try:
            row = digest_service.send_digest(db, account, pref, os.environ['PUBLIC_FRONTEND_BASE'], now)
            state = 'sent' if row.status == 'sent' else 'uncertain'
        except Exception:
            dispatch.rollback(db)
            state = 'uncertain'
        dispatch.finish(db, key, state, time.time())
        result[state] += 1
        attempted += 1
        if attempted >= 1:
            break
    return result
