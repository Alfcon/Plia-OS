import subprocess

from core.registry import tool


def _run_playerctl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["playerctl", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            if "No players found" in result.stderr:
                return "No media player is currently running."
            return f"playerctl error: {result.stderr.strip()}"
        return result.stdout.strip() or "Done."
    except FileNotFoundError:
        return "playerctl not installed. Run: sudo apt install playerctl"
    except subprocess.TimeoutExpired:
        return "Media command timed out."


@tool(description="Get the currently playing track, artist, and player name.")
def get_now_playing() -> str:
    result = _run_playerctl(
        "metadata", "--format", "{{artist}} - {{title}} [{{playerName}}]"
    )
    # "Done." = empty stdout (no stdout from playerctl); " - []" = fields unpopulated
    if result == "Done." or result.strip("- []") == "":
        return "Nothing is playing."
    return result


@tool(description="Resume media playback.")
def media_play() -> str:
    return _run_playerctl("play")


@tool(description="Pause media playback.")
def media_pause() -> str:
    return _run_playerctl("pause")


@tool(description="Skip to the next track.")
def media_next() -> str:
    return _run_playerctl("next")


@tool(description="Go back to the previous track.")
def media_previous() -> str:
    return _run_playerctl("previous")


@tool(description="Stop media playback.")
def media_stop() -> str:
    return _run_playerctl("stop")
