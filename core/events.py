import asyncio
from collections.abc import Callable

_subscribers: list[Callable] = []


def subscribe(callback: Callable) -> None:
    _subscribers.append(callback)


def unsubscribe(callback: Callable) -> None:
    _subscribers.remove(callback)


async def emit(event_type: str, data: dict) -> None:
    payload = {"type": event_type, **data}
    for callback in list(_subscribers):
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(payload)
            else:
                callback(payload)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Event subscriber error (event=%s)", event_type)


def clear_subscribers() -> None:
    """For testing only."""
    _subscribers.clear()
