"""Shared schema constants and identifier defaults."""
import uuid

SCHEMA_VERSION = 19
CANDIDATE_SCHEMA_VERSION = 1

def uid():
    return uuid.uuid4().hex
