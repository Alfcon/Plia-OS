import pytest
from unittest.mock import AsyncMock, patch

import modules.ocr_tools as oc


@pytest.mark.asyncio
async def test_ocr_auto_tesseract_hit():
    with patch.object(oc, "_tesseract_available", return_value=True), \
         patch.object(oc, "_run_tesseract", return_value="hello"), \
         patch.object(oc, "describe_image_bytes", new=AsyncMock()) as vis:
        text, used = await oc._ocr(b"png", "auto")
    assert (text, used) == ("hello", "tesseract")
    vis.assert_not_called()


@pytest.mark.asyncio
async def test_ocr_auto_empty_falls_back_to_vision():
    with patch.object(oc, "_tesseract_available", return_value=True), \
         patch.object(oc, "_run_tesseract", return_value=""), \
         patch.object(oc, "describe_image_bytes", new=AsyncMock(return_value="visiontext")):
        text, used = await oc._ocr(b"png", "auto")
    assert (text, used) == ("visiontext", "vision")


@pytest.mark.asyncio
async def test_ocr_auto_tesseract_unavailable_uses_vision():
    with patch.object(oc, "_tesseract_available", return_value=False), \
         patch.object(oc, "describe_image_bytes", new=AsyncMock(return_value="vt")):
        text, used = await oc._ocr(b"png", "auto")
    assert used == "vision"


@pytest.mark.asyncio
async def test_ocr_vision_engine_skips_tesseract():
    with patch.object(oc, "_run_tesseract") as tess, \
         patch.object(oc, "describe_image_bytes", new=AsyncMock(return_value="vt")):
        text, used = await oc._ocr(b"png", "vision")
    assert used == "vision"
    tess.assert_not_called()


@pytest.mark.asyncio
async def test_ocr_tesseract_engine_unavailable():
    with patch.object(oc, "_tesseract_available", return_value=False), \
         patch.object(oc, "describe_image_bytes", new=AsyncMock()) as vis:
        text, used = await oc._ocr(b"png", "tesseract")
    assert (text, used) == ("", "no_tesseract")
    vis.assert_not_called()


@pytest.mark.asyncio
async def test_ocr_tesseract_raises_auto_falls_back():
    with patch.object(oc, "_tesseract_available", return_value=True), \
         patch.object(oc, "_run_tesseract", side_effect=RuntimeError("boom")), \
         patch.object(oc, "describe_image_bytes", new=AsyncMock(return_value="vt")):
        text, used = await oc._ocr(b"png", "auto")
    assert used == "vision"


@pytest.mark.asyncio
async def test_extract_image_missing():
    with patch("os.path.isfile", return_value=False):
        out = await oc.extract_text_from_image("/no/file.png")
    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_extract_image_renders(tmp_path):
    p = tmp_path / "a.png"; p.write_bytes(b"png")
    with patch.object(oc, "_ocr", new=AsyncMock(return_value=("hello", "tesseract"))):
        out = await oc.extract_text_from_image(str(p))
    assert "[tesseract]" in out and "hello" in out


@pytest.mark.asyncio
async def test_extract_image_no_tesseract_message(tmp_path):
    p = tmp_path / "a.png"; p.write_bytes(b"png")
    with patch.object(oc, "_ocr", new=AsyncMock(return_value=("", "no_tesseract"))):
        out = await oc.extract_text_from_image(str(p), "tesseract")
    assert "tesseract" in out.lower() and "install" in out.lower()


@pytest.mark.asyncio
async def test_extract_image_none(tmp_path):
    p = tmp_path / "a.png"; p.write_bytes(b"png")
    with patch.object(oc, "_ocr", new=AsyncMock(return_value=("", "none"))):
        out = await oc.extract_text_from_image(str(p))
    assert "no text" in out.lower()


@pytest.mark.asyncio
async def test_extract_screen_no_capture():
    with patch.object(oc, "_screen_png", return_value=None):
        out = await oc.extract_text_from_screen()
    assert "could not capture" in out.lower()


@pytest.mark.asyncio
async def test_extract_screen_renders():
    with patch.object(oc, "_screen_png", return_value=b"png"), \
         patch.object(oc, "_ocr", new=AsyncMock(return_value=("screen text", "vision"))):
        out = await oc.extract_text_from_screen(0, "vision")
    assert "[vision]" in out and "screen text" in out


def test_ocr_tools_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.ocr_tools" in sys.modules:
        del sys.modules["modules.ocr_tools"]
    set_loading_module("ocr_tools")
    try:
        import modules.ocr_tools  # noqa: F401
    finally:
        set_loading_module("")
    tools = list_tools()
    assert "extract_text_from_image" in tools and "extract_text_from_screen" in tools
