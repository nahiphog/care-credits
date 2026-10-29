"""Explicit deployment smoke test; creates and removes only its own test rows."""
import os
from pathlib import Path
import secrets
import sys
from datetime import date
import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
settings = dotenv_values(root / '.env.vercel.production')
os.environ['DATABASE_URL'] = settings['DATABASE_URL_UNPOOLED']
from database import SessionLocal, Base
from portal_models import Account, Course, fill_course

base = sys.argv[1].rstrip('/')
tag = secrets.token_hex(8)
email = 'deployment-test-' + tag + '@example.com'
password = secrets.token_urlsafe(32)
course_id = None

def check(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f'{response.request.method} {response.request.url.path}: HTTP {response.status_code}: {response.text[:250]}')
    return response

try:
    with httpx.Client(base_url=base, timeout=90, headers={'Origin': base, 'X-Care-Client': '1'}) as client:
        check(client.get('/'))
        assert check(client.get('/api/v1/config')).json()['signup_enabled']
        check(client.post('/api/v1/auth/register', json={'email': email, 'password': password, 'name': 'Deployment Test'}), 201)
        login = check(client.post('/api/v1/auth/login', json={'email': email, 'password': password}))
        cookie = login.headers.get('set-cookie', '').lower()
        assert 'secure' in cookie and 'httponly' in cookie
        check(client.get('/api/v1/admin/services'), 403)
        profile = {'name': 'Deployment Verified', 'city': 'Kuala Lumpur', 'state': 'Selangor', 'bio': '', 'public_enabled': False}
        check(client.patch('/api/v1/me', json=profile))
        assert check(client.get('/api/v1/me')).json()['name'] == profile['name']
        with SessionLocal() as db:
            course = fill_course(Course(source_key='deployment-smoke-' + tag), {
                'title': 'Temporary deployment check (fictional)', 'provider': 'Deployment test',
                'mode': 'online', 'country': 'MY', 'start_date': date.today().isoformat(),
                'points': 1, 'credit_label': 'CPD', 'source_url': 'https://example.com/deployment-test'}, demo=True)
            db.add(course)
            db.commit()
            course_id = course.id
        record = check(client.put('/api/v1/me/trainings/' + course_id, json={
            'signed_up': True, 'attended': True, 'attended_on': date.today().isoformat(),
            'points': 1, 'credit_label': 'CPD', 'notes': 'Temporary verification', 'public': False, 'version': 0}))
        check(client.get('/api/v1/me/trainings'))
        check(client.get('/api/v1/me/progress'))
        check(client.get('/api/v1/me/export/csv'))
        cert = check(client.post('/api/v1/me/certificates', json={'year': date.today().year}), 201).json()
        check(client.get('/api/v1/me/certificates/' + cert['id'] + '?format=html'))
        check(client.post('/api/v1/auth/logout'))
        check(client.get('/api/v1/me'), 401)
        print('PASS: public V1, signup/login, secure cookies, role protection, persistent profile, record, progress, CSV, certificate, logout')
finally:
    with SessionLocal() as db:
        account = db.query(Account).filter_by(email=email).first()
        if account:
            for table in reversed(Base.metadata.sorted_tables):
                if 'account_id' in table.c:
                    db.execute(table.delete().where(table.c.account_id == account.id))
            db.delete(account)
        if course_id:
            db.query(Course).filter_by(id=course_id).delete()
        db.commit()
        print('Temporary smoke-test account and course removed.')
