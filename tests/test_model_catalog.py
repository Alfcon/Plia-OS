from unittest.mock import patch


def test_catalog_integrity():
    from core.model_catalog import CATALOG
    assert len(CATALOG) >= 12
    for m in CATALOG:
        assert ":" in m.name                 # looks like "name:tag"
        assert m.params_b > 0
        assert m.size_gb > 0
        assert m.vram_gb > 0
        assert m.tags                         # non-empty
        assert m.label


def test_rank_tiers_big_gpu():
    from core.model_catalog import rank_catalog, CATALOG
    ranked = rank_catalog(24.0, 64.0, CATALOG)
    assert len(ranked) == len(CATALOG)
    # with 24 GB VRAM at least one large model is gpu-fast
    assert any(r["tier"] == "gpu" and r["params_b"] >= 30 for r in ranked)


def test_rank_tiers_no_gpu_some_ram():
    from core.model_catalog import rank_catalog, CatalogModel
    cat = (
        CatalogModel("a:8b", "A 8B", 8, 5.0, 6.0, ("general",)),
        CatalogModel("b:70b", "B 70B", 70, 40.0, 45.0, ("general",)),
    )
    ranked = rank_catalog(0.0, 16.0, cat)
    by_name = {r["name"]: r for r in ranked}
    assert by_name["a:8b"]["tier"] == "cpu"    # 16 GB RAM >= 5.0*1.2
    assert by_name["b:70b"]["tier"] == "none"  # 16 GB RAM < 40*1.2


def test_rank_all_none_on_empty_hardware():
    from core.model_catalog import rank_catalog, CATALOG
    ranked = rank_catalog(0.0, 0.0, CATALOG)
    assert all(r["tier"] == "none" for r in ranked)


def test_rank_sort_order():
    from core.model_catalog import rank_catalog, CatalogModel
    cat = (
        CatalogModel("small:1b", "S", 1, 1.0, 1.5, ("tiny",)),
        CatalogModel("big:13b", "B", 13, 8.0, 10.0, ("general",)),
        CatalogModel("huge:70b", "H", 70, 40.0, 45.0, ("general",)),
    )
    ranked = rank_catalog(12.0, 64.0, cat)
    # big & small fit gpu (12 GB), huge is cpu (64 GB RAM >= 40*1.2). gpu first, largest first.
    assert ranked[0]["name"] == "big:13b"
    assert ranked[1]["name"] == "small:1b"
    assert ranked[2]["name"] == "huge:70b"
    assert [r["tier"] for r in ranked] == ["gpu", "gpu", "cpu"]


def test_current_hardware_reads_both():
    from core import model_catalog
    mem = type("M", (), {"total": 32 * 1024 ** 3})()
    with patch.object(model_catalog, "get_gpu_vram_gb", return_value=8.0), \
         patch("psutil.virtual_memory", return_value=mem):
        vram, ram = model_catalog.current_hardware()
    assert vram == 8.0
    assert round(ram) == 32


def test_current_hardware_survives_psutil_error():
    from core import model_catalog
    with patch.object(model_catalog, "get_gpu_vram_gb", return_value=0.0), \
         patch("psutil.virtual_memory", side_effect=RuntimeError("boom")):
        vram, ram = model_catalog.current_hardware()
    assert vram == 0.0
    assert ram == 0.0


def test_merge_installed_dedupes_exact_name():
    from core.model_catalog import rank_catalog, merge_installed, CatalogModel
    cat = (CatalogModel("a:7b", "A 7B", 7, 4.7, 6.0, ("general",)),)
    rows = rank_catalog(24.0, 64.0, cat)
    merged = merge_installed(rows, [{"name": "a:7b", "size": 4_700_000_000}], 24.0, 64.0)
    assert len(merged) == 1                      # no duplicate row
    assert merged[0]["installed"] is True
    assert "installed" in merged[0]["tags"]
    assert merged[0]["vram_gb"] == 6.0           # curated figures win


def test_merge_installed_appends_unknown_with_estimate():
    from core.model_catalog import rank_catalog, merge_installed, CatalogModel
    cat = (CatalogModel("a:7b", "A 7B", 7, 4.7, 6.0, ("general",)),)
    rows = rank_catalog(24.0, 64.0, cat)
    merged = merge_installed(rows, [{"name": "mystery:latest", "size": 5_000_000_000}], 24.0, 64.0)
    assert len(merged) == 2
    row = next(r for r in merged if r["name"] == "mystery:latest")
    assert row["label"] == "mystery:latest"
    assert row["size_gb"] == 5.0
    assert row["vram_gb"] == 6.5                 # 5.0 * 1.3
    assert row["params_b"] == 0
    assert row["tags"] == ["installed"]
    assert row["tier"] == "gpu"                  # 6.5 <= 24.0
    assert row["installed"] is True


def test_merge_installed_tiers_unknown_against_hardware():
    from core.model_catalog import merge_installed
    merged = merge_installed([], [{"name": "big:70b", "size": 40_000_000_000}], 8.0, 16.0)
    assert merged[0]["tier"] == "none"           # 52 GB VRAM est, 48 GB RAM needed
    merged = merge_installed([], [{"name": "big:70b", "size": 40_000_000_000}], 8.0, 64.0)
    assert merged[0]["tier"] == "cpu"


def test_merge_installed_skips_malformed_entries():
    from core.model_catalog import merge_installed
    bad = [{"size": 123}, {"name": ""}, {"name": "x:1b"}, {"name": "y:1b", "size": "big"}]
    assert merge_installed([], bad, 24.0, 64.0) == []


def test_merge_installed_marks_uninstalled_and_sorts():
    from core.model_catalog import rank_catalog, merge_installed, CatalogModel
    cat = (
        CatalogModel("a:7b", "A 7B", 7, 4.7, 6.0, ("general",)),
        CatalogModel("b:1b", "B 1B", 1, 1.0, 1.5, ("tiny",)),
    )
    rows = rank_catalog(24.0, 64.0, cat)
    merged = merge_installed(rows, [{"name": "new:3b", "size": 2_000_000_000}], 24.0, 64.0)
    assert [r["installed"] for r in merged if r["name"] == "a:7b"] == [False]
    # all gpu tier: curated sorted by params desc, params_b=0 unknown last
    assert [r["name"] for r in merged] == ["a:7b", "b:1b", "new:3b"]


def test_merge_installed_dedupes_duplicate_unknown_names():
    from core.model_catalog import merge_installed
    dup = [{"name": "dup:1b", "size": 1_000_000_000}, {"name": "dup:1b", "size": 1_000_000_000}]
    merged = merge_installed([], dup, 24.0, 64.0)
    assert len(merged) == 1
