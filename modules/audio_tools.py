from core.registry import tool


@tool(description="Mute system audio output.")
def mute_audio() -> str:
    import subprocess
    try:
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
                       check=True, capture_output=True, timeout=5)
        return "Audio muted."
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Unmute system audio output.")
def unmute_audio() -> str:
    import subprocess
    try:
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                       check=True, capture_output=True, timeout=5)
        return "Audio unmuted."
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Set system audio volume. percent must be 0–100.")
def set_volume(percent: int) -> str:
    import subprocess
    if not 0 <= percent <= 100:
        return "Volume must be 0–100."
    level = percent / 100
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"],
            check=True, capture_output=True, timeout=5,
        )
        return f"Volume set to {percent}%."
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"


@tool(description="Get current system audio volume as a percentage.")
def get_volume() -> str:
    import subprocess
    import re
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        match = re.search(r"[\d.]+", result.stdout)
        if not match:
            return "Could not parse volume."
        percent = round(float(match.group()) * 100)
        muted = "[MUTED]" in result.stdout
        return f"Volume: {percent}%{' (muted)' if muted else ''}"
    except FileNotFoundError:
        return "wpctl not found. Install pipewire-tools."
    except subprocess.CalledProcessError as exc:
        return f"wpctl error: {exc.stderr.decode().strip()}"
