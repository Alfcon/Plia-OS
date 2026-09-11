"""Unit tests for core/hf_quants.py (HF URL parsing + GGUF quant extraction)."""

from core.hf_quants import extract_quants, parse_hf_repo


def _f(path, size):
    return {"path": path, "size": size}


# ── parse_hf_repo ──────────────────────────────────────────────────────────

def test_parse_full_url_with_query():
    url = ("https://huggingface.co/mradermacher/"
           "Dirty-Muse-Writer-v01-Uncensored-Erotica-NSFW-i1-GGUF"
           "?not-for-all-audiences=true")
    assert parse_hf_repo(url) == (
        "mradermacher/Dirty-Muse-Writer-v01-Uncensored-Erotica-NSFW-i1-GGUF")


def test_parse_url_with_trailing_path():
    assert parse_hf_repo(
        "https://huggingface.co/Qwen/Qwen3-4B/tree/main") == "Qwen/Qwen3-4B"


def test_parse_bare_id_and_hfco():
    assert parse_hf_repo("Qwen/Qwen3-4B") == "Qwen/Qwen3-4B"
    assert parse_hf_repo("hf.co/Qwen/Qwen3-4B") == "Qwen/Qwen3-4B"
    assert parse_hf_repo("  hf.co/Qwen/Qwen3-4B  ") == "Qwen/Qwen3-4B"


def test_parse_rejects_non_repo_inputs():
    assert parse_hf_repo("") is None
    assert parse_hf_repo(None) is None
    assert parse_hf_repo("llama3.2:3b") is None
    assert parse_hf_repo("mistral") is None
    # hf.co with an explicit quant tag is pull-ready, not a listing target
    assert parse_hf_repo("hf.co/Qwen/Qwen3-4B:Q4_K_M") is None
    assert parse_hf_repo("https://example.com/a/b") is None
    # reserved first segments are site sections, not usernames
    assert parse_hf_repo("https://huggingface.co/datasets/foo") is None
    assert parse_hf_repo("https://huggingface.co/spaces/foo") is None


# ── extract_quants ─────────────────────────────────────────────────────────

def test_extract_parses_quant_names_and_sorts_by_bits():
    files = [
        _f("Qwen3-4B.i1-Q4_K_M.gguf", 2_500_000_000),
        _f("Qwen3-4B.i1-IQ3_XS.gguf", 1_800_000_000),
        _f("model.f16.gguf", 8_000_000_000),
        _f("README.md", 1000),
        _f("weird-file.gguf", 500),  # no quant token → skipped
    ]
    rows = extract_quants(files, vram_gb=24.0, ram_gb=64.0)
    assert [r["quant"] for r in rows] == ["IQ3_XS", "Q4_K_M", "f16"]
    assert [r["bits"] for r in rows] == [3, 4, 16]
    assert rows[0]["size_gb"] == 1.8
    assert rows[1]["size_gb"] == 2.5


def test_extract_fit_tiers():
    files = [
        _f("m.Q2_K.gguf", 2_000_000_000),    # 2.0*1.3=2.6 <= 4 → gpu
        _f("m.Q4_K_M.gguf", 5_000_000_000),  # 6.5 > 4; 5.0*1.2=6.0 <= 16 → cpu
        _f("m.Q8_0.gguf", 20_000_000_000),   # 26 > 4; 24 > 16 → none
    ]
    rows = extract_quants(files, vram_gb=4.0, ram_gb=16.0)
    fits = {r["quant"]: r["fit"] for r in rows}
    assert fits == {"Q2_K": "gpu", "Q4_K_M": "cpu", "Q8_0": "none"}


def test_extract_collapses_shards_and_marks_unsupported():
    files = [
        _f("qwen-72b-q4_k_m-00001-of-00002.gguf", 20_000_000_000),
        _f("qwen-72b-q4_k_m-00002-of-00002.gguf", 19_000_000_000),
    ]
    rows = extract_quants(files, vram_gb=8.0, ram_gb=32.0)
    assert len(rows) == 1
    assert rows[0]["quant"] == "q4_k_m"
    assert rows[0]["unsupported"] is True
    assert rows[0]["size_gb"] == 39.0


def test_extract_skips_malformed_entries():
    files = [
        "not-a-dict",
        {"path": 42, "size": 1},
        {"path": "m.Q4_0.gguf"},                 # no size
        {"path": "m.Q5_K_M.gguf", "size": -5},   # nonsense size
        {"path": "m.Q4_K_S.gguf", "size": 2_000_000_000},
    ]
    rows = extract_quants(files, vram_gb=8.0, ram_gb=32.0)
    assert [r["quant"] for r in rows] == ["Q4_K_S"]


def test_extract_bits_mapping():
    files = [
        _f("m.IQ4_NL.gguf", 1_000_000_000),
        _f("m.bf16.gguf", 1_000_000_000),
        _f("m.f32.gguf", 1_000_000_000),
    ]
    rows = extract_quants(files, vram_gb=99.0, ram_gb=99.0)
    bits = {r["quant"]: r["bits"] for r in rows}
    assert bits == {"IQ4_NL": 4, "bf16": 16, "f32": 32}


def test_extract_empty_input():
    assert extract_quants([], vram_gb=8.0, ram_gb=32.0) == []


def test_extract_skips_mmproj_sidecars():
    files = [
        _f("mmproj-F16.gguf", 600_000_000),
        _f("model.Q4_K_M.gguf", 2_500_000_000),
    ]
    rows = extract_quants(files, vram_gb=24.0, ram_gb=64.0)
    assert [r["quant"] for r in rows] == ["Q4_K_M"]


def test_extract_mm_proj_hyphenated_variant_also_skipped():
    files = [
        _f("mm-proj-f16.gguf", 600_000_000),
        _f("model.Q4_K_M.gguf", 2_500_000_000),
    ]
    rows = extract_quants(files, vram_gb=24.0, ram_gb=64.0)
    assert [r["quant"] for r in rows] == ["Q4_K_M"]


def test_extract_shards_then_single_file_prefers_single_file():
    files = [
        _f("m-q4_k_m-00001-of-00002.gguf", 5_000_000_000),
        _f("m-q4_k_m-00002-of-00002.gguf", 4_000_000_000),
        _f("m.q4_k_m.gguf", 9_000_000_000),
    ]
    rows = extract_quants(files, vram_gb=8.0, ram_gb=32.0)
    assert len(rows) == 1
    assert rows[0]["unsupported"] is False
    assert rows[0]["size_gb"] == 9.0


def test_extract_single_file_then_shards_prefers_single_file():
    files = [
        _f("m.q4_k_m.gguf", 9_000_000_000),
        _f("m-q4_k_m-00001-of-00002.gguf", 5_000_000_000),
        _f("m-q4_k_m-00002-of-00002.gguf", 4_000_000_000),
    ]
    rows = extract_quants(files, vram_gb=8.0, ram_gb=32.0)
    assert len(rows) == 1
    assert rows[0]["unsupported"] is False
    assert rows[0]["size_gb"] == 9.0
