import textwrap
from pathlib import Path
import pytest
from core.loader import load_modules
from core.registry import list_tools


def test_loads_valid_module(tmp_path):
    mod = tmp_path / "my_mod.py"
    mod.write_text(textwrap.dedent("""
        from core.registry import tool

        @tool(description="hello tool")
        def hello() -> str:
            return "hi"
    """))
    load_modules(tmp_path)
    assert "hello" in list_tools()


def test_skips_broken_module(tmp_path, caplog):
    bad = tmp_path / "bad_mod.py"
    bad.write_text("raise RuntimeError('oops')")
    import logging
    with caplog.at_level(logging.WARNING):
        load_modules(tmp_path)
    assert "bad_mod" in caplog.text


def test_skips_dunder_files(tmp_path):
    (tmp_path / "__init__.py").write_text("")
    load_modules(tmp_path)
    assert list_tools() == {}


def test_empty_directory_loads_fine(tmp_path):
    load_modules(tmp_path)  # must not raise
    assert list_tools() == {}


def test_reload_refreshes_package_attribute(tmp_path):
    """A re-exec'd module must be reachable as `modules.X`, not just in sys.modules.

    `import modules.X as alias` resolves through getattr(modules, "X"), so
    leaving that attribute stale hands out the previous module object while
    `from modules.X import ...` (and patch("modules.X.…")) see the new one.
    """
    import sys
    from core.registry import clear_tools

    mod = tmp_path / "reload_mod.py"
    mod.write_text("VALUE = 1\n")
    load_modules(tmp_path)
    first = sys.modules["modules.reload_mod"]

    # The registry is cleared between tests, which is exactly when the loader
    # re-execs an already-imported module.
    clear_tools()
    # Different byte length as well as content: a same-size rewrite within the
    # same mtime tick would let the cached .pyc win over the new source.
    mod.write_text("VALUE = 200\n")
    load_modules(tmp_path)
    try:
        import modules.reload_mod as alias
        assert alias is sys.modules["modules.reload_mod"]
        assert alias is not first
        assert alias.VALUE == 200
    finally:
        sys.modules.pop("modules.reload_mod", None)
        try:
            delattr(sys.modules["modules"], "reload_mod")
        except AttributeError:
            pass
