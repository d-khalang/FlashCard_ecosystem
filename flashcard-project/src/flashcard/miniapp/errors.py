"""The API's one error shape: {"error": {"code", "message"}}."""
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

# status -> code, the ones the contract names.
CODES = {
    401: "auth_required",
    403: "not_allowed",
    404: "not_found",
    413: "payload_too_large",
    422: "invalid_request",
    429: "rate_limited",
    503: "generation_failed",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def auth_required() -> ApiError:
    return ApiError(401, "auth_required", "Open the app from Telegram to sign in.")


def not_allowed() -> ApiError:
    return ApiError(403, "not_allowed", "This account cannot use the app yet.")


def not_found() -> ApiError:
    return ApiError(404, "not_found", "Not found.")


def invalid_request(message: str = "Invalid request.") -> ApiError:
    return ApiError(422, "invalid_request", message)


def generation_failed() -> ApiError:
    return ApiError(503, "generation_failed", "Could not generate the card. Try again in a moment.")


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(429, "rate_limited", "Too many requests. Try again shortly.",
                    headers={"Retry-After": str(retry_after)})


def _response(status: int, code: str, message: str, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, error: ApiError):
        return _response(error.status, error.code, error.message, error.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError):
        # Field names only: the values may be what the user typed.
        fields = sorted({".".join(str(part) for part in e["loc"][1:]) or str(e["loc"][0]) for e in error.errors()})
        return _response(422, "invalid_request", "Invalid request: " + ", ".join(fields) + ".")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, error: StarletteHTTPException):
        code = CODES.get(error.status_code, "invalid_request" if error.status_code < 500 else "internal_error")
        return _response(error.status_code, code, {404: "Not found.", 413: "The request is too large."}.get(error.status_code, "Request failed."))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, error: Exception):
        logger.error("Unhandled error in the Mini App API", exc_info=error)
        return _response(500, "internal_error", "Something went wrong.")
