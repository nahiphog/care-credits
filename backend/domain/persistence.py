"""Storage-independent conflict raised when a persisted uniqueness rule wins a race."""
class PersistenceConflict(Exception):
    pass
