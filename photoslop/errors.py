# SPDX-License-Identifier: Apache-2.0
"""Stable automation-facing error categories shared by CLI and MCP."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSAFE_OPERATION = "unsafe_operation"
    CANCELLED = "cancelled"
    IO_FAILURE = "io_failure"
    INTERNAL = "internal_error"


class StructuredError(ValueError):
    def __init__(self, message: str, code: ErrorCode = ErrorCode.INVALID_INPUT) -> None:
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": str(self)}


def classify_error(exc: BaseException) -> ErrorCode:
    if isinstance(exc, StructuredError):
        return exc.code
    if isinstance(exc, OSError):
        return ErrorCode.IO_FAILURE
    if exc.__class__.__name__ == "CancelledError":
        return ErrorCode.CANCELLED
    message = str(exc).casefold()
    if any(word in message for word in ("not exposed", "unsupported", "does not support")):
        return ErrorCode.UNSUPPORTED_CAPABILITY
    if any(
        word in message
        for word in ("unsafe", "overwrite is disabled", "must stay under", "insecure")
    ):
        return ErrorCode.UNSAFE_OPERATION
    if isinstance(exc, ValueError):
        return ErrorCode.INVALID_INPUT
    return ErrorCode.INTERNAL


class ToolError(StructuredError):
    """MCP-visible error whose string and attributes both carry a stable code."""

    def __str__(self) -> str:
        return f"[{self.code.value}] {super().__str__()}"
