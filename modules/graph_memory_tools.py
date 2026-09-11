from __future__ import annotations

from core.registry import tool

# Small heuristic table: relations we'd expect a well-described entity of a
# given type to have at least one of. Used only for gap analysis hints.
_EXPECTED: dict[str, list[str]] = {
    "person": ["works_at", "knows"],
    "organization": ["located_in"],
    "project": ["part_of"],
    "place": ["located_in"],
}


def _fmt_edge(name: str, edge: dict) -> str:
    if edge["direction"] == "out":
        return f"  {name} —{edge['relation']}→ {edge['other']}"
    return f"  {edge['other']} —{edge['relation']}→ {name}"


@tool(
    "Query the knowledge graph for what is connected to an entity and how "
    "(its relationships to people, organizations, projects, etc.). "
    "Pass the entity name."
)
def query_graph(entity: str) -> str:
    from agents.memory_store import get_memory_store
    g = get_memory_store().graph_entity(entity)
    if g is None:
        return f"Nothing in the graph about '{entity}'."
    lines = [f"{g['name']} ({g['type']}):"]
    if g.get("summary"):
        lines.append(f"Summary: {g['summary']}")
    if not g["edges"]:
        lines.append("(no known relationships)")
    else:
        lines += [_fmt_edge(g["name"], e) for e in g["edges"]]
    return "\n".join(lines)


@tool(
    "Analyse gaps in the knowledge graph. With an entity name: shows its relationships and "
    "flags expected relationships it is missing. With no argument: lists sparse/orphan "
    "entities (the graph's thin spots)."
)
def analyze_gaps(entity: str = "") -> str:
    from agents.memory_store import get_memory_store
    store = get_memory_store()
    entity = (entity or "").strip()

    if entity:
        g = store.graph_entity(entity)
        if g is None:
            return f"Nothing in the graph about '{entity}'."
        present = {e["relation"] for e in g["edges"]}
        expected = _EXPECTED.get(g["type"], [])
        missing = [r for r in expected if r not in present]
        lines = [f"{g['name']} ({g['type']}): {len(g['edges'])} relationship(s)."]
        if missing:
            lines.append("Missing expected relationship(s): " + ", ".join(missing))
        else:
            lines.append("No obvious gaps for its type.")
        return "\n".join(lines)

    sparse = store.sparse_entities(max_edges=1)
    if not sparse:
        return "The knowledge graph is empty (no entities yet)."
    lines = ["Sparse / weakly-connected entities:"]
    lines += [f"  {s['name']} ({s['type']}) — {s['edge_count']} edge(s)" for s in sparse]
    return "\n".join(lines)
