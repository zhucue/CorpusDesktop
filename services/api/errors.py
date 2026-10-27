"""Stable API errors without credentials, SQL text or validation input values."""

from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable=False):
        self.status, self.code, self.message, self.retryable = (
            status,
            code,
            message,
            retryable,
        )


def install_error_handlers(app):
    @app.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse(
            {
                "code": error.code,
                "message": error.message,
                "request_id": str(uuid4()),
                "field_errors": [],
                "retryable": error.retryable,
            },
            status_code=error.status,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        fields = [
            {"field": ".".join(map(str, item["loc"])), "message": "Invalid value"}
            for item in error.errors()
        ]
        return JSONResponse(
            {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request",
                "request_id": str(uuid4()),
                "field_errors": fields,
                "retryable": False,
            },
            status_code=422,
        )
