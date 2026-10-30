"""Rate-limit policy over an atomic persistent counter."""
import time
from domain.errors import DomainError
from domain.passwords import digest
from repository.account_repository import consume_throttle


def throttle(db, key, limit=20, window=300):
    bucket = digest(key) + ':' + str(int(time.time()) // window)
    if not consume_throttle(db, bucket, limit):
        raise DomainError(429, 'Too many requests. Please try again later.')
