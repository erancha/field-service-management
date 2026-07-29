"""HTTP status mapping for assist domain errors."""
from __future__ import annotations

import pytest
from fastapi import Request

from fsm.assist.domain.errors import AssistError, ConversationAlreadyOpen
from fsm.platform.api.assist_errors import handle_assist_error


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


@pytest.mark.parametrize("error_type", AssistError.__subclasses__())
def test_every_assist_error_maps_to_a_client_status(error_type: type[AssistError]) -> None:
    """Guards the mapping's exhaustiveness claim: an unmapped subtype raises KeyError here."""
    response = handle_assist_error(_request(), error_type("detail"))

    assert 400 <= response.status_code < 500


def test_starting_a_second_open_conversation_is_a_conflict() -> None:
    response = handle_assist_error(_request(), ConversationAlreadyOpen("customer"))

    assert response.status_code == 409
