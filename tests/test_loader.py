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
