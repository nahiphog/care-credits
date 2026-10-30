"""Digest preference and unsubscribe HTTP endpoints."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import get_db
from security import current_user, operator
from errors import envelope
from domain.errors import DomainError
from schemas.learning import DigestChange
from services import preference_service
from services.digest_service import run_due_digests
from services.rate_limit import throttle

router = APIRouter(tags=['digest'])

UNSUBSCRIBE_OK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Unsubscribed — CareCredits</title>
<style>
  body { font-family: Georgia, serif; color: #10233f; max-width: 36rem; margin: 3rem auto; padding: 0 1.25rem; }
  h1 { font-size: 1.6rem; }
  p { line-height: 1.5; color: #3d536b; }
</style>
</head>
<body>
  <h1>You are unsubscribed</h1>
  <p>CareCredits will not send another biweekly digest unless you opt in again from your signed-in portal.</p>
  <p>This page does not require a CareCredits account. No catalogue search or Tavily call ran.</p>
</body>
</html>"""

UNSUBSCRIBE_INVALID_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Unsubscribe link invalid — CareCredits</title>
<style>
  body { font-family: Georgia, serif; color: #10233f; max-width: 36rem; margin: 3rem auto; padding: 0 1.25rem; }
  h1 { font-size: 1.6rem; }
  p { line-height: 1.5; color: #3d536b; }
</style>
</head>
<body>
  <h1>Unsubscribe link invalid</h1>
  <p>This CareCredits digest unsubscribe link is missing, blank, or no longer valid.</p>
  <p>If you still receive digests, open a newer email or sign in and turn off the biweekly digest. No catalogue search or Tavily call ran.</p>
</body>
</html>"""



@router.get('/api/v1/me/digest')
def get_digest(user=Depends(current_user), db: Session = Depends(get_db)):
    return preference_service.get_digest(db, user)

@router.patch('/api/v1/me/digest')
def patch_digest(body: DigestChange, user=Depends(current_user), db: Session = Depends(get_db)):
    return preference_service.patch_digest(db, user, body.opted_in, body.cadence_days)

@router.get('/api/v1/digest/unsubscribe')
def digest_unsubscribe(request: Request, token: str | None = None, db: Session = Depends(get_db)):
    accept = (request.headers.get('accept') or '').lower()
    wants_json = 'application/json' in accept and 'text/html' not in accept
    try:
        result = preference_service.unsubscribe(db, token)
    except DomainError as error:
        return envelope(error.status_code, error.detail, request) if wants_json else HTMLResponse(UNSUBSCRIBE_INVALID_HTML, status_code=404)
    return result if wants_json else HTMLResponse(UNSUBSCRIBE_OK_HTML)

@router.post('/api/v1/admin/digests/run')
def admin_run_digests(user=Depends(operator), db: Session = Depends(get_db)):
    throttle(db, 'digests:' + user.id, 20, 300)
    return run_due_digests(db)
