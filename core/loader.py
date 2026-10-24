import importlib.util
import logging
import sys
from pathlib import Path
from core.registry import list_modules, set_loading_module

logger = logging.getLogger(__name__)


def load_modules(directory: Path | None = None) -> None:
    if directory is None:
        directory = Path(__file__).parent.parent / "modules"
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        if f"modules.{path.stem}" in sys.modules and path.stem in list_modules():
            # Already imported as a side effect of another module's
            # `from modules.X import ...` and its tools are registered —
            # exec'ing the file again would re-run side effects and trip
            # "already registered" warnings. (The registry check matters in
            # tests: fixtures clear the registry between tests while
            # sys.modules persists, so the module must be re-exec'd then.)
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        set_loading_module(path.stem)
        try:
            spec.loader.exec_module(module)
            sys.modules[f"modules.{path.stem}"] = module
            # Keep the parent package attribute in sync. `import modules.X as
            # alias` resolves through getattr(modules, "X"), not through
            # sys.modules, so without this the alias silently keeps pointing
            # at the previous module object while `from modules.X import ...`
            # (and patch("modules.X.…")) already see the re-exec'd one.
            parent = sys.modules.get("modules")
            if parent is not None:
                setattr(parent, path.stem, module)
        except Exception:
            logger.warning("Failed to load module %s", path.name, exc_info=True)
        finally:
            set_loading_module("")
