"""Live tool output → the dashboard chat (core/tool_output.py)."""
import asyncio
import subprocess
import sys
import threading

from core import tool_output


def test_publish_is_a_no_op_without_a_loop():
    # Worker threads may publish before startup finished; dropping the line must
    # never raise, and must not touch the event bus.
    tool_output._main_loop = None
    original = tool_output.events.emit
    calls = []
    tool_output.events.emit = lambda *a, **k: calls.append(a)
    try:
        assert tool_output.publish("hello", "some_tool") is None
    finally:
        tool_output.events.emit = original
    assert calls == []


def test_publish_reaches_the_event_bus_from_a_worker_thread():
    captured = []
    original = tool_output.events.emit

    async def fake_emit(event_type, data):
        captured.append((event_type, data))

    tool_output.events.emit = fake_emit
    try:
        async def main():
            tool_output.capture_main_loop()
            done = threading.Event()

            def worker():
                tool_output.publish("Trying pin 1234", "attack_wps")
                done.set()

            threading.Thread(target=worker).start()
            for _ in range(100):
                if captured:
                    break
                await asyncio.sleep(0.02)
            done.wait(timeout=2)

        asyncio.run(main())
    finally:
        tool_output.events.emit = original
        tool_output._main_loop = None

    assert captured, "worker-thread publish never reached the event bus"
    event_type, data = captured[0]
    assert event_type == "transcript"
    assert data["role"] == "tool"
    assert data["text"] == "[attack_wps] Trying pin 1234"


def test_stream_captures_output_and_reports_success():
    tool_output._main_loop = None
    lines = []
    original = tool_output.publish
    tool_output.publish = lambda text, tool="": lines.append(text)
    try:
        r = tool_output.stream(
            [sys.executable, "-c", "print('one'); print('two')"], tool="t", timeout=30,
        )
    finally:
        tool_output.publish = original
    assert r.returncode == 0
    assert "one" in r.stdout and "two" in r.stdout
    assert r.stderr == ""
    assert any("one" in l for l in lines) and any("two" in l for l in lines)
    assert any(l.startswith("$ ") for l in lines)      # the command echo
    assert any("finished" in l for l in lines)


def test_stream_keeps_partial_output_on_timeout():
    # The whole point: a killed run still reports what it printed. subprocess.run
    # would raise and drop every line captured before the deadline.
    tool_output._main_loop = None
    original = tool_output.publish
    tool_output.publish = lambda text, tool="": None
    try:
        r = tool_output.stream(
            [sys.executable, "-c",
             "import sys, time; print('first', flush=True); time.sleep(30); print('never')"],
            tool="t", timeout=2,
        )
    finally:
        tool_output.publish = original
    assert r.returncode == -1
    assert "timed out after 2s" in r.stderr
    assert "first" in r.stdout          # partial output preserved
    assert "never" not in r.stdout


def test_stream_reports_a_missing_binary():
    tool_output._main_loop = None
    original = tool_output.publish
    tool_output.publish = lambda text, tool="": None
    try:
        r = tool_output.stream(["/nonexistent/binary", "--x"], tool="t", timeout=5)
    finally:
        tool_output.publish = original
    assert r.returncode == -1
    assert "not found" in r.stderr


def test_tail_returns_the_last_non_empty_lines():
    text = "a\n\nb\nc\nd\n"
    assert tool_output.tail(text, 2) == "c\nd"
    assert tool_output.tail("", 3) == ""
