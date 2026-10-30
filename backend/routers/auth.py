"""Authentication HTTP boundary: validated requests, cookies and redirects."""
import os
import secrets
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from security import current_user
from domain.errors import DomainError
from domain.config import production_env
from http_boundary import client_host
from errors import envelope
from schemas.account import Credentials, PasswordChange, RecoveryRequest, RecoveryConfirm
from services import recovery_service
from serializers.common import profile
from services import auth_service
from services.rate_limit import throttle
from services.oauth_service import authorize_url, configured as google_oauth, exchange_code, issue_session, public_frontend_base, upsert_account, OAuthError

router = APIRouter(prefix='/api/v1/auth', tags=['auth'])


@router.post('/password-recovery')
def request_recovery(body: RecoveryRequest, request: Request, db=Depends(get_db)):
    return recovery_service.request_reset(db, body.email, client_host(request))


@router.post('/password-reset')
def confirm_recovery(body: RecoveryConfirm, request: Request, response: Response, db=Depends(get_db)):
    result = recovery_service.reset(db, body.token, body.new_password, client_host(request))
    _delete_session_cookie(response, 'care_session')
    return result

def _session_cookie_kwargs():
    return {
        'httponly': True,
        'secure': production_env(),
        'samesite': 'lax',
        'max_age': 28800,
        'path': '/',
    }


def _oauth_state_cookie_kwargs():
    return {
        'httponly': True,
        'secure': production_env(),
        'samesite': 'lax',
        'max_age': 600,
        'path': '/',
    }


def _delete_session_cookie(response: Response, name: str):
    # Match set_cookie flags so production Secure cookies actually clear.
    response.delete_cookie(
        name,
        path='/',
        httponly=True,
        secure=production_env(),
        samesite='lax',
    )


@router.get('/oauth/google')
def google_start(request: Request, response: Response):
    state = secrets.token_urlsafe(24)
    try:
        url = authorize_url(state)
    except OAuthError as exc:
        # Match callback failure paths: drop leftover oauth_state on unconfigured start.
        return _oauth_callback_error(request, exc.status_code, exc.detail)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie('oauth_state', state, **_oauth_state_cookie_kwargs())
    return response


def _oauth_callback_error(request: Request, status_code: int, message: str):
    """Envelope for OAuth callback failures; always drop leftover oauth_state."""
    response = envelope(status_code, message, request)
    _delete_session_cookie(response, 'oauth_state')
    return response


@router.get('/oauth/google/callback')
def google_callback(request: Request, db: Session = Depends(get_db), code: str = '', state: str = '', error: str = ''):
    expected = request.cookies.get('oauth_state', '')
    # Strip padded PUBLIC_FRONTEND_BASE (parity with oauth.redirect_uri / digest BFF preference).
    frontend = public_frontend_base()
    if error:
        dest = RedirectResponse(frontend + '/live?oauth=denied', status_code=302)
        _delete_session_cookie(dest, 'oauth_state')
        return dest
    # Match start endpoint: unconfigured Google stays 503 (no KeyError on missing env).
    if not google_oauth():
        return _oauth_callback_error(request, 503, 'Google sign-in is not configured.')
    # Same IP budget as password login so Google callback cannot mint sessions unbounded.
    # Browser navigations must not land on a raw JSON 429 — map throttle to /live like state failures.
    try:
        throttle(db, 'login-ip:' + client_host(request), 30, 300)
    except DomainError as exc:
        if exc.status_code == 429:
            dest = RedirectResponse(frontend + '/live?oauth=failed', status_code=302)
            _delete_session_cookie(dest, 'oauth_state')
            return dest
        raise
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        # Browser callback — surface on /live like provider/account failures (not a raw JSON page).
        dest = RedirectResponse(frontend + '/live?oauth=failed', status_code=302)
        _delete_session_cookie(dest, 'oauth_state')
        return dest
    try:
        identity = exchange_code(code)
        account = upsert_account(db, identity, os.getenv('ALLOW_SIGNUP') == 'true')
        token = issue_session(db, account, request.cookies.get('care_session'))
    except OAuthError as exc:
        # Browser landed on the callback URL — map provider/account failures to the demo shell.
        if exc.status_code in (401, 403):
            dest = RedirectResponse(frontend + '/live?oauth=failed', status_code=302)
            _delete_session_cookie(dest, 'oauth_state')
            return dest
        return _oauth_callback_error(request, exc.status_code, exc.detail)
    dest = RedirectResponse(frontend + '/live', status_code=302)
    dest.set_cookie('care_session', token, **_session_cookie_kwargs())
    _delete_session_cookie(dest, 'oauth_state')
    return dest



@router.post('/register', status_code=201)
def register(body: Credentials, request: Request, db: Session = Depends(get_db)):
    return auth_service.register(db, body.email, body.name, body.password, client_host(request))


@router.post('/login')
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    account, token = auth_service.login(db, body.email, body.password, client_host(request), request.cookies.get('care_session'))
    response.set_cookie('care_session', token, **_session_cookie_kwargs())
    _delete_session_cookie(response, 'oauth_state')
    return profile(account)


@router.post('/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    result = auth_service.logout(db, request.cookies.get('care_session', ''))
    _delete_session_cookie(response, 'care_session')
    _delete_session_cookie(response, 'oauth_state')
    return result


@router.post('/password')
def change_password(body: PasswordChange, response: Response, user=Depends(current_user), db: Session = Depends(get_db)):
    result = auth_service.change_password(db, user, body.current_password, body.new_password)
    _delete_session_cookie(response, 'care_session')
    return result
