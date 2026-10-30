"""Account authentication use cases. HTTP cookies belong to the router."""
import os
import secrets
import time
from domain.errors import DomainError
from domain.passwords import password_hash, password_matches, digest
from repository import account_repository as accounts
from repository.audit_repository import audit
from services.rate_limit import throttle

_DUMMY = password_hash('not-an-account-password')


def register(db, email, name, password, host):
    if os.getenv('ALLOW_SIGNUP') != 'true':
        raise DomainError(403, 'Registration is disabled. Contact the application operator.')
    throttle(db, 'register:' + host, 10, 3600)
    try:
        accounts.create_account(db, email=email, name=name, password_hash=password_hash(password))
        accounts.save(db)
    except accounts.IntegrityError:
        accounts.rollback(db)
        raise DomainError(409, 'This address cannot be registered. Try signing in.')
    return {'message': 'Account created. Please sign in.'}


def maybe_reseed_demo_login(db, email, password):
    if os.getenv('DEMO_MODE') != 'true':
        return
    from seed_demo import DEMO_EMAILS, DEMO_PASSWORD, seed
    if email in DEMO_EMAILS and password == DEMO_PASSWORD:
        seed(db)


def issue_session(db, account, prior_token=None):
    if prior_token:
        accounts.revoke_session(db, digest(prior_token))
    token = secrets.token_urlsafe(32)
    accounts.create_session(db, token_hash=digest(token), account_id=account.id, expires_at=time.time() + 28800)
    accounts.save(db)
    return token


def login(db, email, password, host, prior_token=None):
    throttle(db, 'login-ip:' + host, 30, 300)
    throttle(db, 'login-email:' + email, 10, 300)
    maybe_reseed_demo_login(db, email, password)
    account = accounts.account_by_email(db, email)
    valid = password_matches(password, account.password_hash if account else _DUMMY)
    if not account or not valid:
        raise DomainError(401, 'Email or password is incorrect.')
    return account, issue_session(db, account, prior_token)


def logout(db, token):
    accounts.revoke_session(db, digest(token or ''))
    accounts.save(db)
    return {'ok': True}


def change_password(db, account, current_password, new_password):
    throttle(db, 'password-change:' + account.id, 5, 300)
    if not password_matches(current_password, account.password_hash):
        raise DomainError(403, 'Current password is incorrect.')
    if current_password == new_password:
        raise DomainError(422, 'Choose a different new password.')
    account.password_hash = password_hash(new_password)
    accounts.revoke_account_sessions(db, account.id)
    audit(db, account.id, 'password_changed', account.id, {})
    accounts.save(db)
    return {'message': 'Password changed. Please sign in again on each device.'}
