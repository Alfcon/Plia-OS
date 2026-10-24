import pytest
from unittest.mock import patch, MagicMock


def test_create_agent_success():
    mock_save = MagicMock()
    mock_reload = MagicMock()
    with patch("core.agent_store.get_agent", return_value=None), \
         patch("core.agent_store.save_agent", mock_save), \
         patch("core.supervisor._reload_custom_agents", mock_reload):
        from modules.agent_tools import create_agent
        result = create_agent(
            name="mhd-research",
            system_prompt="You search for MHD papers.",
            display_name="MHD Research Agent",
            description="Searches for MHD papers",
            tool_names="research_search,list_research_sites",
            keywords="mhd,saltwater generator",
        )
    assert mock_save.called
    saved = mock_save.call_args[0][0]
    assert saved.name == "mhd-research"
    assert saved.display_name == "MHD Research Agent"
    assert saved.tool_names == ["research_search", "list_research_sites"]
    assert saved.keywords == ["mhd", "saltwater generator"]
    assert mock_reload.called
    assert "created" in result.lower()


def test_create_agent_invalid_slug():
    with patch("core.agent_store.get_agent", return_value=None):
        from modules.agent_tools import create_agent
        result = create_agent(
            name="Bad Name!",
            system_prompt="prompt",
        )
    assert "lowercase" in result.lower() or "invalid" in result.lower()


def test_create_agent_already_exists():
    mock_existing = MagicMock()
    with patch("core.agent_store.get_agent", return_value=mock_existing):
        from modules.agent_tools import create_agent
        result = create_agent(name="my-agent", system_prompt="prompt")
    assert "already exists" in result.lower()
    assert "edit_agent" in result


def test_create_agent_empty_tool_names_stores_empty_list():
    mock_save = MagicMock()
    with patch("core.agent_store.get_agent", return_value=None), \
         patch("core.agent_store.save_agent", mock_save), \
         patch("core.supervisor._reload_custom_agents"):
        from modules.agent_tools import create_agent
        create_agent(name="bare-agent", system_prompt="prompt", tool_names="")
    saved = mock_save.call_args[0][0]
    assert saved.tool_names == []


def test_edit_agent_updates_fields():
    mock_defn = MagicMock()
    mock_defn.display_name = "Old Name"
    mock_defn.llm_description = "old desc"
    mock_defn.system_prompt = "old prompt"
    mock_defn.tool_names = []
    mock_defn.keywords = []
    mock_save = MagicMock()
    mock_reload = MagicMock()
    with patch("core.agent_store.get_agent", return_value=mock_defn), \
         patch("core.agent_store.save_agent", mock_save), \
         patch("core.supervisor._reload_custom_agents", mock_reload):
        from modules.agent_tools import edit_agent
        result = edit_agent(
            name="my-agent",
            display_name="New Name",
            description="new desc",
            tool_names="research_search",
        )
    assert mock_defn.display_name == "New Name"
    assert mock_defn.llm_description == "new desc"
    assert mock_defn.tool_names == ["research_search"]
    assert mock_reload.called
    assert "updated" in result.lower()


def test_edit_agent_not_found():
    with patch("core.agent_store.get_agent", return_value=None):
        from modules.agent_tools import edit_agent
        result = edit_agent(name="no-such-agent", display_name="X")
    assert "no agent" in result.lower() or "not found" in result.lower()


def test_edit_agent_skips_empty_strings():
    mock_defn = MagicMock()
    mock_defn.display_name = "Keep This"
    mock_defn.system_prompt = "Keep This Too"
    mock_defn.tool_names = ["existing-tool"]
    mock_defn.keywords = []
    mock_defn.llm_description = "keep"
    with patch("core.agent_store.get_agent", return_value=mock_defn), \
         patch("core.agent_store.save_agent"), \
         patch("core.supervisor._reload_custom_agents"):
        from modules.agent_tools import edit_agent
        edit_agent(name="my-agent", display_name="", system_prompt="", tool_names="")
    assert mock_defn.display_name == "Keep This"
    assert mock_defn.system_prompt == "Keep This Too"
    assert mock_defn.tool_names == ["existing-tool"]


def test_delete_agent_success():
    mock_reload = MagicMock()
    with patch("core.agent_store.delete_agent", return_value=True) as mock_del, \
         patch("core.supervisor._reload_custom_agents", mock_reload):
        from modules.agent_tools import delete_agent
        result = delete_agent("my-agent")
    mock_del.assert_called_once_with("my-agent")
    assert mock_reload.called
    assert "deleted" in result.lower()


def test_delete_agent_not_found():
    with patch("core.agent_store.delete_agent", return_value=False), \
         patch("core.supervisor._reload_custom_agents"):
        from modules.agent_tools import delete_agent
        result = delete_agent("ghost-agent")
    assert "no agent" in result.lower() or "not found" in result.lower()
