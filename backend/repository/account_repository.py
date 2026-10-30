"""Account, profile, session and throttle persistence. No HTTP dependencies."""
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from models import Account, LoginSession, Throttle, PasswordReset


def account_by_email(db, email):
    return db.query(Account).filter_by(email=email).first()


def account_by_identity(db, issuer, subject):
    return db.query(Account).filter_by(identity_issuer=issuer, identity_subject=subject).first()


def account_by_id(db, account_id):
    return db.get(Account, account_id)


def public_account(db, slug):
    return db.query(Account).filter_by(public_slug=slug, public_enabled=True).first()


def create_account(db, **values):
    account = Account(**values)
    db.add(account)
    db.flush()
    return account


def session_by_hash(db, token_hash):
    return db.get(LoginSession, token_hash)


def revoke_session(db, token_hash):
    db.query(LoginSession).filter_by(token_hash=token_hash).delete()


def revoke_account_sessions(db, account_id):
    db.query(LoginSession).filter_by(account_id=account_id).delete()


def revoke_account_recovery(db, account_id):
    db.query(PasswordReset).filter_by(account_id=account_id).delete()


def create_session(db, **values):
    db.add(LoginSession(**values))


def consume_throttle(db, bucket, limit):
    if not db.get(Throttle, bucket):
        try:
            with db.begin_nested():
                db.add(Throttle(key=bucket, count=0))
                db.flush()
        except IntegrityError:
            pass
    changed = db.execute(update(Throttle).where(Throttle.key == bucket, Throttle.count < limit).values(count=Throttle.count + 1))
    db.commit()
    return changed.rowcount == 1


def save(db):
    db.commit()


def rollback(db):
    db.rollback()
