from __future__ import annotations

import asyncio

from core.registry import tool

_MSG = {
    "no_ytdlp": "yt-dlp is not installed; only local files can be transcribed.",
    "none": "Could not fetch a transcript for this source (no captions and audio download failed).",
    "bad_source": "Unsupported source. Provide a http(s):// URL (YouTube etc.) or a local file path.",
}


def _err_message(method: str) -> str:
    if method in _MSG:
        return _MSG[method]
    if method.startswith("error:"):
        return f"Transcription failed: {method[6:]}"
    return "No speech/transcript found for this source."


@tool(
    "Transcribe a video/audio source to text. Accepts a YouTube (or other yt-dlp) URL or a local "
    "file path. Uses existing captions when available (fast); otherwise downloads audio and "
    "transcribes with Whisper (can take minutes for long videos). Saves the full transcript to a file."
)
async def transcribe_video(source: str) -> str:
    from agents.video_summarize import get_transcript, _save_transcript
    text, method = await get_transcript(source)
    if not text:
        return _err_message(method)
    path = _save_transcript(source, text)
    saved = f" saved to `{path}`" if path else " (could not save transcript file)"
    return f"Transcript ({method}, {len(text)} chars){saved}.\n\nPreview:\n{text[:600]}…"


@tool(
    "Summarize a video/audio source. Accepts a YouTube (or other yt-dlp) URL or a local file path; "
    "transcribes it (captions when available, else Whisper) then summarizes. Long videos via "
    "Whisper can take minutes. Saves the full transcript to a file."
)
async def summarize_video(source: str) -> str:
    from agents.video_summarize import get_transcript, _save_transcript, _summarize_transcript
    text, method = await get_transcript(source)
    if not text:
        return _err_message(method)
    path = _save_transcript(source, text)
    summary = await asyncio.to_thread(_summarize_transcript, text)
    saved = f"Full transcript saved to `{path}`." if path else "(Full transcript could not be saved.)"
    return f"Summary ({method}):\n{summary}\n\n{saved}"
