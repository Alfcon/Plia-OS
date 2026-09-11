from unittest.mock import MagicMock, patch


def test_consolidate_now_reports_stats():
    import modules.consolidation_tools as ct
    with patch("agents.consolidation.run_consolidation",
               return_value={"synthesized": 3, "skipped": 1, "gaps": 2}):
        out = ct.consolidate_now()
    assert "3" in out and "2" in out


def test_consolidate_now_defensive():
    import modules.consolidation_tools as ct
    with patch("agents.consolidation.run_consolidation", side_effect=RuntimeError("boom")):
        out = ct.consolidate_now()
    assert isinstance(out, str)
    assert "couldn't" in out.lower() or "error" in out.lower() or "failed" in out.lower()


def test_consolidate_now_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.consolidation_tools" in sys.modules:
        del sys.modules["modules.consolidation_tools"]
    set_loading_module("consolidation_tools")
    try:
        import modules.consolidation_tools  # noqa: F401
    finally:
        set_loading_module("")
    assert "consolidate_now" in list_tools()


def test_query_graph_shows_summary():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.graph_entity.return_value = {
        "name": "Jane", "type": "person", "summary": "Jane works at Acme.",
        "edges": [{"relation": "works_at", "other": "Acme", "direction": "out"}],
    }
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.query_graph("Jane")
    assert "Jane works at Acme." in out
    assert "works_at" in out


def test_query_graph_no_summary_still_lists_edges():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.graph_entity.return_value = {
        "name": "Acme", "type": "organization", "summary": None,
        "edges": [{"relation": "works_at", "other": "Jane", "direction": "in"}],
    }
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.query_graph("Acme")
    assert "Jane" in out
    assert "Summary:" not in out
