from __future__ import annotations
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Literal

logger = logging.getLogger(__name__)


@dataclass
class ModelEntry:
    name: str
    priority: int          # 1 = LIGHT, 3 = HEAVY
    vram_gb: float
    load_fn: Callable[[], None]
    unload_fn: Callable[[], None]
    state: Literal["gpu", "unloaded"] = "unloaded"


class VRAMBroker:
    def __init__(self) -> None:
        self._models: dict[str, ModelEntry] = {}
        self._evicted: list[str] = []
        self._lock = threading.RLock()

    def register(self, entry: ModelEntry) -> None:
        with self._lock:
            if entry.name in self._models:
                return
            self._models[entry.name] = entry

    def request(self, name: str) -> None:
        with self._lock:
            if name not in self._models:
                raise KeyError(f"VRAMBroker: model {name!r} is not registered")
            entry = self._models[name]
            if entry.state == "gpu":
                return

            # Release any active heavy model first
            if entry.priority == 3:
                for m in list(self._models.values()):
                    if m.priority == 3 and m.state == "gpu" and m.name != name:
                        logger.info("Releasing active heavy model %r before loading %r", m.name, name)
                        m.unload_fn()
                        m.state = "unloaded"
                self._evicted = []

            # Evict lower-priority models to make room
            for m in sorted(self._models.values(), key=lambda x: x.priority):
                if m.priority < entry.priority and m.state == "gpu":
                    logger.info("Evicting %r (priority %d) for %r", m.name, m.priority, name)
                    m.unload_fn()
                    m.state = "unloaded"
                    self._evicted.append(m.name)

            _empty_cuda_cache()
            entry.load_fn()
            entry.state = "gpu"
            logger.info("Loaded %r on GPU", name)

    def release(self, name: str) -> None:
        with self._lock:
            entry = self._models.get(name)
            if entry is None or entry.state == "unloaded":
                return
            entry.unload_fn()
            entry.state = "unloaded"
            _empty_cuda_cache()
            logger.info("Released %r", name)

            # Restore evicted models in reverse order (highest priority first)
            for evicted_name in reversed(self._evicted):
                m = self._models.get(evicted_name)
                if m and m.state == "unloaded":
                    logger.info("Restoring evicted model %r", evicted_name)
                    m.load_fn()
                    m.state = "gpu"
            self._evicted = []

    def status(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
                used = torch.cuda.memory_allocated(0) / 1024 ** 3
            else:
                total = used = 0.0
        except Exception:
            total = used = 0.0

        with self._lock:
            active_heavy = next(
                (m.name for m in self._models.values() if m.priority == 3 and m.state == "gpu"),
                None,
            )
            models_snapshot = {
                m.name: {"state": m.state, "vram_gb": m.vram_gb if m.state == "gpu" else 0.0}
                for m in self._models.values()
            }
        return {
            "studio_mode": active_heavy is not None,
            "active_heavy": active_heavy,
            "models": models_snapshot,
            "vram_used_gb": round(used, 2),
            "vram_total_gb": round(total, 2),
        }


def _empty_cuda_cache() -> None:
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


_broker: VRAMBroker | None = None


def get_vram_broker() -> VRAMBroker:
    global _broker
    if _broker is None:
        _broker = VRAMBroker()
    return _broker
