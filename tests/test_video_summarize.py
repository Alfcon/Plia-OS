import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_transcribe_file_forwards_path():
    from voice.stt import STTService
    svc = STTService()
    seg = MagicMock(); seg.text = " hello world "
    svc._model = MagicMock()
    svc._model.transcribe.return_value = ([seg], None)
    with patch("voice.stt.get_config", return_value=MagicMock(stt_language="auto")):
        out = svc.transcribe_file("/tmp/a.mp3")
    assert out == "hello world"
    assert svc._model.transcribe.call_args.args[0] == "/tmp/a.mp3"


def test_transcribe_file_requires_load():
    from voice.stt import STTService
    svc = STTService()
    with pytest.raises(RuntimeError):
        svc.transcribe_file("/tmp/a.mp3")


def test_parse_vtt_strips_and_dedupes():
    from agents.video_summarize import _parse_vtt
    vtt = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "\n"
        "00:00:01.000 --> 00:00:03.000 align:start position:0%\n"
        "<c>Hello</c> there\n"
        "\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "Hello there\n"          # duplicate rolling caption -> dropped
        "\n"
        "00:00:05.000 --> 00:00:07.000\n"
        "second line\n"
    )
    out = _parse_vtt(vtt)
    assert "-->" not in out and "WEBVTT" not in out and "<c>" not in out
    assert out == "Hello there second line"


@pytest.mark.asyncio
async def test_get_transcript_local_file():
    from agents import video_summarize as vs
    with patch("os.path.isfile", return_value=True), \
         patch("agents.video_summarize.get_stt_service") as gss:
        gss.return_value.transcribe_file.return_value = "local transcript"
        text, method = await vs.get_transcript("/tmp/clip.mp4")
    assert (text, method) == ("local transcript", "file")


@pytest.mark.asyncio
async def test_get_transcript_captions():
    from agents import video_summarize as vs
    with patch("os.path.isfile", return_value=False), \
         patch("agents.video_summarize._have_ytdlp", return_value=True), \
         patch("agents.video_summarize._fetch_captions", new=AsyncMock(return_value="cap text")), \
         patch("agents.video_summarize._fetch_audio_transcript", new=AsyncMock()) as audio:
        text, method = await vs.get_transcript("https://youtu.be/x")
    assert (text, method) == ("cap text", "captions")
    audio.assert_not_called()   # captions short-circuit


@pytest.mark.asyncio
async def test_get_transcript_whisper_fallback():
    from agents import video_summarize as vs
    with patch("os.path.isfile", return_value=False), \
         patch("agents.video_summarize._have_ytdlp", return_value=True), \
         patch("agents.video_summarize._fetch_captions", new=AsyncMock(return_value=None)), \
         patch("agents.video_summarize._fetch_audio_transcript", new=AsyncMock(return_value="whisper text")):
        text, method = await vs.get_transcript("https://youtu.be/x")
    assert (text, method) == ("whisper text", "whisper")


@pytest.mark.asyncio
async def test_get_transcript_no_ytdlp():
    from agents import video_summarize as vs
    with patch("os.path.isfile", return_value=False), \
         patch("agents.video_summarize._have_ytdlp", return_value=False):
        text, method = await vs.get_transcript("https://youtu.be/x")
    assert text == "" and method == "no_ytdlp"


@pytest.mark.asyncio
async def test_get_transcript_none():
    from agents import video_summarize as vs
    with patch("os.path.isfile", return_value=False), \
         patch("agents.video_summarize._have_ytdlp", return_value=True), \
         patch("agents.video_summarize._fetch_captions", new=AsyncMock(return_value=None)), \
         patch("agents.video_summarize._fetch_audio_transcript", new=AsyncMock(return_value=None)):
        text, method = await vs.get_transcript("https://youtu.be/x")
    assert text == "" and method == "none"


def _resp(content):
    r = MagicMock()
    r.json.return_value = {"message": {"content": content}}
    return r


def test_summarize_short_single_call():
    from agents.video_summarize import _summarize_transcript
    with patch("httpx.post", return_value=_resp("short summary")) as m, \
         patch("agents.video_summarize.get_config", return_value=MagicMock(ollama_url="http://x", ollama_model="m")):
        out = _summarize_transcript("a short transcript")
    assert out == "short summary"
    assert m.call_count == 1


def test_summarize_long_chunks_then_combines():
    from agents.video_summarize import _summarize_transcript
    long_text = "x" * 13000   # 3 chunks of 6000 + combine = 4 calls
    with patch("httpx.post", return_value=_resp("partial")) as m, \
         patch("agents.video_summarize.get_config", return_value=MagicMock(ollama_url="http://x", ollama_model="m")):
        out = _summarize_transcript(long_text)
    assert m.call_count > 1
    assert out == "partial"


def test_summarize_failure_falls_back_to_excerpt():
    from agents.video_summarize import _summarize_transcript
    with patch("httpx.post", side_effect=RuntimeError("boom")), \
         patch("agents.video_summarize.get_config", return_value=MagicMock(ollama_url="http://x", ollama_model="m")):
        out = _summarize_transcript("some transcript text")
    assert "some transcript text" in out


def test_save_transcript_writes_file(tmp_path):
    from agents import video_summarize as vs
    with patch("agents.video_summarize._output_dir", return_value=tmp_path):
        path = vs._save_transcript("https://youtu.be/abc", "the transcript")
    assert path.exists()
    assert path.read_text() == "the transcript"
    assert path.suffix == ".txt"


@pytest.mark.asyncio
async def test_get_transcript_rejects_non_http_source():
    from agents import video_summarize as vs
    with patch("os.path.isfile", return_value=False), \
         patch("agents.video_summarize._have_ytdlp", return_value=True) as have, \
         patch("agents.video_summarize._fetch_captions", new=AsyncMock()) as caps:
        text, method = await vs.get_transcript("--exec=touch /tmp/pwned")
    assert text == "" and method == "bad_source"
    caps.assert_not_called()       # never reaches yt-dlp
    have.assert_not_called()


def test_save_transcript_returns_none_on_write_error(tmp_path):
    from agents import video_summarize as vs
    with patch("agents.video_summarize._output_dir", return_value=tmp_path), \
         patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        assert vs._save_transcript("https://youtu.be/x", "text") is None


@pytest.mark.asyncio
async def test_run_ytdlp_kills_on_timeout():
    from agents import video_summarize as vs
    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    proc.kill = MagicMock()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        ok = await vs._run_ytdlp("--version", timeout=1)
    assert ok is False
    proc.kill.assert_called_once()
