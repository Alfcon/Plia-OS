import pytest


@pytest.fixture(autouse=True)
def reset_registry():
    from core import registry
    registry.clear_tools()
    yield
    registry.clear_tools()


@pytest.fixture(autouse=True)
def reset_events():
    from core import events
    events.clear_subscribers()
    yield
    events.clear_subscribers()
