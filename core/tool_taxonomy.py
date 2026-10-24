"""Tool information architecture — the category → subgroup → tools map.

This is the single source of truth for how tools are grouped in the
dashboard (``GET /api/tools/taxonomy``) and in the Tools panel.

Rules encoded here:

* Two levels only — category, then subgroup. No tool needs a third click.
* Grouping is by *function*, not by module filename.
* No catch-all: every registered tool must have exactly one home.
  ``tests/test_tool_taxonomy.py`` fails if a module adds a tool without
  adding it here (or passing ``category=``/``subgroup=`` to ``@tool``).
* Destructive subgroups are listed last and flagged in ``DANGER_SUBGROUPS``
  so the UI can render them as a separate, red block.

Individual tools can override their home with
``@tool("…", category="X", subgroup="Y")``; that override wins.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

CATEGORIES: dict[str, dict[str, tuple[str, ...]]] = {
    'Memory & Agents': {
        'Facts & Recall': (
            'save_memory',
            'get_fact',
            'list_memories',
            'search_memories',
            'forget_memory',
        ),
        'Notes': (
            'add_note',
            'list_notes',
            'delete_note',
            'clear_notes',
        ),
        'Conversation': (
            'clear_conversation',
            'delete_history_permanent',
        ),
        'Memory Graph': (
            'query_graph',
            'analyze_gaps',
            'consolidate_now',
        ),
        'Agents & Flows': (
            'list_custom_agents',
            'create_agent',
            'edit_agent',
            'delete_agent',
            'run_agent',
            'list_workflows',
            'run_workflow',
        ),
    },
    'Files & Code': {
        'Files': (
            'read_file',
            'write_file',
            'append_to_file',
            'delete_file',
            'move_file',
            'copy_file',
            'list_directory',
            'find_files',
            'search_in_file',
            'run_file',
        ),
        'Documents': (
            'read_pdf',
            'read_docx',
            'read_xlsx',
            'read_pptx',
        ),
        'Document Index': (
            'index_documents',
            'query_documents',
            'list_indexed_sources',
            'remove_indexed_source',
        ),
        'Code Execution': (
            'run_python_code',
            'run_shell_command',
        ),
        'Guarded Shell': (
            'propose_command',
            'run_proposed_command',
        ),
        'Desktop Control': (
            'use_computer',
        ),
    },
    'Vision & Media': {
        'Screen & OCR': (
            'take_screenshot',
            'extract_text_from_screen',
            'look_at_screen',
            'describe_image',
            'extract_text_from_image',
        ),
        'Generate': (
            'generate_image',
            'generate_slides',
        ),
        'Video': (
            'transcribe_video',
            'summarize_video',
        ),
        'Playback': (
            'get_now_playing',
            'media_play',
            'media_pause',
            'media_next',
            'media_previous',
            'media_stop',
        ),
        'Volume': (
            'mute_audio',
            'unmute_audio',
            'set_volume',
            'get_volume',
        ),
    },
    'Comms & Schedule': {
        'Email': (
            'list_inbox',
            'search_email',
            'triage_inbox',
            'send_email',
        ),
        'Calendar': (
            'add_calendar_event',
            'list_calendar_events',
            'get_next_event',
            'delete_calendar_event',
        ),
        'Reminders': (
            'set_reminder',
            'list_pending_reminders',
            'delete_reminder',
            'clear_all_reminders',
        ),
        'Timers': (
            'set_timer',
            'list_timers',
            'cancel_timer',
        ),
        'Cron': (
            'add_cron',
            'list_crons',
            'remove_cron',
            'disable_cron',
            'enable_cron',
        ),
        'Briefing': (
            'morning_briefing',
        ),
    },
    'Web & Research': {
        'Web': (
            'search_web',
            'scrape_url',
        ),
        'Feeds': (
            'fetch_news',
            'fetch_rss',
        ),
        'Weather': (
            'get_current_weather',
            'get_forecast',
            'get_uv_index',
        ),
        'Research Sites': (
            'list_research_sites',
            'add_research_site',
            'remove_research_site',
            'research_search',
        ),
        'Site Access': (
            'set_site_credentials',
            'check_site_credentials',
            'remove_site_credentials',
            'login_site',
            'finish_login',
        ),
        'Deep Research': (
            'deep_research',
        ),
    },
    'Home & System': {
        'Smart Home': (
            'toggle_entity',
            'get_entity_state',
            'set_brightness',
            'list_home_entities',
        ),
        'System Info': (
            'get_system_info',
            'get_vram_status',
            'check_system_fit',
        ),
        'Performance': (
            'reduce_memory_usage',
            'reduce_power_consumption',
            'restore_system_performance',
        ),
        'Background Agents': (
            'observer_status',
            'enable_observer',
            'disable_observer',
            'proactive_status',
            'enable_proactive',
            'disable_proactive',
        ),
        'Voice Pipeline': (
            'start_voice_pipeline',
            'stop_voice_pipeline',
            'announce',
        ),
        'Utilities': (
            'get_time',
            'get_current_date',
            'list_tools',
            'recommend_models',
        ),
    },
    'Network': {
        'MAC Address': (
            'list_macs',
            'show_mac',
            'randomize_mac',
            'set_mac',
            'restore_mac',
        ),
        'IP Address': (
            'show_ip',
            'randomize_local_ip',
            'set_local_ip',
            'restore_ip',
        ),
        'Wi-Fi': (
            'list_wifi_interfaces',
            'scan_wifi',
            'wifi_status',
            'connect_wifi',
            'list_saved_wifi',
            'reveal_hidden_ssid',
        ),
        'Adapters': (
            'enable_wifi_dongle',
            'disable_wifi_dongle',
            'internal_wifi_status',
            'disable_internal_wifi',
            'enable_internal_wifi',
            'reactivate_internal_network',
        ),
        'Diagnostics': (
            'public_ip',
            'ping_host',
            'dns_lookup',
            'network_speedtest',
        ),
    },
    'Security & Privacy': {
        'Tor': (
            'enable_tor',
            'disable_tor',
            'tor_status',
        ),
        'Security Audit': (
            'check_password',
            'check_wifi_password',
            'scan_local_network',
            'external_exposure_check',
        ),
        '⚠ Wireless Testing': (
            'install_wireless_tools',
            'start_monitor_mode',
            'stop_monitor_mode',
            'kill_interfering_processes',
            'monitor_scan_networks',
            'capture_handshake',
            'create_wordlist',
            'download_rockyou',
            'scan_wps_networks',
            'attack_wps',
            'crack_handshake_rockyou',
            'crack_handshake_wordlist',
            'crack_handshake_auto',
            'gain_wifi_access',
        ),
    },
}

DANGER_SUBGROUPS: frozenset[str] = frozenset({"⚠ Wireless Testing"})

UNCATEGORISED = "Uncategorised"


def _index() -> dict[str, tuple[str, str]]:
    """name -> (category, subgroup). Built once at import (170 entries)."""
    idx: dict[str, tuple[str, str]] = {}
    for cat, subs in CATEGORIES.items():
        for sub, names in subs.items():
            for name in names:
                idx[name] = (cat, sub)
    return idx


_HOME: dict[str, tuple[str, str]] = _index()


def home_of(tool_name: str) -> tuple[str, str] | None:
    """Return ``(category, subgroup)`` for a tool, or None if unassigned."""
    return _HOME.get(tool_name)


def category_order() -> list[str]:
    return list(CATEGORIES)


def audit(tool_names: Iterable[str]) -> dict[str, list[str]]:
    """Report tools with no home, and homes pointing at missing tools."""
    names = set(tool_names)
    return {
        "missing": sorted(names - set(_HOME)),
        "stale": sorted(set(_HOME) - names),
    }


def _meta_home(name: str, meta: Mapping) -> tuple[str, str]:
    """Resolve one tool's home, preferring the registered override."""
    cat = str(meta.get("category") or "")
    sub = str(meta.get("subgroup") or "")
    if cat and sub:
        return cat, sub
    return home_of(name) or (UNCATEGORISED, "Unassigned")


def build(tools: Mapping[str, dict]) -> list[dict]:
    """Group ``tools`` (name -> meta dict) into the category/subgroup tree.

    Order follows ``CATEGORIES`` for known groups; categories/subgroups that
    only exist as per-tool overrides are appended in first-seen order. Empty
    categories and subgroups are dropped, so a UI never shows a dead heading.

    Tools that resolve to no home land in an explicit ``Uncategorised``
    category. The tests forbid that in a clean checkout; it exists so the
    dashboard stays usable while a brand-new module is being wired up.
    """
    buckets: dict[str, dict[str, list]] = {}
    for name, meta in tools.items():
        cat, sub = _meta_home(name, meta)
        buckets.setdefault(cat, {}).setdefault(sub, []).append(dict(meta))

    order = [c for c in CATEGORIES if c in buckets]
    order += [c for c in buckets if c not in CATEGORIES]

    tree: list[dict] = []
    for cat in order:
        subs = buckets[cat]
        known = list(CATEGORIES.get(cat, {}))
        sub_names = [s for s in known if s in subs]
        sub_names += [s for s in subs if s not in known]
        node: dict = {"name": cat, "count": 0, "subgroups": []}
        for sub in sub_names:
            entries = subs[sub]
            node["subgroups"].append({
                "name": sub,
                "danger": sub in DANGER_SUBGROUPS,
                "count": len(entries),
                "tools": entries,
            })
            node["count"] += len(entries)
        tree.append(node)
    return tree


__all__ = [
    "CATEGORIES", "DANGER_SUBGROUPS", "UNCATEGORISED",
    "home_of", "category_order", "audit", "build",
]
