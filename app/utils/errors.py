from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class DescriptorError(HTTPException):
    """Standard error with {error: {code, message, details}} format."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.code = code
        self.error_message = message
        self.details = details
        super().__init__(status_code=status_code, detail=message)


async def descriptor_error_handler(request: Request, exc: DescriptorError) -> JSONResponse:
    body: dict = {"code": exc.code, "message": exc.error_message}
    if exc.details:
        body["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content={"error": body})
