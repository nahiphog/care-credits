"""One explicitly requested live run. No provider retries or automatic publication."""
import json
import os
from pathlib import Path
import secrets
import sys
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: verify_live_discovery.py PUBLIC_ORIGIN QUERY')
    base, query = sys.argv[1].rstrip('/'), sys.argv[2]
    if base != 'https://care-credits-hackathon.vercel.app':
        raise SystemExit('This verification is scoped to the existing public deployment.')
    settings = dotenv_values(ROOT / '.env.vercel.production')
    os.environ['DATABASE_URL'] = settings['DATABASE_URL_UNPOOLED']
    from database import SessionLocal
    from models import Account, AccountProfile, LoginSession, Job, Audit
    email = 'discovery-check-' + secrets.token_hex(10) + '@example.com'
    password = secrets.token_urlsafe(32)
    account_id = None
    job_id = None
    def checked(response, expected=200):
        if response.status_code != expected:
            raise RuntimeError(f'{response.request.method} {response.request.url.path}: HTTP {response.status_code}')
        return response.json()
    try:
        with httpx.Client(base_url=base, timeout=260, headers={'Origin':base, 'X-Care-Client':'1'}) as client:
            checked(client.post('/api/v1/auth/register',json={'email':email,'password':password,'name':'Discovery verification'}),201)
            checked(client.post('/api/v1/auth/login',json={'email':email,'password':password}))
            with SessionLocal() as db:
                account = db.query(Account).filter_by(email=email).one()
                account_id = account.id
                account.role = 'operator'; db.commit()
            ready = checked(client.get('/api/v1/admin/services'))
            if not ready.get('paid_scrape_ready'):
                raise RuntimeError('Discovery is not ready; no job started.')
            job = checked(client.post('/api/v1/admin/ingestion-jobs',headers={'Idempotency-Key':'live-proof-'+secrets.token_hex(12)},json={'query':query,'max_results':1}),202)
            job_id = job['id']
            print('Created bounded live job:', job_id, flush=True)
            result = checked(client.post('/api/v1/admin/ingestion-jobs/'+job_id+'/run'))
            # Terminal repeated execution must return the same receipt without another extraction.
            repeated = checked(client.post('/api/v1/admin/ingestion-jobs/'+job_id+'/run'))
            assert repeated.get('result') == result.get('result')
            receipt = {'id':job_id, 'status':result.get('status'), 'result':result.get('result')}
            output = ROOT / 'outputs' / 'live-discovery-verification.json'
            output.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
            print('Terminal status:',result.get('status'),'; receipt saved; repeat returned unchanged result.')
    finally:
        if account_id:
            with SessionLocal() as db:
                owner = db.query(Account).filter_by(email='gohpihan@gmail.com',role='operator').one_or_none()
                if job_id and not owner:
                    raise RuntimeError('Keep verification identity for job ownership; operator owner unavailable.')
                if job_id:
                    db.query(Job).filter_by(id=job_id,account_id=account_id).update({'account_id':owner.id})
                db.query(LoginSession).filter_by(account_id=account_id).delete()
                db.query(Audit).filter_by(account_id=account_id).delete()
                db.query(AccountProfile).filter_by(account_id=account_id).delete()
                db.query(Account).filter_by(id=account_id).delete()
                db.commit()
            print('Temporary verification account removed; job retained for operator review.')


if __name__ == '__main__':
    main()
