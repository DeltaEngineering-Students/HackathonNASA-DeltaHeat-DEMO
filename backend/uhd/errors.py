"""API error type and JSON error envelope: ``{"error": code, "message": text, "details"?: ...}``."""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str = "", details: Any = None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code
        self.details = details

    def body(self) -> dict[str, Any]:
        b: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details is not None:
            b["details"] = self.details
        return b


def bad_request(code: str, message: str, details: Any = None) -> APIError:
    return APIError(422, code, message, details)


def not_found(code: str, message: str) -> APIError:
    return APIError(404, code, message)
