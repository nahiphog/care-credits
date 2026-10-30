"""Atomic recovery token consumption and account/session updates."""
from models import Account, PasswordReset, LoginSession


def issue(db, account_id, token_hash, expires_at):
    db.query(Account).filter_by(id=account_id).with_for_update().one()
    db.query(PasswordReset).filter_by(account_id=account_id).delete()
    db.add(PasswordReset(account_id=account_id, token_hash=token_hash, expires_at=expires_at))
    db.commit()


def revoke(db, token_hash):
    db.query(PasswordReset).filter_by(token_hash=token_hash).delete()
    db.commit()


def consume(db, token_hash, now, password_hash):
    token = db.get(PasswordReset, token_hash)
    if not token or token.expires_at <= now:
        return None
    account = db.query(Account).filter_by(id=token.account_id).with_for_update().one_or_none()
    changed = db.query(PasswordReset).filter(PasswordReset.token_hash == token_hash,
                                           PasswordReset.expires_at > now).delete()
    if not account or changed != 1:
        db.rollback()
        return None
    account.password_hash = password_hash
    db.query(PasswordReset).filter_by(account_id=account.id).delete()
    db.query(LoginSession).filter_by(account_id=account.id).delete()
    # Caller adds the audit event and commits the same transaction.
    return account.id
