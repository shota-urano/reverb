from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    stage: Optional[str]
    message: str
    retryable: Optional[bool]


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class BackendError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        stage: Optional[str] = None,
        retryable: Optional[bool] = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.stage = stage
        self.retryable = retryable


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BackendError)
    async def handle_backend_error(_: Request, exc: BackendError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "stage": exc.stage,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTP_ERROR",
                    "stage": None,
                    "message": str(exc.detail),
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "stage": None,
                    "message": str(exc),
                    "retryable": False,
                }
            },
        )
