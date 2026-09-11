from unittest.mock import MagicMock, patch


def test_query_graph_formats_neighbors():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.graph_entity.return_value = {
        "name": "Jane", "type": "person",
        "edges": [
            {"relation": "works_at", "other": "Acme", "direction": "out"},
            {"relation": "manages", "other": "Q3 project", "direction": "out"},
        ],
    }
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.query_graph("Jane")
    assert "Jane" in out and "Acme" in out and "works_at" in out
    assert "Q3 project" in out


def test_query_graph_unknown_entity():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.graph_entity.return_value = None
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.query_graph("Nobody")
    assert "nothing" in out.lower()


def test_analyze_gaps_entity_flags_missing_relation():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    # a person with NO works_at and NO knows -> both flagged
    store.graph_entity.return_value = {
        "name": "Jane", "type": "person",
        "edges": [{"relation": "owns", "other": "Car", "direction": "out"}],
    }
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.analyze_gaps("Jane")
    assert "works_at" in out or "knows" in out       # missing expected relation surfaced


def test_analyze_gaps_unknown_entity():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.graph_entity.return_value = None
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.analyze_gaps("Nobody")
    assert "nothing" in out.lower()


def test_analyze_gaps_whole_graph_lists_sparse():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.sparse_entities.return_value = [
        {"name": "Orphan", "type": "thing", "edge_count": 0},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.analyze_gaps("")
    assert "Orphan" in out


def test_analyze_gaps_empty_graph():
    import modules.graph_memory_tools as gmt
    store = MagicMock()
    store.sparse_entities.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=store):
        out = gmt.analyze_gaps("")
    assert "empty" in out.lower()


def test_graph_tools_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.graph_memory_tools" in sys.modules:
        del sys.modules["modules.graph_memory_tools"]
    set_loading_module("graph_memory_tools")
    try:
        import modules.graph_memory_tools  # noqa: F401
    finally:
        set_loading_module("")
    tools = list_tools()
    assert "query_graph" in tools
    assert "analyze_gaps" in tools
