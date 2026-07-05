import importlib

import pytest

CONTEXTS = [
    "fsm",
    "fsm.identity",
    "fsm.scheduling",
    "fsm.calendar",
    "fsm.notifications",
    "fsm.platform",
    "fsm.platform.calendar_bridge",
    "fsm.shared",
]


@pytest.mark.parametrize("module_name", CONTEXTS)
def test_context_is_importable(module_name):
    assert importlib.import_module(module_name) is not None
