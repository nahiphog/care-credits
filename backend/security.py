import hashlib
import os
import secrets
import time
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db


from domain.passwords import password_hash, password_matches, digest
from services.rate_limit import throttle
from repository.account_repository import account_by_id, session_by_hash


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get('care_session', '')
    session = session_by_hash(db, digest(token))
    if not session or session.expires_at < time.time():
        raise HTTPException(401, 'Please sign in.')
    account = account_by_id(db, session.account_id)
    if not account:
        raise HTTPException(401, 'Please sign in.')
    return account


def operator(user=Depends(current_user)):
    if user.role != 'operator':
        raise HTTPException(403, 'Operator access required.')
    return user


def worker(request: Request):
    # Fail closed on blank/whitespace tokens; require Bearer (case-insensitive) + strip both sides
    # so .env newlines / accidental padding cannot mint a match or look "configured".
    expected = (os.getenv('SCRAPER_SERVICE_TOKEN') or '').strip()
    if not expected:
        raise HTTPException(503, 'Scraper service is not configured.')
    auth = (request.headers.get('Authorization') or '').strip()
    provided = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    if not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(403, 'Service authorization required.')
