import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")


class AppException(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: list[dict[str, str]] | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors
        self.extra = extra or {}
        self.headers = headers
        super().__init__(message)


def field_error(field: str, reason: str, message: str) -> dict[str, str]:
    return {"field": field, "reason": reason, "message": message}


def validation_failed(*errors: dict[str, str]) -> AppException:
    return AppException(400, "VALIDATION_FAILED", "입력값을 확인해 주세요.", field_errors=list(errors))


def unauthorized() -> AppException:
    return AppException(401, "UNAUTHORIZED", "로그인이 필요합니다.")


def forbidden(message: str = "권한이 없습니다.") -> AppException:
    return AppException(403, "FORBIDDEN", message)


def not_found(code: str = "NOT_FOUND", message: str = "대상을 찾을 수 없습니다.") -> AppException:
    return AppException(404, code, message)


def conflict(code: str, message: str, **extra: Any) -> AppException:
    return AppException(409, code, message, extra=extra)


def _body(code: str, message: str, field_errors=None, extra=None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if field_errors:
        body["fieldErrors"] = field_errors
    if extra:
        body.update(extra)
    return body


_STATUS_CODES = {
    401: ("UNAUTHORIZED", "로그인이 필요합니다."),
    403: ("FORBIDDEN", "권한이 없습니다."),
    404: ("NOT_FOUND", "대상을 찾을 수 없습니다."),
    405: ("METHOD_NOT_ALLOWED", "허용되지 않은 요청입니다."),
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app_exc(_: Request, exc: AppException):
        return JSONResponse(
            _body(exc.code, exc.message, exc.field_errors, exc.extra),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            loc = [str(p) for p in err["loc"] if p not in ("body", "query", "path", "form")]
            errors.append(
                field_error(".".join(loc) or "body", str(err["type"]).upper(), "올바른 값을 입력해 주세요.")
            )
        return JSONResponse(_body("VALIDATION_FAILED", "입력값을 확인해 주세요.", errors), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code, message = _STATUS_CODES.get(exc.status_code, ("ERROR", "요청을 처리할 수 없습니다."))
        return JSONResponse(_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(_body("INTERNAL_ERROR", "서버 오류가 발생했습니다."), status_code=500)
