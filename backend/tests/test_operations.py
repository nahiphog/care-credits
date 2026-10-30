"""Recovery, cron receipts and duplicate-delivery regression coverage."""
import os
import time
from unittest.mock import patch
import unittest
from backend.tests.test_portal import PortalTests
from models import PasswordReset, LoginSession, MaintenanceRun, DigestDispatch
from domain.passwords import digest, password_matches
from services import recovery_service, maintenance_service, scheduled_digest_service, digest_service
from repository import account_repository


class OperationsTests(unittest.TestCase):
    setUp = PortalTests.setUp
    tearDown = PortalTests.tearDown
    login = PortalTests.login
    def test_recovery_disabled_and_email_validation(self):
        self.assertEqual(self.client.post('/api/v1/auth/password-recovery', json={'email':'a@example.com'}).status_code, 503)
        self.assertFalse(self.client.get('/api/v1/config').json()['password_recovery_available'])
        self.assertEqual(self.client.post('/api/v1/auth/password-recovery', json={'email':'bad'}).status_code, 422)

    def recovery_env(self):
        return patch.dict(os.environ, {'PASSWORD_RECOVERY_ENABLED':'true', 'MAIL_PROVIDER':'smtp',
            'SMTP_HOST':'mail.example.com', 'SMTP_FROM':'test@example.com',
            'PUBLIC_FRONTEND_BASE':'https://care-credits-hackathon.vercel.app'})

    def test_recovery_single_use_revokes_sessions_and_stores_only_hash(self):
        with self.recovery_env(), patch('services.mail_service.send') as send:
            known = self.client.post('/api/v1/auth/password-recovery', json={'email':'a@example.com'})
            unknown = self.client.post('/api/v1/auth/password-recovery', json={'email':'missing@example.com'})
            self.assertEqual(known.json(), unknown.json())
            self.assertEqual(send.call_count, 1)
            body = send.call_args.args[2]
            token = body.split('#token=')[1].split()[0]
            with self.Session() as db:
                row = db.query(PasswordReset).one()
                self.assertEqual(row.token_hash, digest(token))
                self.assertNotEqual(row.token_hash, token)
            result = self.client.post('/api/v1/auth/password-reset', json={'token':token,'new_password':'New-password-1234'})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.client.get('/api/v1/me').status_code, 401)
            self.assertEqual(self.client.post('/api/v1/auth/password-reset', json={'token':token,'new_password':'Another-password-1234'}).status_code, 400)
            with self.Session() as db:
                self.assertEqual(db.query(LoginSession).filter_by(account_id=self.a).count(), 0)
                self.assertTrue(password_matches('New-password-1234', account_repository.account_by_id(db,self.a).password_hash))

    def test_expired_reset_and_failed_email(self):
        with self.recovery_env(), patch('services.mail_service.send', side_effect=RuntimeError('private-provider-detail')):
            result = self.client.post('/api/v1/auth/password-recovery', json={'email':'a@example.com'})
            self.assertEqual(result.status_code,200)
            self.assertNotIn('private-provider-detail', result.text)
            with self.Session() as db:
                self.assertEqual(db.query(PasswordReset).count(),0)
                db.add(PasswordReset(token_hash=digest('x'*32), account_id=self.a, expires_at=time.time()-1)); db.commit()
            self.assertEqual(self.client.post('/api/v1/auth/password-reset', json={'token':'x'*32,'new_password':'Another-password-1234'}).status_code,400)

    def test_maintenance_receipt_failure_and_role_isolation(self):
        with self.Session() as db:
            result = maintenance_service.maintain(db)
            self.assertEqual(result['counts']['digests']['status'], 'disabled')
            self.assertFalse(maintenance_service.status(db)['overdue'])
            with patch('services.maintenance_service.purge_expired_source_text', side_effect=RuntimeError('secret')):
                with self.assertRaises(RuntimeError): maintenance_service.maintain(db)
            receipt = db.query(MaintenanceRun).filter_by(status='failed').one()
            self.assertEqual(receipt.error_type,'RuntimeError')
        self.assertEqual(self.client.get('/api/v1/admin/maintenance').status_code,200)
        self.login('b@example.com')
        self.assertEqual(self.client.get('/api/v1/admin/maintenance').status_code,403)

    def test_digest_disabled_and_uncertain_send_not_repeated(self):
        with self.Session() as db:
            self.assertEqual(scheduled_digest_service.run_batch(db)['status'],'disabled')
            pref=digest_service.ensure_preference(db,self.b); pref.opted_in=True; db.commit()
            with self.recovery_env(), patch.dict(os.environ,{'SERVERLESS_DIGEST_ENABLED':'true','DIGEST_ENABLED':'true'}), patch('services.digest_service.send_via_provider',side_effect=TimeoutError):
                self.assertEqual(scheduled_digest_service.run_batch(db)['uncertain'],1)
                self.assertEqual(scheduled_digest_service.run_batch(db)['uncertain'],0)
                self.assertEqual(db.query(DigestDispatch).one().state,'uncertain')

    def test_catalogue_quality_queue_role_and_unknowns(self):
        result = self.client.get('/api/v1/admin/catalogue-quality')
        self.assertEqual(result.status_code,200)
        self.assertIn('fee',result.json()['items'][0]['missing'])
        self.assertTrue(result.json()['items'][0]['review_due'])
        self.assertEqual(self.client.get('/api/v1/admin/catalogue-quality?page=0').status_code,422)
        self.login('b@example.com')
        self.assertEqual(self.client.get('/api/v1/admin/catalogue-quality').status_code,403)
