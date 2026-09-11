from unittest.mock import MagicMock, patch


class _FakeImage:
    def __init__(self, sink):
        self._sink = sink
    def save(self, path):
        self._sink["path"] = str(path)
        with open(path, "wb") as f:
            f.write(b"PNG")


def _fake_pipe(sink):
    # callable(prompt, num_inference_steps=...) -> obj with .images[0].save(path)
    def _call(prompt, num_inference_steps=25):
        result = MagicMock()
        result.images = [_FakeImage(sink)]
        return result
    return _call


def test_generate_image_unavailable_returns_message():
    from agents import image_gen
    with patch("agents.image_gen._available", return_value=False), \
         patch("agents.image_gen.get_vram_broker") as broker:
        out = image_gen.generate_image("a red fox")
    assert "not available" in out.lower() or "needs a cuda" in out.lower()
    broker.assert_not_called()          # no broker work when unavailable


def test_generate_image_happy_path(tmp_path):
    from agents import image_gen
    sink = {}
    broker = MagicMock()
    with patch("agents.image_gen._available", return_value=True), \
         patch("agents.image_gen._ensure_registered"), \
         patch("agents.image_gen.get_vram_broker", return_value=broker), \
         patch("agents.image_gen._output_dir", return_value=tmp_path), \
         patch.object(image_gen, "_pipe", _fake_pipe(sink)):
        out = image_gen.generate_image("a red fox")
    assert "saved image to" in out.lower()
    assert sink.get("path", "").endswith(".png")
    broker.request.assert_called_once_with("image_gen")
    broker.release.assert_called_once_with("image_gen")


def test_generate_image_releases_on_error(tmp_path):
    from agents import image_gen
    def _boom(prompt, num_inference_steps=25):
        raise RuntimeError("cuda oom")
    broker = MagicMock()
    with patch("agents.image_gen._available", return_value=True), \
         patch("agents.image_gen._ensure_registered"), \
         patch("agents.image_gen.get_vram_broker", return_value=broker), \
         patch("agents.image_gen._output_dir", return_value=tmp_path), \
         patch.object(image_gen, "_pipe", _boom):
        out = image_gen.generate_image("a red fox")
    assert "failed" in out.lower()
    broker.release.assert_called_once_with("image_gen")   # released even on error


def test_generate_image_load_failure_never_raises():
    from agents import image_gen
    from voice import vram_broker
    # a fresh real broker whose image_gen load_fn raises (simulates CUDA OOM on model load)
    broker = vram_broker.VRAMBroker()
    def _raising_load():
        raise RuntimeError("cuda oom on load")
    def _noop_unload():
        pass
    broker.register(vram_broker.ModelEntry(
        name="image_gen", priority=3, vram_gb=4.0,
        load_fn=_raising_load, unload_fn=_noop_unload,
    ))
    with patch("agents.image_gen._available", return_value=True), \
         patch("agents.image_gen._ensure_registered"), \
         patch("agents.image_gen.get_vram_broker", return_value=broker):
        out = image_gen.generate_image("a red fox")   # must NOT raise
    assert "failed" in out.lower()


def test_image_load_failure_restores_evicted_model():
    # Real broker: a low-priority model is on GPU, image load fails ->
    # the evicted low-priority model must be restored, not orphaned.
    from agents import image_gen
    from voice import vram_broker
    broker = vram_broker.VRAMBroker()
    tts_state = {"loaded": True}
    broker.register(vram_broker.ModelEntry(
        name="kokoro", priority=1, vram_gb=0.4,
        load_fn=lambda: tts_state.__setitem__("loaded", True),
        unload_fn=lambda: tts_state.__setitem__("loaded", False),
    ))
    broker.request("kokoro")   # kokoro now on GPU

    def _failing_load():
        # simulates from_pretrained/.to('cuda') failing, but swallowed like the real _load_pipe
        image_gen._pipe = None
    broker.register(vram_broker.ModelEntry(
        name="image_gen", priority=3, vram_gb=4.0,
        load_fn=_failing_load, unload_fn=lambda: setattr(image_gen, "_pipe", None),
    ))

    with patch("agents.image_gen._available", return_value=True), \
         patch("agents.image_gen._ensure_registered"), \
         patch("agents.image_gen.get_vram_broker", return_value=broker), \
         patch.object(image_gen, "_pipe", None):
        out = image_gen.generate_image("a red fox")   # must not raise

    assert "failed" in out.lower()          # generation reported failure (pipe was None)
    assert tts_state["loaded"] is True      # evicted kokoro was restored
    assert broker._evicted == []            # broker bookkeeping cleared


def test_generate_image_tool_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools
    if "modules.image_tools" in sys.modules:
        del sys.modules["modules.image_tools"]
    set_loading_module("image_tools")
    try:
        import modules.image_tools  # noqa: F401
    finally:
        set_loading_module("")
    assert "generate_image" in list_tools()
