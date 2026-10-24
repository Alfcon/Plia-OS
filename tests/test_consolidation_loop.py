def test_should_fire_true_when_enabled_time_matches_not_run_today():
    from core.consolidation_loop import _should_fire
    assert _should_fire(True, "03:00", "03:00", None, "2026-07-04") is True
    assert _should_fire(True, "03:00", "03:00", "2026-07-03", "2026-07-04") is True


def test_should_not_fire_when_disabled():
    from core.consolidation_loop import _should_fire
    assert _should_fire(False, "03:00", "03:00", None, "2026-07-04") is False


def test_should_not_fire_wrong_minute():
    from core.consolidation_loop import _should_fire
    assert _should_fire(True, "03:00", "03:01", None, "2026-07-04") is False


def test_should_not_fire_already_ran_today():
    from core.consolidation_loop import _should_fire
    assert _should_fire(True, "03:00", "03:00", "2026-07-04", "2026-07-04") is False


def test_config_has_consolidation_fields():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.consolidation_enabled is False
    assert cfg.consolidation_time == "03:00"
