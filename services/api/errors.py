import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger("api")

STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "TOO_LARGE",
    422: "VALIDATION_ERROR",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def not_found(what="资源"):
    return ApiError(404, "NOT_FOUND", f"{what}不存在")


def forbidden():
    return ApiError(403, "FORBIDDEN", "权限不足")


def error_response(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status)


def install(app: FastAPI):
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        code = STATUS_CODES.get(exc.status_code, "ERROR")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return error_response(500, "INTERNAL", "服务器内部错误")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"] if p != "body")
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return error_response(422, "VALIDATION_ERROR", message)
