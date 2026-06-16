import re
import pytest
from unittest.mock import patch


def test_get_time_returns_hhmm():
    from modules.utility_tools import get_time
    result = get_time()
    assert re.match(r"^\d{2}:\d{2}$", result)


def test_get_current_date_contains_year():
    from modules.utility_tools import get_current_date
    result = get_current_date()
    assert "2025" in result or "2026" in result or "2027" in result


def test_get_current_date_contains_day_of_week():
    from modules.utility_tools import get_current_date
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    result = get_current_date()
    assert any(d in result for d in days)


def test_list_tools_returns_tool_names():
    from modules.utility_tools import list_tools
    from core.registry import tool

    @tool(description="dummy tool for test")
    def _dummy_list_tools_test() -> str:
        return "ok"

    result = list_tools()
    assert "_dummy_list_tools_test" in result
    assert "dummy tool for test" in result


def test_list_tools_no_tools_message():
    from modules.utility_tools import list_tools
    from core import registry
    original = registry._tools.copy()
    registry._tools.clear()
    try:
        result = list_tools()
        assert "No tools" in result
    finally:
        registry._tools.update(original)


def test_list_tools_includes_count():
    from modules.utility_tools import list_tools
    from core.registry import tool

    @tool(description="another dummy")
    def _dummy_count_tool() -> str:
        return "ok"

    result = list_tools()
    assert "tools available" in result
