import hashlib
import os
import secrets
import time
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from database import get_db
from portal_models import Account, LoginSession, Throttle


def password_hash(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=67108864).hex()
    return salt + ':' + hashed


def password_matches(password, encoded):
    salt, expected = encoded.split(':')
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=67108864).hex()
    return secrets.compare_digest(actual, expected)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def throttle(db, key, limit=20, window=300):
    bucket = digest(key) + ':' + str(int(time.time()) // window)
    if not db.get(Throttle, bucket):
        try:
            with db.begin_nested():
                db.add(Throttle(key=bucket, count=0))
                db.flush()
        except IntegrityError:
            pass
    result = db.execute(update(Throttle).where(Throttle.key == bucket, Throttle.count < limit).values(count=Throttle.count + 1))
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(429, 'Too many requests. Please try again later.')


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get('care_session', '')
    session = db.get(LoginSession, digest(token))
    if not session or session.expires_at < time.time():
        raise HTTPException(401, 'Please sign in.')
    account = db.get(Account, session.account_id)
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
