import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_transcribe_video_saves_and_previews(tmp_path):
    import modules.video_tools as vt
    p = tmp_path / "transcript_x.txt"
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("the full transcript text", "captions"))), \
         patch("agents.video_summarize._save_transcript", return_value=p):
        out = await vt.transcribe_video("https://youtu.be/x")
    assert "captions" in out
    assert str(p) in out
    assert "the full transcript text" in out


@pytest.mark.asyncio
async def test_transcribe_video_no_transcript():
    import modules.video_tools as vt
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("", "no_ytdlp"))):
        out = await vt.transcribe_video("https://youtu.be/x")
    assert "yt-dlp" in out.lower()


@pytest.mark.asyncio
async def test_transcribe_video_error_method():
    import modules.video_tools as vt
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("", "error:boom"))):
        out = await vt.transcribe_video("https://youtu.be/x")
    assert "boom" in out.lower()


@pytest.mark.asyncio
async def test_transcribe_video_bad_source():
    import modules.video_tools as vt
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("", "bad_source"))):
        out = await vt.transcribe_video("not a url")
    assert "unsupported source" in out.lower()


@pytest.mark.asyncio
async def test_transcribe_video_save_failure_still_returns_text():
    import modules.video_tools as vt
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("the transcript", "captions"))), \
         patch("agents.video_summarize._save_transcript", return_value=None):
        out = await vt.transcribe_video("https://youtu.be/x")
    assert "could not save" in out.lower()
    assert "the transcript" in out


@pytest.mark.asyncio
async def test_summarize_video(tmp_path):
    import modules.video_tools as vt
    p = tmp_path / "transcript_y.txt"
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("transcript body", "whisper"))), \
         patch("agents.video_summarize._save_transcript", return_value=p), \
         patch("agents.video_summarize._summarize_transcript", return_value="the summary"):
        out = await vt.summarize_video("https://youtu.be/x")
    assert "the summary" in out
    assert "whisper" in out
    assert str(p) in out


@pytest.mark.asyncio
async def test_summarize_video_no_transcript():
    import modules.video_tools as vt
    with patch("agents.video_summarize.get_transcript",
               new=AsyncMock(return_value=("", "none"))):
        out = await vt.summarize_video("https://youtu.be/x")
    assert "could not fetch" in out.lower()


def test_video_tools_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.video_tools" in sys.modules:
        del sys.modules["modules.video_tools"]
    set_loading_module("video_tools")
    try:
        import modules.video_tools  # noqa: F401
    finally:
        set_loading_module("")
    tools = list_tools()
    assert "transcribe_video" in tools and "summarize_video" in tools
