"""Google OAuth for doctor sign-in. Email/password remains for local demo."""
from __future__ import annotations
from repository import account_repository as accounts

import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from models import Account
from domain.passwords import digest, password_hash


GOOGLE_AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN = 'https://oauth2.googleapis.com/token'
GOOGLE_ISSUERS = {'https://accounts.google.com', 'accounts.google.com'}


class OAuthError(Exception):
    def __init__(self, detail: str, status_code: int = 401):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def configured() -> bool:
    return bool((os.getenv('GOOGLE_CLIENT_ID') or '').strip() and (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip())


def public_frontend_base() -> str:
    """Next BFF origin for OAuth redirects. Strip padding like GOOGLE_REDIRECT_URI / digest."""
    return (os.getenv('PUBLIC_FRONTEND_BASE') or '').strip().rstrip('/') or 'http://127.0.0.1:3000'


def redirect_uri() -> str:
    explicit = (os.getenv('GOOGLE_REDIRECT_URI') or '').strip()
    if explicit:
        return explicit
    # Default through the Next BFF so oauth_state / care_session share the UI origin.
    return public_frontend_base() + '/api/v1/auth/oauth/google/callback'


def authorize_url(state: str) -> str:
    if not configured():
        raise OAuthError('Google sign-in is not configured.', 503)
    return GOOGLE_AUTH + '?' + urlencode({
        'client_id': os.environ['GOOGLE_CLIENT_ID'].strip(),
        'redirect_uri': redirect_uri(),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    })


def exchange_code(code: str, client: httpx.Client | None = None) -> dict:
    if not configured():
        raise OAuthError('Google sign-in is not configured.', 503)
    owns = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        response = client.post(
            GOOGLE_TOKEN,
            data={
                'code': code,
                'client_id': os.environ['GOOGLE_CLIENT_ID'].strip(),
                'client_secret': os.environ['GOOGLE_CLIENT_SECRET'].strip(),
                'redirect_uri': redirect_uri(),
                'grant_type': 'authorization_code',
            },
        )
        if response.status_code >= 400:
            raise OAuthError('Google rejected the sign-in request.', 401)
        payload = response.json()
        token = payload.get('id_token')
        if not token:
            raise OAuthError('Google did not return an identity token.', 401)
        info = client.get('https://oauth2.googleapis.com/tokeninfo', params={'id_token': token})
        if info.status_code >= 400:
            raise OAuthError('Google identity token could not be verified.', 401)
        claims = info.json()
    finally:
        if owns:
            client.close()
    if claims.get('aud') != os.environ['GOOGLE_CLIENT_ID'].strip():
        raise OAuthError('Google identity token audience did not match.', 401)
    if claims.get('iss') not in GOOGLE_ISSUERS:
        raise OAuthError('Google identity token issuer is not trusted.', 401)
    raw_email = claims.get('email')
    email = raw_email.strip().lower() if isinstance(raw_email, str) else ''
    verified = claims.get('email_verified')
    if not email or not (verified is True or verified == 'true'):
        raise OAuthError('Google account email is missing or unverified.', 401)
    raw_subject = claims.get('sub')
    subject = raw_subject.strip() if isinstance(raw_subject, str) else ''
    if not subject or len(subject) > 200:
        raise OAuthError('Google account identity is missing or invalid.', 401)
    name = claims.get('name')
    return {
        'email': email,
        'name': (name if isinstance(name, str) and name else email.split('@')[0])[:100],
        'subject': subject,
    }


def upsert_account(db, identity: dict, allow_create: bool) -> Account:
    issuer = 'https://accounts.google.com'
    subject = (identity.get('subject') or '').strip() or None
    account = None
    if subject:
        account = accounts.account_by_identity(db, issuer, subject)
    if not account:
        account = accounts.account_by_email(db, identity['email'])
    if account:
        # Same verified email must not mint a session for a differently linked Google subject.
        if subject and account.identity_subject and account.identity_subject != subject:
            raise OAuthError('Google account does not match the linked identity for this email.', 401)
        if subject and not account.identity_subject:
            account.identity_issuer = issuer
            account.identity_subject = subject
        return account
    if not allow_create:
        raise OAuthError('Registration is disabled. Contact the application operator.', 403)
    account = accounts.create_account(db,
        email=identity['email'],
        name=identity['name'] or 'Doctor',
        password_hash=password_hash(secrets.token_urlsafe(32)),
        identity_issuer=issuer if subject else None,
        identity_subject=subject,
    )
    return account


def issue_session(db, account, prior_token=None):
    from services.auth_service import issue_session as create_session
    return create_session(db, account, prior_token)
