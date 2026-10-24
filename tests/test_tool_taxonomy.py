"""Tests for the tool information architecture (category → subgroup → tool).

The dashboard Tools menu is driven by ``GET /api/tools/taxonomy``, which is
built from ``core/tool_taxonomy.py``. These tests keep the map honest:

* every ``@tool`` in ``modules/*.py`` has exactly one home;
* there is no catch-all category;
* destructive subgroups stay last in their category;
* the API exposes the tree, honours per-tool overrides and never ships an
  "Uncategorised" bucket in a clean checkout.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from core.tool_taxonomy import (
    CATEGORIES,
    DANGER_SUBGROUPS,
    UNCATEGORISED,
    audit,
    build,
    home_of,
)

MODULES = Path(__file__).resolve().parent.parent / "modules"


def _declared_tools() -> list[str]:
    """Every @tool-decorated function name in modules/*.py, without importing."""
    found: list[str] = []
    for path in sorted(MODULES.glob("*.py")):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if not line.strip().startswith("@tool"):
                continue
            for j in range(i + 1, min(i + 16, len(lines))):
                m = re.match(r"\s*(?:async\s+)?def\s+(\w+)", lines[j])
                if m:
                    found.append(m.group(1))
                    break
    return found


async def _get(path: str):
    from core.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        return await ac.get(path)


# ---------------------------------------------------------------- static map


def test_every_declared_tool_has_a_home():
    declared = _declared_tools()
    assert declared, "no @tool decorators found — did modules/ move?"
    assert len(declared) == len(set(declared)), "duplicate tool name across modules"
    result = audit(declared)
    assert result["missing"] == [], "tools with no category — add them to CATEGORIES"
    assert result["stale"] == [], "CATEGORIES lists tools that no longer exist"


def test_no_catch_all_category():
    assert UNCATEGORISED not in CATEGORIES
    assert all(subs for subs in CATEGORIES.values()), "empty category"
    assert all(names for subs in CATEGORIES.values() for names in subs.values()), "empty subgroup"


def test_structure_is_two_levels_and_balanced():
    # 6–9 top-level categories keeps the rail scannable without cramming.
    assert 6 <= len(CATEGORIES) <= 9
    assert sum(len(subs) for subs in CATEGORIES.values()) == 42
    for cat, subs in CATEGORIES.items():
        assert 2 <= len(subs) <= 7, f"{cat} has {len(subs)} subgroups"
        total = sum(len(names) for names in subs.values())
        assert total <= 30, f"{cat} holds {total} tools — split it"


def test_destructive_subgroups_are_last():
    assert DANGER_SUBGROUPS, "expected at least one flagged subgroup"
    for cat, subs in CATEGORIES.items():
        names = list(subs)
        for danger in [s for s in names if s in DANGER_SUBGROUPS]:
            assert names[-1] == danger, f"{danger!r} must be the last subgroup of {cat!r}"


def test_names_are_unique_across_categories():
    seen: dict[str, str] = {}
    for cat, subs in CATEGORIES.items():
        for sub, names in subs.items():
            for name in names:
                assert name not in seen, f"{name} listed in {seen[name]} and {cat}/{sub}"
                seen[name] = f"{cat}/{sub}"
    assert len(seen) == 170


# ---------------------------------------------------------------- build()


def test_build_orders_and_counts():
    tree = build({"save_memory": {"name": "save_memory"}, "recommend_models": {"name": "recommend_models"}})
    assert [c["name"] for c in tree] == ["Memory & Agents", "Home & System"]
    mem = tree[0]
    assert mem["count"] == 1
    assert mem["subgroups"][0]["name"] == "Facts & Recall"
    assert mem["subgroups"][0]["tools"][0]["name"] == "save_memory"
    sys_cat = tree[1]
    assert [t["name"] for s in sys_cat["subgroups"] for t in s["tools"]] == ["recommend_models"]


def test_build_drops_empty_categories():
    tree = build({"save_memory": {"name": "save_memory"}})
    assert [c["name"] for c in tree] == ["Memory & Agents"]
    assert tree[0]["subgroups"][0]["danger"] is False


def test_build_honours_override():
    tree = build({"brand_new": {"name": "brand_new", "category": "Zeta", "subgroup": "Nested"}})
    assert tree[-1]["name"] == "Zeta"
    assert tree[-1]["subgroups"][0]["name"] == "Nested"


def test_build_flags_unknown_tools():
    tree = build({"ghost": {"name": "ghost"}})
    assert tree[-1]["name"] == UNCATEGORISED
    assert tree[-1]["subgroups"][0]["tools"][0]["name"] == "ghost"


def test_audit_reports_both_directions():
    result = audit(["save_memory", "not_a_real_tool"])
    assert result["missing"] == ["not_a_real_tool"]
    assert "save_memory" not in result["stale"]
    assert len(result["stale"]) == 169


def test_home_of():
    assert home_of("recommend_models") == ("Home & System", "Utilities")
    assert home_of("attack_wps") == ("Security & Privacy", "⚠ Wireless Testing")
    assert home_of("nope") is None


# ---------------------------------------------------------------- decorator


def test_decorator_inherits_taxonomy_home():
    from core.registry import _tools, tool

    @tool("test tool")
    def save_memory() -> str:  # noqa: D401 — name intentionally matches a real tool
        return ""

    assert _tools["save_memory"]["category"] == "Memory & Agents"
    assert _tools["save_memory"]["subgroup"] == "Facts & Recall"


def test_decorator_override_wins():
    from core.registry import _tools, tool

    @tool("test tool", category="Custom", subgroup="Deep")
    def my_custom_tool() -> str:
        return ""

    assert _tools["my_custom_tool"]["category"] == "Custom"
    assert _tools["my_custom_tool"]["subgroup"] == "Deep"


def test_unassigned_tool_falls_back_to_uncategorised():
    from core.registry import _tools, tool

    @tool("test tool")
    def never_categorised() -> str:
        return ""

    assert _tools["never_categorised"]["category"] == UNCATEGORISED


def test_register_tool_passthrough():
    from core.registry import _tools, register_tool

    ok = register_tool(
        name="mcp_thing",
        fn=lambda: "",
        description="d",
        parameters={"type": "object", "properties": {}},
        module="mcp:test",
        category="Custom",
        subgroup="Deep",
    )
    assert ok
    assert _tools["mcp_thing"]["category"] == "Custom"


# ---------------------------------------------------------------- API


@pytest.mark.asyncio
async def test_taxonomy_endpoint_covers_everything():
    r = await _get("/api/tools/taxonomy")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 170
    assert len(data["categories"]) == 8
    assert [c["name"] for c in data["categories"]][0] == "Memory & Agents"
    assert all(c["name"] != UNCATEGORISED for c in data["categories"])

    names = [t["name"] for c in data["categories"] for s in c["subgroups"] for t in s["tools"]]
    assert len(names) == len(set(names)) == 170
    assert sum(s["count"] for c in data["categories"] for s in c["subgroups"]) == 170

    danger = [s for c in data["categories"] for s in c["subgroups"] if s["danger"]]
    assert [s["name"] for s in danger] == ["⚠ Wireless Testing"]


@pytest.mark.asyncio
async def test_tools_endpoint_exposes_home():
    r = await _get("/api/tools")
    assert r.status_code == 200
    by_name = {t["name"]: t for t in r.json()["tools"]}
    assert by_name["recommend_models"]["category"] == "Home & System"
    assert by_name["recommend_models"]["subgroup"] == "Utilities"
    assert by_name["attack_wps"]["subgroup"] == "⚠ Wireless Testing"
