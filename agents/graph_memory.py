from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger(__name__)

_TYPES = {"person", "organization", "place", "project", "thing", "concept"}
_RELATIONS = {
    "works_at", "manages", "knows", "located_in", "part_of", "owns",
    "member_of", "created", "has_attribute", "related_to",
}
_TIMEOUT = 60


def _extract_object(text: str) -> dict:
    """Find the first {...} JSON object and parse it. Raises on failure."""
    start = text.index("{")
    end = text.rindex("}")
    return json.loads(text[start : end + 1])


def extract_graph(text: str) -> dict:
    """One Ollama call extracting entities + typed triples. Never raises."""
    if not text or not text.strip():
        return {"entities": [], "edges": []}
    from core.config import get_config
    cfg = get_config()

    try:
        prompt = (
            "Extract a knowledge graph from the text. Identify entities and relationships.\n"
            "Entity type MUST be one of: person, organization, place, project, thing, concept.\n"
            "Relation MUST be one of: works_at, manages, knows, located_in, part_of, owns, "
            "member_of, created, has_attribute, related_to (use related_to if none fit).\n"
            'Reply with ONLY a JSON object: {"entities":[{"name":...,"type":...}],'
            '"edges":[{"subject":...,"relation":...,"object":...}]}. No prose.\n\n'
            f"Text: {text.strip()}"
        )
        r = httpx.post(
            f"{cfg.ollama_url}/api/chat",
            json={
                "model": cfg.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=_TIMEOUT,
        )
        raw = _extract_object(r.json()["message"]["content"])
    except Exception:
        logger.exception("Graph extraction failed")
        return {"entities": [], "edges": []}

    raw_entities = raw.get("entities") if isinstance(raw, dict) else None
    if not isinstance(raw_entities, list):
        raw_entities = []
    raw_edges = raw.get("edges") if isinstance(raw, dict) else None
    if not isinstance(raw_edges, list):
        raw_edges = []

    entities = []
    for e in raw_entities:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()
        if not name:
            continue
        etype = str(e.get("type") or "").strip().lower()
        if etype not in _TYPES:
            etype = "thing"
        entities.append({"name": name, "type": etype})

    edges = []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        subj = str(e.get("subject") or "").strip()
        obj = str(e.get("object") or "").strip()
        if not subj or not obj:
            continue
        rel = str(e.get("relation") or "").strip().lower()
        if rel not in _RELATIONS:
            rel = "related_to"
        edges.append({"subject": subj, "relation": rel, "object": obj})

    return {"entities": entities, "edges": edges}


def ingest_fact(text: str) -> int:
    """Extract a graph from text and persist it. Returns edges written. Never raises."""
    try:
        graph = extract_graph(text)
        edges = graph.get("edges", [])
        entities = graph.get("entities", [])
        if not edges and not entities:
            return 0
        from agents.memory_store import get_memory_store
        store = get_memory_store()

        type_of = {str(e["name"]).lower(): e["type"] for e in entities}
        written = 0
        for edge in edges:
            subj = str(edge["subject"])
            obj = str(edge["object"])
            sid = store.upsert_entity(subj, type_of.get(subj.lower(), "thing"))
            oid = store.upsert_entity(obj, type_of.get(obj.lower(), "thing"))
            if store.add_edge(sid, edge["relation"], oid, text):
                written += 1
        # upsert standalone entities that never appeared as an edge endpoint
        edge_names = {str(edge["subject"]).lower() for edge in edges} | {str(edge["object"]).lower() for edge in edges}
        for ent in entities:
            if str(ent["name"]).lower() not in edge_names:
                store.upsert_entity(ent["name"], ent["type"])
        return written
    except Exception:
        logger.exception("Graph ingest failed")
        return 0
