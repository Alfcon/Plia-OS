"""Event bus stub — full implementation in Task 4."""

_subscribers: dict = {}


def clear_subscribers() -> None:
    """For testing only."""
    _subscribers.clear()
