import pytest
from unittest.mock import patch


def test_parse_action_clean_json():
    from agents.computer_use import _parse_action
    assert _parse_action('{"action":"click","x":10,"y":20}') == {"action": "click", "x": 10, "y": 20}


def test_parse_action_json_in_prose():
    from agents.computer_use import _parse_action
    out = _parse_action('Sure, the action is: {"action":"type","text":"hi"} — done.')
    assert out == {"action": "type", "text": "hi"}


def test_parse_action_malformed_returns_none():
    from agents.computer_use import _parse_action
    assert _parse_action("no json here") is None
    assert _parse_action("{not valid}") is None


def test_run_action_click_clamps_and_calls_xdotool():
    from agents.computer_use import _run_action
    with patch("subprocess.run") as m:
        out = _run_action({"action": "click", "x": 5000, "y": -3}, (1920, 1080))
    assert "(1919,0)" in out
    argv = m.call_args.args[0]
    assert argv[:2] == ["xdotool", "mousemove"]
    assert "click" in argv


def test_run_action_type_passes_text_after_dashdash():
    from agents.computer_use import _run_action
    with patch("subprocess.run") as m:
        out = _run_action({"action": "type", "text": "hello"}, (1920, 1080))
    argv = m.call_args.args[0]
    assert argv[-2:] == ["--", "hello"]
    assert "typed" in out


def test_run_action_done_sentinel_no_subprocess():
    from agents.computer_use import _run_action
    with patch("subprocess.run") as m:
        out = _run_action({"action": "done", "summary": "finished"}, (0, 0))
    assert out.startswith("DONE:")
    m.assert_not_called()


def test_run_action_unknown_type():
    from agents.computer_use import _run_action
    out = _run_action({"action": "frobnicate"}, (0, 0))
    assert "unknown action" in out.lower()


def test_run_action_non_dict_returns_message():
    from agents.computer_use import _run_action
    out = _run_action(None, (0, 0))
    assert "invalid action" in out.lower()


def test_parse_action_non_str_returns_none():
    from agents.computer_use import _parse_action
    assert _parse_action(None) is None


@pytest.mark.asyncio
async def test_run_computer_use_loops_until_done():
    from unittest.mock import AsyncMock
    import agents.computer_use as cu
    replies = ['{"action":"click","x":10,"y":10}', '{"action":"done","summary":"ok"}']
    with patch.object(cu, "_xdotool_available", return_value=True), \
         patch.object(cu, "_screen_size", return_value=(1920, 1080)), \
         patch("modules.vision_tools._screen_png", return_value=b"PNG"), \
         patch("agents.vision.describe_image_bytes", new_callable=AsyncMock, side_effect=replies), \
         patch.object(cu, "_run_action", side_effect=["click at (10,10)", "DONE: ok"]), \
         patch("core.events.emit", new_callable=AsyncMock):
        out = await cu.run_computer_use("do it", max_steps=15)
    assert "Steps (2)" in out
    assert "ok" in out.lower()


@pytest.mark.asyncio
async def test_run_computer_use_respects_max_steps():
    from unittest.mock import AsyncMock
    import agents.computer_use as cu
    with patch.object(cu, "_xdotool_available", return_value=True), \
         patch.object(cu, "_screen_size", return_value=(800, 600)), \
         patch("modules.vision_tools._screen_png", return_value=b"PNG"), \
         patch("agents.vision.describe_image_bytes", new_callable=AsyncMock, return_value='{"action":"click","x":1,"y":1}'), \
         patch.object(cu, "_run_action", return_value="click at (1,1)"), \
         patch("core.events.emit", new_callable=AsyncMock) as emit:
        out = await cu.run_computer_use("loop", max_steps=3)
    assert emit.await_count == 3
    assert "Steps (3)" in out


@pytest.mark.asyncio
async def test_run_computer_use_no_xdotool():
    import agents.computer_use as cu
    with patch.object(cu, "_xdotool_available", return_value=False):
        out = await cu.run_computer_use("x")
    assert "xdotool" in out.lower()


@pytest.mark.asyncio
async def test_run_computer_use_unparseable_stops():
    from unittest.mock import AsyncMock
    import agents.computer_use as cu
    with patch.object(cu, "_xdotool_available", return_value=True), \
         patch.object(cu, "_screen_size", return_value=(800, 600)), \
         patch("modules.vision_tools._screen_png", return_value=b"PNG"), \
         patch("agents.vision.describe_image_bytes", new_callable=AsyncMock, return_value="no action"), \
         patch("core.events.emit", new_callable=AsyncMock) as emit:
        out = await cu.run_computer_use("x", max_steps=5)
    assert emit.await_count == 0
    assert "could not parse" in out.lower()
