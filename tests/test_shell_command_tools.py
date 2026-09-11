import pytest
from unittest.mock import MagicMock, patch


def test_propose_command_stashes_and_shows():
    import modules.shell_command_tools as sct
    sct._LAST_PROPOSAL = None
    out = sct.propose_command("du -sh ~", "shows home size, read-only")
    assert "du -sh ~" in out
    assert "read-only" in out
    assert sct._LAST_PROPOSAL is not None
    assert sct._LAST_PROPOSAL["command"] == "du -sh ~"


def test_propose_command_blocks_destructive():
    import modules.shell_command_tools as sct
    sct._LAST_PROPOSAL = None
    out = sct.propose_command("rm -rf /", "wipe everything")
    assert "blocked" in out.lower()
    assert sct._LAST_PROPOSAL is None


@pytest.mark.asyncio
async def test_run_proposed_command_no_stash():
    import modules.shell_command_tools as sct
    sct._LAST_PROPOSAL = None
    out = await sct.run_proposed_command("echo hi")
    assert "no command proposed" in out.lower()


@pytest.mark.asyncio
async def test_run_proposed_command_executes_and_clears():
    import modules.shell_command_tools as sct
    sct._LAST_PROPOSAL = {"command": "echo hi", "explanation": "e", "risk": ""}
    with patch("agents.shell_exec.exec_real", return_value="hi") as m:
        out = await sct.run_proposed_command("echo hi")
    assert out == "hi"
    m.assert_called_once_with("echo hi")
    assert sct._LAST_PROPOSAL is None


@pytest.mark.asyncio
async def test_run_proposed_command_blocks_destructive_stash():
    import modules.shell_command_tools as sct
    sct._LAST_PROPOSAL = {"command": "rm -rf /", "explanation": "e", "risk": ""}
    out = await sct.run_proposed_command("rm -rf /")
    assert "blocked" in out.lower()
    assert sct._LAST_PROPOSAL is None


@pytest.mark.asyncio
async def test_run_proposed_command_mismatch_refused():
    import modules.shell_command_tools as sct
    sct._LAST_PROPOSAL = {"command": "echo hi", "explanation": "e", "risk": ""}
    out = await sct.run_proposed_command("rm -rf /tmp/x")
    assert "does not match" in out.lower()
    assert sct._LAST_PROPOSAL is not None  # stash retained on mismatch


def test_run_proposed_command_always_guarded():
    from core.tool_guard import _is_guarded
    cfg = MagicMock()
    cfg.tool_guard_list = []
    with patch("core.config.get_config", return_value=cfg):
        assert _is_guarded("run_proposed_command") is True
        assert _is_guarded("some_other_tool") is False
