from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def call_service(
    base_url: str,
    token: str,
    domain: str,
    service: str,
    entity_id: str | None = None,
    extra: dict | None = None,
) -> str:
    data: dict = {}
    if entity_id and entity_id != "all":
        data["entity_id"] = entity_id
    if extra:
        data.update(extra)
    url = f"{base_url.rstrip('/')}/api/services/{domain}/{service}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=_headers(token), json=data)
    if resp.status_code == 404:
        return f"Entity not found: {entity_id!r}"
    resp.raise_for_status()
    states = resp.json()
    if not states or not isinstance(states, list):
        return f"Called {domain}.{service}" + (f" on {entity_id}" if entity_id else "")
    changed = [s.get("entity_id", "") for s in states if isinstance(s, dict)]
    return f"Called {domain}.{service} — affected: {', '.join(changed)}"


async def get_state(base_url: str, token: str, entity_id: str) -> str:
    url = f"{base_url.rstrip('/')}/api/states/{entity_id}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=_headers(token))
    if resp.status_code == 404:
        return f"Entity not found: {entity_id!r}"
    resp.raise_for_status()
    data = resp.json()
    state = data.get("state", "unknown")
    attrs = data.get("attributes", {})
    friendly = attrs.get("friendly_name", entity_id)
    unit = attrs.get("unit_of_measurement", "")
    return f"{friendly}: {state}{' ' + unit if unit else ''}"


async def list_states(base_url: str, token: str, domain: str | None = None) -> str:
    url = f"{base_url.rstrip('/')}/api/states"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=_headers(token))
    resp.raise_for_status()
    entities = resp.json()
    if domain:
        entities = [e for e in entities if e.get("entity_id", "").startswith(f"{domain}.")]
    if not entities:
        return f"No entities found{' for domain ' + domain if domain else ''}."
    lines = []
    for e in entities[:30]:
        eid = e.get("entity_id", "")
        state = e.get("state", "")
        name = e.get("attributes", {}).get("friendly_name", eid)
        lines.append(f"  {name} ({eid}): {state}")
    suffix = f"\n  ... and {len(entities) - 30} more" if len(entities) > 30 else ""
    return "\n".join(lines) + suffix
