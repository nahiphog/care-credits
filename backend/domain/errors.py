"""Framework-neutral failures translated to HTTP only at the application boundary."""
class DomainError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
