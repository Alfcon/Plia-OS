from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import httpx

from core.config import get_config
from voice.stt import get_stt_service

logger = logging.getLogger(__name__)

_YTDLP = "yt-dlp"
_CHUNK = 6000
_SUMMARIZE_TIMEOUT = 90
_CAPTION_TIMEOUT = 60
_AUDIO_TIMEOUT = 600

_TAG_RE = re.compile(r"<[^>]+>")


def _have_ytdlp() -> bool:
    return shutil.which(_YTDLP) is not None


def _output_dir() -> Path:
    d = Path(get_config().memory_dir) / "generated"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (s or "video")[:40]


def _parse_vtt(vtt_text: str) -> str:
    out: list[str] = []
    prev: str | None = None
    for raw in vtt_text.splitlines():
        line = raw.strip()
        if (not line or line == "WEBVTT" or "-->" in line
                or line.startswith(("NOTE", "Kind:", "Language:"))
                or line.isdigit()):
            continue
        line = re.sub(r"\s+", " ", _TAG_RE.sub("", line)).strip()
        if not line or line == prev:
            continue
        out.append(line)
        prev = line
    return " ".join(out).strip()


async def _run_ytdlp(*args: str, timeout: int) -> bool:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            _YTDLP, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.debug("yt-dlp timed out: %s", args)
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        return False
    except Exception:
        logger.debug("yt-dlp run failed: %s", args, exc_info=True)
        return False


async def _fetch_captions(url: str, tmpdir: str) -> str | None:
    ok = await _run_ytdlp(
        "--skip-download", "--write-auto-subs", "--write-subs",
        "--sub-langs", "en.*", "--sub-format", "vtt",
        "-o", os.path.join(tmpdir, "cap.%(ext)s"), "--", url,
        timeout=_CAPTION_TIMEOUT,
    )
    if not ok:
        return None
    vtts = glob.glob(os.path.join(tmpdir, "*.vtt"))
    if not vtts:
        return None
    try:
        text = _parse_vtt(Path(vtts[0]).read_text(errors="replace"))
    except Exception:
        logger.debug("vtt parse failed", exc_info=True)
        return None
    return text or None


async def _fetch_audio_transcript(url: str, tmpdir: str) -> str | None:
    ok = await _run_ytdlp(
        "-f", "bestaudio", "-o", os.path.join(tmpdir, "audio.%(ext)s"), "--", url,
        timeout=_AUDIO_TIMEOUT,
    )
    if not ok:
        return None
    files = glob.glob(os.path.join(tmpdir, "audio.*"))
    if not files:
        return None
    try:
        text = await asyncio.to_thread(get_stt_service().transcribe_file, files[0])
    except Exception:
        logger.debug("whisper transcribe failed", exc_info=True)
        return None
    return text or None


async def get_transcript(source: str) -> tuple[str, str]:
    """Return (transcript_text, method). Never raises."""
    try:
        if os.path.isfile(source):
            text = await asyncio.to_thread(get_stt_service().transcribe_file, source)
            return (text or "", "file")
        if not str(source).lower().startswith(("http://", "https://")):
            return ("", "bad_source")
        if not _have_ytdlp():
            return ("", "no_ytdlp")
        with tempfile.TemporaryDirectory() as tmp:
            caps = await _fetch_captions(source, tmp)
            if caps:
                return (caps, "captions")
            audio = await _fetch_audio_transcript(source, tmp)
            if audio:
                return (audio, "whisper")
        return ("", "none")
    except Exception as exc:
        logger.exception("get_transcript failed")
        return ("", f"error:{exc}")


def _save_transcript(source: str, text: str) -> Path | None:
    try:
        base = os.path.basename(source) if os.path.isfile(source) else source
        path = _output_dir() / f"transcript_{_slug(base)}_{int(time.time())}.txt"
        path.write_text(text)
        return path
    except Exception:
        logger.exception("saving transcript failed")
        return None


def _summarize_transcript(text: str) -> str:
    """Summarize a transcript via Ollama (chunked if long). Never raises."""
    cfg = get_config()

    def _one(prompt: str) -> str:
        r = httpx.post(
            f"{cfg.ollama_url}/api/chat",
            json={"model": cfg.ollama_model,
                  "messages": [{"role": "user", "content": prompt}],
                  "stream": False},
            timeout=_SUMMARIZE_TIMEOUT,
        )
        return str(r.json()["message"]["content"]).strip()

    try:
        if len(text) <= _CHUNK:
            return _one("Summarize this transcript in a few concise paragraphs with the key "
                        "points:\n\n" + text)
        chunks = [text[i:i + _CHUNK] for i in range(0, len(text), _CHUNK)]
        partials = [_one(f"Summarize part {i}/{len(chunks)} of a transcript:\n\n{ch}")
                    for i, ch in enumerate(chunks, 1)]
        return _one("Combine these section summaries into one concise overall summary with key "
                    "points:\n\n" + "\n".join(partials))
    except Exception:
        logger.exception("summarize failed")
        return text[:1500].strip() + " …"
