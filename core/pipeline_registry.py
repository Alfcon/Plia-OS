import asyncio

_state: str = "stopped"
_task: "asyncio.Task | None" = None


def get_state() -> str:
    return _state


def set_state(state: str) -> None:
    global _state
    _state = state


def get_task() -> "asyncio.Task | None":
    return _task


def set_task(task: "asyncio.Task | None") -> None:
    global _task
    _task = task
