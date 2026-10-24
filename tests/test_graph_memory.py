import json
from unittest.mock import MagicMock, patch


def _resp(content):
    r = MagicMock()
    r.json.return_value = {"message": {"content": content}}
    return r


VALID = json.dumps({
    "entities": [{"name": "Jane", "type": "person"}, {"name": "Acme", "type": "organization"}],
    "edges": [{"subject": "Jane", "relation": "works_at", "object": "Acme"}],
})


def test_extract_graph_parses_valid():
    from agents.graph_memory import extract_graph
    with patch("httpx.post", return_value=_resp(VALID)):
        g = extract_graph("Jane works at Acme")
    assert {e["name"] for e in g["entities"]} == {"Jane", "Acme"}
    assert g["edges"][0] == {"subject": "Jane", "relation": "works_at", "object": "Acme"}


def test_extract_graph_normalizes_unknown_vocab():
    from agents.graph_memory import extract_graph
    payload = json.dumps({
        "entities": [{"name": "Jane", "type": "wizard"}],
        "edges": [{"subject": "Jane", "relation": "employed_by", "object": "Acme"}],
    })
    with patch("httpx.post", return_value=_resp(payload)):
        g = extract_graph("x")
    assert g["entities"][0]["type"] == "thing"          # unknown type -> thing
    assert g["edges"][0]["relation"] == "related_to"     # unknown relation -> related_to


def test_extract_graph_drops_malformed_entries():
    from agents.graph_memory import extract_graph
    payload = json.dumps({
        "entities": [{"name": "", "type": "person"}, {"name": "Bob", "type": "person"}],
        "edges": [{"subject": "Bob", "relation": "knows"}, {"subject": "Bob", "relation": "knows", "object": "Al"}],
    })
    with patch("httpx.post", return_value=_resp(payload)):
        g = extract_graph("x")
    assert [e["name"] for e in g["entities"]] == ["Bob"]           # blank name dropped
    assert g["edges"] == [{"subject": "Bob", "relation": "knows", "object": "Al"}]  # incomplete edge dropped


def test_extract_graph_extracts_object_from_prose():
    from agents.graph_memory import extract_graph
    content = 'Here:\n' + VALID + '\nDone.'
    with patch("httpx.post", return_value=_resp(content)):
        g = extract_graph("x")
    assert g["edges"][0]["relation"] == "works_at"


def test_extract_graph_malformed_json_returns_empty():
    from agents.graph_memory import extract_graph
    with patch("httpx.post", return_value=_resp("not json")):
        g = extract_graph("x")
    assert g == {"entities": [], "edges": []}


def test_extract_graph_http_error_returns_empty():
    from agents.graph_memory import extract_graph
    with patch("httpx.post", side_effect=RuntimeError("boom")):
        g = extract_graph("x")
    assert g == {"entities": [], "edges": []}


def test_extract_graph_blank_input_no_call():
    from agents.graph_memory import extract_graph
    with patch("httpx.post") as m:
        g = extract_graph("   ")
    assert g == {"entities": [], "edges": []}
    m.assert_not_called()


def test_ingest_fact_writes_and_counts():
    from agents import graph_memory
    fake_store = MagicMock()
    ids = {}
    def _upsert(name, type):
        return ids.setdefault(name.lower(), len(ids) + 1)
    fake_store.upsert_entity.side_effect = _upsert
    fake_store.add_edge.return_value = True
    with patch("agents.graph_memory.extract_graph", return_value=json.loads(VALID)), \
         patch("agents.memory_store.get_memory_store", return_value=fake_store):
        n = graph_memory.ingest_fact("Jane works at Acme")
    assert n == 1
    fake_store.add_edge.assert_called_once()


def test_ingest_fact_empty_extraction_writes_nothing():
    from agents import graph_memory
    fake_store = MagicMock()
    with patch("agents.graph_memory.extract_graph", return_value={"entities": [], "edges": []}), \
         patch("agents.memory_store.get_memory_store", return_value=fake_store):
        n = graph_memory.ingest_fact("nonsense")
    assert n == 0
    fake_store.add_edge.assert_not_called()


def test_ingest_fact_never_raises():
    from agents import graph_memory
    with patch("agents.graph_memory.extract_graph", side_effect=RuntimeError("boom")):
        assert graph_memory.ingest_fact("x") == 0


def test_extract_graph_null_entities_no_raise():
    from agents.graph_memory import extract_graph
    payload = json.dumps({"entities": None, "edges": []})
    with patch("httpx.post", return_value=_resp(payload)):
        g = extract_graph("x")
    assert g == {"entities": [], "edges": []}


def test_extract_graph_nonlist_edges_no_raise():
    from agents.graph_memory import extract_graph
    payload = json.dumps({"entities": [], "edges": 5})
    with patch("httpx.post", return_value=_resp(payload)):
        g = extract_graph("x")
    assert g == {"entities": [], "edges": []}


def test_extract_graph_nondict_toplevel_no_raise():
    from agents.graph_memory import extract_graph
    with patch("httpx.post", return_value=_resp("[1, 2, 3]")):
        g = extract_graph("x")
    assert g == {"entities": [], "edges": []}


def test_ingest_fact_upserts_standalone_entity():
    # an entity that is NOT an edge endpoint must still be upserted
    from agents import graph_memory
    fake_store = MagicMock()
    fake_store.upsert_entity.side_effect = lambda name, type: 1
    fake_store.add_edge.return_value = True
    graph = {
        "entities": [{"name": "Solo", "type": "person"}],
        "edges": [],
    }
    with patch("agents.graph_memory.extract_graph", return_value=graph), \
         patch("agents.memory_store.get_memory_store", return_value=fake_store):
        n = graph_memory.ingest_fact("Solo exists")
    assert n == 0
    # Solo (a non-endpoint entity) was still upserted
    upserted = [c.args[0] for c in fake_store.upsert_entity.call_args_list]
    assert "Solo" in upserted


def test_ingest_fact_counts_only_new_edges():
    # add_edge returning False (duplicate triple) must NOT be counted
    from agents import graph_memory
    fake_store = MagicMock()
    fake_store.upsert_entity.side_effect = lambda name, type: hash(name.lower()) & 0xffff
    fake_store.add_edge.side_effect = [True, False]   # first new, second duplicate
    graph = {
        "entities": [],
        "edges": [
            {"subject": "A", "relation": "knows", "object": "B"},
            {"subject": "A", "relation": "knows", "object": "B"},
        ],
    }
    with patch("agents.graph_memory.extract_graph", return_value=graph), \
         patch("agents.memory_store.get_memory_store", return_value=fake_store):
        n = graph_memory.ingest_fact("A knows B")
    assert n == 1   # only the new edge counted
