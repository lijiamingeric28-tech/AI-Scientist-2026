class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **details):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.details}
