from unittest.mock import MagicMock, patch


def _resp(content):
    r = MagicMock()
    r.json.return_value = {"message": {"content": content}}
    return r


EDGES = [
    {"relation": "works_at", "other": "Acme", "direction": "out"},
    {"relation": "manages", "other": "Q3 project", "direction": "out"},
]


def test_synthesize_entity_returns_summary():
    from agents.consolidation import synthesize_entity
    with patch("httpx.post", return_value=_resp("Jane works at Acme and manages Q3.")):
        s = synthesize_entity("Jane", "person", EDGES)
    assert "Acme" in s


def test_synthesize_entity_no_edges_no_call():
    from agents.consolidation import synthesize_entity
    with patch("httpx.post") as m:
        s = synthesize_entity("Jane", "person", [])
    assert s == ""
    m.assert_not_called()


def test_synthesize_entity_http_error_returns_empty():
    from agents.consolidation import synthesize_entity
    with patch("httpx.post", side_effect=RuntimeError("boom")):
        s = synthesize_entity("Jane", "person", EDGES)
    assert s == ""


def test_run_consolidation_synthesizes_candidates():
    from agents import consolidation
    store = MagicMock()
    store.entities_needing_synthesis.return_value = [
        {"id": 1, "name": "Jane", "type": "person"},
        {"id": 2, "name": "Acme", "type": "organization"},
    ]
    store.graph_entity.side_effect = lambda n: {"name": n, "type": "x", "summary": None, "edges": EDGES}
    store.sparse_entities.return_value = [{"name": "Orphan", "type": "thing", "edge_count": 0}]
    with patch("agents.consolidation.synthesize_entity", return_value="a summary"), \
         patch("agents.memory_store.get_memory_store", return_value=store):
        stats = consolidation.run_consolidation()
    assert stats["synthesized"] == 2
    assert stats["gaps"] == 1
    assert store.set_entity_summary.call_count == 2


def test_run_consolidation_skips_failing_entity():
    from agents import consolidation
    store = MagicMock()
    store.entities_needing_synthesis.return_value = [
        {"id": 1, "name": "Jane", "type": "person"},
        {"id": 2, "name": "Acme", "type": "organization"},
    ]
    store.graph_entity.side_effect = lambda n: {"name": n, "type": "x", "summary": None, "edges": EDGES}
    store.sparse_entities.return_value = []
    def _synth(name, type, edges):
        if name == "Jane":
            raise RuntimeError("boom")
        return "ok"
    with patch("agents.consolidation.synthesize_entity", side_effect=_synth), \
         patch("agents.memory_store.get_memory_store", return_value=store):
        stats = consolidation.run_consolidation()
    assert stats["synthesized"] == 1     # Acme done
    assert stats["skipped"] == 1         # Jane skipped
    store.set_entity_summary.assert_called_once_with(2, "ok")


def test_run_consolidation_empty_summary_not_stored():
    from agents import consolidation
    store = MagicMock()
    store.entities_needing_synthesis.return_value = [{"id": 1, "name": "Jane", "type": "person"}]
    store.graph_entity.side_effect = lambda n: {"name": n, "type": "x", "summary": None, "edges": EDGES}
    store.sparse_entities.return_value = []
    with patch("agents.consolidation.synthesize_entity", return_value=""), \
         patch("agents.memory_store.get_memory_store", return_value=store):
        stats = consolidation.run_consolidation()
    assert stats["synthesized"] == 0
    store.set_entity_summary.assert_not_called()


def test_run_consolidation_never_raises():
    from agents import consolidation
    with patch("agents.memory_store.get_memory_store", side_effect=RuntimeError("boom")):
        stats = consolidation.run_consolidation()
    assert stats == {"synthesized": 0, "skipped": 0, "gaps": 0}


def test_run_consolidation_late_failure_returns_partial_stats():
    # sparse_entities raises AFTER one entity was synthesized+stored:
    # must NOT raise, and returns the partial stats (synthesized already counted).
    from agents import consolidation
    store = MagicMock()
    store.entities_needing_synthesis.return_value = [{"id": 1, "name": "Jane", "type": "person"}]
    store.graph_entity.side_effect = lambda n: {"name": n, "type": "x", "summary": None, "edges": EDGES}
    store.sparse_entities.side_effect = RuntimeError("boom")
    with patch("agents.consolidation.synthesize_entity", return_value="a summary"), \
         patch("agents.memory_store.get_memory_store", return_value=store):
        stats = consolidation.run_consolidation()   # must not raise
    assert stats["synthesized"] == 1   # partial stats: the real write is reflected
    assert stats["gaps"] == 0          # gap count never completed


def test_run_consolidation_malformed_edge_is_skipped():
    # graph_entity returns an edge missing keys -> synthesize path raises internally,
    # per-entity except catches it, entity skipped, no raise.
    from agents import consolidation
    store = MagicMock()
    store.entities_needing_synthesis.return_value = [{"id": 1, "name": "Jane", "type": "person"}]
    store.graph_entity.side_effect = lambda n: {"name": n, "type": "x", "summary": None,
                                                "edges": [{"direction": "out"}]}  # missing relation/other
    store.sparse_entities.return_value = []
    # use the REAL synthesize_entity so the malformed edge is actually processed
    with patch("agents.memory_store.get_memory_store", return_value=store), \
         patch("httpx.post") as m:
        stats = consolidation.run_consolidation()   # must not raise
    assert stats["skipped"] == 1
    assert stats["synthesized"] == 0
    m.assert_not_called()   # malformed edge fails before any HTTP call


def test_run_consolidation_candidate_missing_key_skipped():
    # a candidate dict missing "name"/"type" must be caught per-entity, not crash the pass.
    from agents import consolidation
    store = MagicMock()
    store.entities_needing_synthesis.return_value = [{"id": 1}]  # missing name/type
    store.sparse_entities.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=store):
        stats = consolidation.run_consolidation()   # must not raise
    assert stats["skipped"] == 1
    assert stats["synthesized"] == 0
