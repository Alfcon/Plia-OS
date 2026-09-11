import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_describe_image_missing_file(tmp_path):
    from modules.vision_tools import describe_image
    out = await describe_image(str(tmp_path / "nope.png"))
    assert "no file" in out.lower()


@pytest.mark.asyncio
async def test_describe_image_reads_and_delegates(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"PNGDATA")
    with patch("agents.vision.describe_image_bytes", new_callable=AsyncMock, return_value="A cat.") as mock_v:
        from modules.vision_tools import describe_image
        out = await describe_image(str(f), "What animal?")
    assert out == "A cat."
    assert mock_v.await_args.args[0] == b"PNGDATA"
    assert mock_v.await_args.args[1] == "What animal?"


@pytest.mark.asyncio
async def test_look_at_screen_captures_and_delegates():
    with patch("modules.vision_tools._screen_png", return_value=b"SCREENPNG"), \
         patch("agents.vision.describe_image_bytes", new_callable=AsyncMock, return_value="Desktop.") as mock_v:
        from modules.vision_tools import look_at_screen
        out = await look_at_screen("what's here?")
    assert out == "Desktop."
    assert mock_v.await_args.args[0] == b"SCREENPNG"


@pytest.mark.asyncio
async def test_look_at_screen_capture_failure():
    with patch("modules.vision_tools._screen_png", return_value=None):
        from modules.vision_tools import look_at_screen
        out = await look_at_screen()
    assert "could not capture" in out.lower()


@pytest.mark.asyncio
async def test_describe_image_read_error_returns_message(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"x")
    with patch("pathlib.Path.read_bytes", side_effect=PermissionError("denied")):
        from modules.vision_tools import describe_image
        out = await describe_image(str(f))
    assert "could not read" in out.lower()
