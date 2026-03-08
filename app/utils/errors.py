from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details for HTTP APIs."""

    type: str = Field(default="about:blank", description="문제 유형을 식별하는 URI")
    title: str = Field(description="짧은 사람 읽기용 요약")
    status: int = Field(description="HTTP 상태 코드")
    detail: str | None = Field(default=None, description="구체적인 오류 설명")
    instance: str | None = Field(default=None, description="요청 식별자 (Correlation ID)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "type": "about:blank",
                    "title": "Not Found",
                    "status": 404,
                    "detail": "Description not found for cog_image_id: abc-123",
                    "instance": "550e8400-e29b-41d4-a716-446655440000",
                }
            ]
        }
    }


_STATUS_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def _get_correlation_id(request: Request) -> str | None:
    return getattr(getattr(request, "state", None), "correlation_id", None)


class DescriptorError(HTTPException):
    """Application-specific error that produces RFC 7807 responses."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.code = code
        self.error_message = message
        self.details = details
        super().__init__(status_code=status_code, detail=message)


async def descriptor_error_handler(request: Request, exc: DescriptorError) -> JSONResponse:
    body = {
        "type": f"https://problems.cognito-descriptor.io/{exc.code.lower().replace('_', '-')}",
        "title": _STATUS_TITLES.get(exc.status_code, "Error"),
        "status": exc.status_code,
        "detail": exc.error_message,
        "instance": _get_correlation_id(request),
    }
    if exc.details:
        body["errors"] = exc.details
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "about:blank",
            "title": _STATUS_TITLES.get(exc.status_code, "Error"),
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": _get_correlation_id(request),
        },
        media_type="application/problem+json",
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        errors.append(
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://problems.cognito-descriptor.io/validation-error",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": f"요청 데이터 검증에 실패했습니다 ({len(errors)}건의 오류)",
            "instance": _get_correlation_id(request),
            "errors": errors,
        },
        media_type="application/problem+json",
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    import structlog

    logger = structlog.get_logger()
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "type": "https://problems.cognito-descriptor.io/internal-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "서버 내부 오류가 발생했습니다",
            "instance": _get_correlation_id(request),
        },
        media_type="application/problem+json",
    )
