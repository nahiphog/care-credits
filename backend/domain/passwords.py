"""Password hashing and token digests, independent of transport and persistence."""
import hashlib
import secrets

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


