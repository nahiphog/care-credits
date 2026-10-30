"""Explicitly enabled password recovery; never log or return raw tokens."""
import os
import secrets
import time
from urllib.parse import urlsplit
from domain.errors import DomainError
from domain.passwords import digest, password_hash
from repository import account_repository as accounts, recovery_repository as store
from repository.audit_repository import audit
from services import mail_service
from services.rate_limit import throttle

MESSAGE = {'message': 'If an eligible account exists, a password reset email will be sent.'}


def configured():
    base = (os.getenv('PUBLIC_FRONTEND_BASE') or '').strip().rstrip('/')
    try:
        parsed = urlsplit(base)
    except ValueError:
        return False
    return (os.getenv('PASSWORD_RECOVERY_ENABLED') == 'true' and mail_service.configured()
            and parsed.scheme == 'https' and bool(parsed.hostname)
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)


def request_reset(db, email, host):
    if not configured():
        raise DomainError(503, 'Email account recovery is not available. Contact the operator.')
    throttle(db, 'recovery-ip:' + host, 10, 3600)
    throttle(db, 'recovery-email:' + email, 3, 3600)
    account = accounts.account_by_email(db, email)
    if account:
        token = secrets.token_urlsafe(32)
        hashed = digest(token)
        store.issue(db, account.id, hashed, time.time() + 1800)
        base = os.environ['PUBLIC_FRONTEND_BASE'].strip().rstrip('/')
        # Fragment avoids tokens in HTTP request URLs, access logs and referrers.
        body = f'Reset your CareCredits password within 30 minutes:\n{base}/reset-password#token={token}\n\nIf you did not request this, ignore this email.'
        try:
            mail_service.send(account.email, 'Reset your CareCredits password', body)
        except Exception:
            store.revoke(db, hashed)
            audit(db, account.id, 'password_reset_delivery_failed', account.id, {})
            accounts.save(db)
            # A generic response must not reveal account existence or provider details.
    return dict(MESSAGE)


def reset(db, token, new_password, host):
    if not configured():
        raise DomainError(503, 'Email account recovery is not available. Contact the operator.')
    throttle(db, 'recovery-confirm:' + host, 10, 300)
    account_id = store.consume(db, digest(token), time.time(), password_hash(new_password))
    if not account_id:
        raise DomainError(400, 'This reset link is invalid or expired. Request a new one.')
    audit(db, account_id, 'password_reset', account_id, {})
    accounts.save(db)
    return {'message': 'Password reset. Please sign in again on each device.'}
