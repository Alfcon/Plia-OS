import pytest
from core import registry, events


@pytest.fixture(autouse=True)
def reset_registry():
    registry.clear_tools()
    yield
    registry.clear_tools()


@pytest.fixture(autouse=True)
def reset_events():
    events.clear_subscribers()
    yield
    events.clear_subscribers()
