from unittest.mock import MagicMock, patch


def test_recommend_models_summary():
    import modules.model_catalog_tools as mct
    cfg = MagicMock()
    cfg.ollama_model = "llama3.1:8b"
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)), \
         patch("core.config.get_config", return_value=cfg):
        out = mct.recommend_models()
    assert "VRAM" in out
    assert "RAM" in out
    # a large model should be recommended as GPU-fast on 24 GB
    assert "70B" in out or "72B" in out


def test_recommend_models_want_filter():
    import modules.model_catalog_tools as mct
    cfg = MagicMock()
    cfg.ollama_model = ""
    with patch("core.model_catalog.current_hardware", return_value=(24.0, 64.0)), \
         patch("core.config.get_config", return_value=cfg):
        out = mct.recommend_models(want="coding")
    assert "Coder" in out
    assert "LLaVA" not in out  # vision model filtered out


def test_recommend_models_defensive():
    import modules.model_catalog_tools as mct
    with patch("core.model_catalog.current_hardware", side_effect=RuntimeError("boom")):
        out = mct.recommend_models()
    assert isinstance(out, str)
    assert "couldn't" in out.lower() or "error" in out.lower()


def test_recommend_models_is_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools

    # Remove module from cache if present, so we can import it fresh
    if "modules.model_catalog_tools" in sys.modules:
        del sys.modules["modules.model_catalog_tools"]

    set_loading_module("model_catalog_tools")
    try:
        import modules.model_catalog_tools  # noqa: F401
    finally:
        set_loading_module("")

    assert "recommend_models" in list_tools()
