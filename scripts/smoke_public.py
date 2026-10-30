"""Explicit deployment smoke test; creates and removes only its own test rows."""
import os
from pathlib import Path
import secrets
import sys
import time
from datetime import date
import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
settings = dotenv_values(root / '.env.vercel.production')
os.environ['DATABASE_URL'] = settings['DATABASE_URL_UNPOOLED']
from database import SessionLocal, Base
from models import Account, Course
from repository.model_helpers import fill_course, listed_filter
from sqlalchemy import or_

base = sys.argv[1].rstrip('/')
tag = secrets.token_hex(8)
email = 'deployment-test-' + tag + '@example.com'
password = secrets.token_urlsafe(32)
course_id = None
created_course_id = None

def check(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f'{response.request.method} {response.request.url.path}: HTTP {response.status_code}: {response.text[:250]}')
    return response

try:
    with httpx.Client(base_url=base, timeout=90, headers={'Origin': base, 'X-Care-Client': '1'}) as client:
        check(client.get('/'))
        config = check(client.get('/api/v1/config')).json()
        assert config['signup_enabled']
        assert not config['password_recovery_available'], 'Recovery must stay disabled without a sender'
        check(client.get('/reset-password'))
        check(client.post('/api/v1/auth/register', json={'email': email, 'password': password, 'name': 'Deployment Test'}), 201)
        login = check(client.post('/api/v1/auth/login', json={'email': email, 'password': password}))
        cookie = login.headers.get('set-cookie', '').lower()
        assert 'secure' in cookie and 'httponly' in cookie
        check(client.get('/api/v1/admin/services'), 403)
        check(client.get('/api/v1/admin/maintenance'), 403)
        check(client.get('/api/v1/admin/catalogue-quality'), 403)
        with SessionLocal() as db:
            test_account = db.query(Account).filter_by(email=email).one()
            test_account.role = 'operator'
            db.commit()
        for attempt in range(3):
            services = check(client.get('/api/v1/admin/services')).json()
            if services.get('paid_scrape_ready'):
                break
            time.sleep(2)
        assert services.get('database') == 'ready', 'Database readiness failed'
        assert services.get('scraper', {}).get('status') == 'ready', 'Private scraper binding/readiness failed'
        assert services.get('paid_scrape_ready'), 'Live discovery configuration is not ready'
        maintenance = check(client.get('/api/v1/admin/maintenance')).json()
        assert maintenance['client_identity_verified'], 'Vercel client identity was not signed and verified'
        quality = check(client.get('/api/v1/admin/catalogue-quality')).json()
        assert isinstance(quality['items'], list)
        with SessionLocal() as db:
            db.query(Account).filter_by(email=email).one().role = 'doctor'
            db.commit()
        profile = {'name': 'Deployment Verified', 'city': 'Kuala Lumpur', 'state': 'Selangor', 'bio': '', 'public_enabled': False}
        check(client.patch('/api/v1/me', json=profile))
        assert check(client.get('/api/v1/me')).json()['name'] == profile['name']
        with SessionLocal() as db:
            # Prefer an existing published course without changing it. Test records
            # remain private and are removed with this account in finally.
            course = db.query(Course).filter(listed_filter(), or_(Course.start_date.is_(None), Course.start_date <= date.today().isoformat())).order_by(Course.id).first()
            if course is None:
                course = fill_course(Course(source_key='deployment-smoke-' + tag), {
                    'title': 'Temporary deployment check (fictional)', 'provider': 'Deployment test',
                    'mode': 'online', 'country': 'MY', 'start_date': date.today().isoformat(),
                    'points': 1, 'credit_label': 'CPD', 'source_url': 'https://example.com/deployment-test'}, demo=True)
                db.add(course)
                db.commit()
                created_course_id = course.id
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
        print('PASS: dashboard, signup/login, secure cookies, role protection, signed client identity, maintenance, catalogue quality, disabled recovery, private scraper readiness, persistent profile, record, progress, CSV, certificate, logout. No paid discovery run invoked.')
finally:
    with SessionLocal() as db:
        account = db.query(Account).filter_by(email=email).first()
        if account:
            for table in reversed(Base.metadata.sorted_tables):
                if 'account_id' in table.c:
                    db.execute(table.delete().where(table.c.account_id == account.id))
            # Dependants (including the eager profile) were already deleted above;
            # a Core delete avoids ORM delete-orphan issuing a second profile delete.
            db.execute(Account.__table__.delete().where(Account.__table__.c.id == account.id))
        if created_course_id:
            db.query(Course).filter_by(id=created_course_id).delete()
        db.commit()
        print('Temporary smoke-test account and any created fixture course removed; existing courses untouched.')
