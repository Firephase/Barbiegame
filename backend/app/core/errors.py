"""Typed errors.

The app never fakes a result when a capability is missing.  It raises one of
these, and the API surfaces the *reason* to the user.
"""
from __future__ import annotations


class WorkspaceError(Exception):
    """Base class. ``status`` maps onto the HTTP response code."""

    status = 500
    code = "workspace_error"

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class ProviderUnavailable(WorkspaceError):
    """A capability was requested but no configured provider can serve it.

    This is deliberately *not* silently swallowed: telling the user "no web
    search provider is configured" is honest; answering from model memory and
    calling it research is not.
    """

    status = 503
    code = "provider_unavailable"


class ProviderFailed(WorkspaceError):
    status = 502
    code = "provider_failed"


class AccessDenied(WorkspaceError):
    """Fetching was refused for policy reasons (robots.txt, paywall, login)."""

    status = 403
    code = "access_denied"


class NotFound(WorkspaceError):
    status = 404
    code = "not_found"


class BadRequest(WorkspaceError):
    status = 400
    code = "bad_request"


class UnsupportedContent(WorkspaceError):
    status = 415
    code = "unsupported_content"
