"""Unit tests for is_auth_error in calendar_errors."""
from __future__ import annotations


from fsm.platform.calendar_errors import is_auth_error


class RefreshError(Exception):
    """Mimics google.auth.exceptions.RefreshError by matching its type name."""


class _FakeHttpError401(Exception):
    """Mimics googleapiclient.errors.HttpError with a 401 resp.status."""

    class _Resp:
        status = 401

    resp = _Resp()


class _FakeHttpError403(Exception):
    """Mimics an HttpError with a non-401 status."""

    class _Resp:
        status = 403

    resp = _Resp()


def test_refresh_error_type_name_returns_true():
    exc = RefreshError("Token has been expired or revoked.")
    assert is_auth_error(exc) is True


def test_invalid_grant_in_message_returns_true():
    exc = RuntimeError("Error: invalid_grant - Token has been expired.")
    assert is_auth_error(exc) is True


def test_http_error_401_returns_true():
    exc = _FakeHttpError401("401 Unauthorized")
    assert is_auth_error(exc) is True


def test_http_error_403_returns_false():
    exc = _FakeHttpError403("403 Forbidden")
    assert is_auth_error(exc) is False


def test_generic_runtime_error_returns_false():
    exc = RuntimeError("calendar unavailable")
    assert is_auth_error(exc) is False


def test_value_error_returns_false():
    exc = ValueError("bad argument")
    assert is_auth_error(exc) is False
