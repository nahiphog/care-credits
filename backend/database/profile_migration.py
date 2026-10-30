"""Explicit additive v17 -> v18 migration. Never invoked from request handlers."""
from sqlalchemy import select, exists
from models.account import Account
from models.profile import AccountProfile, PROFILE_DEFAULTS


def upgrade_profile_schema(db):
    """Backfill only missing profiles, preserving IDs, slugs and canonical edits.

    The caller owns commit/rollback and version stamping. Existing account columns
    remain intact for rollback; this migration never reads through ORM relationships.
    """
    target = AccountProfile.__table__
    accounts = Account.__table__
    target.create(bind=db.connection(), checkfirst=True)
    fields = ['account_id', *PROFILE_DEFAULTS]
    source = select(accounts.c.id, *(accounts.c[field] for field in PROFILE_DEFAULTS)).where(
        ~exists().where(target.c.account_id == accounts.c.id)
    )
    db.execute(target.insert().from_select(fields, source))
    db.flush()
    db.expire_all()
