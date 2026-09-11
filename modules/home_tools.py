from core.registry import tool


def _ha_config():
    from core.config import get_config
    cfg = get_config()
    if not cfg.hass_url or not cfg.hass_token:
        return None, None, "Home Assistant not configured. Set hass_url and hass_token in Settings → Home."
    return cfg.hass_url.rstrip("/"), cfg.hass_token, None


@tool(description="Toggle a Home Assistant entity on or off. entity_id example: 'light.living_room'.")
def toggle_entity(entity_id: str) -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(
            f"{url}/api/services/homeassistant/toggle",
            headers=headers,
            json={"entity_id": entity_id},
            timeout=10.0,
        )
        if resp.status_code == 404:
            return f"Entity not found: {entity_id!r}"
        resp.raise_for_status()
        return f"Toggled {entity_id}."
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"


@tool(description="Get the current state of a Home Assistant entity. entity_id example: 'light.living_room'.")
def get_entity_state(entity_id: str) -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.get(f"{url}/api/states/{entity_id}", headers=headers, timeout=10.0)
        if resp.status_code == 404:
            return f"Entity not found: {entity_id!r}"
        resp.raise_for_status()
        data = resp.json()
        return f"{entity_id}: {data.get('state', 'unknown')}"
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"


@tool(description="Set the brightness of a light. brightness_pct must be 0–100. entity_id example: 'light.living_room'.")
def set_brightness(entity_id: str, brightness_pct: int) -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    if not 0 <= brightness_pct <= 100:
        return "brightness_pct must be 0–100."
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    brightness = round(brightness_pct * 255 / 100)
    try:
        resp = httpx.post(
            f"{url}/api/services/light/turn_on",
            headers=headers,
            json={"entity_id": entity_id, "brightness": brightness},
            timeout=10.0,
        )
        if resp.status_code == 404:
            return f"Entity not found: {entity_id!r}"
        resp.raise_for_status()
        return f"Set {entity_id} to {brightness_pct}% brightness."
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"


@tool(description="List Home Assistant entities, optionally filtered by domain (e.g. 'light', 'switch', 'sensor').")
def list_home_entities(domain: str = "") -> str:
    import httpx
    url, token, err = _ha_config()
    if err:
        return err
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.get(f"{url}/api/states", headers=headers, timeout=10.0)
        resp.raise_for_status()
        states = resp.json()
        if domain:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        if not states:
            return f"No entities found{' for domain ' + domain if domain else ''}."
        lines = [f"- {s['entity_id']}: {s.get('state', '?')}" for s in states[:30]]
        suffix = f"\n(showing 30 of {len(resp.json())})" if domain == "" and len(states) > 30 else ""
        return "\n".join(lines) + suffix
    except httpx.HTTPError as exc:
        return f"HA request failed: {exc}"
