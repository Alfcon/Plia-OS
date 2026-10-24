import pytest
from unittest.mock import patch, MagicMock


def _make_store(tmp_path):
    with patch("agents.cron_store.get_config") as mock_cfg:
        mock_cfg.return_value.memory_dir = str(tmp_path)
        from agents.cron_store import _CronStore
        return _CronStore()


@pytest.fixture
def store(tmp_path):
    return _make_store(tmp_path)


def test_add_and_list(store):
    store.add("daily", "0 8 * * *", "Good morning")
    jobs = store.list_all()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "daily"
    assert jobs[0]["expr"] == "0 8 * * *"
    assert jobs[0]["enabled"] == 1


def test_add_replaces_existing(store):
    store.add("daily", "0 8 * * *", "Morning")
    store.add("daily", "0 9 * * *", "Later morning")
    jobs = store.list_all()
    assert len(jobs) == 1
    assert jobs[0]["expr"] == "0 9 * * *"


def test_remove(store):
    store.add("job1", "* * * * *", "tick")
    removed = store.remove("job1")
    assert removed is True
    assert store.list_all() == []


def test_remove_nonexistent(store):
    assert store.remove("ghost") is False


def test_set_enabled(store):
    store.add("job1", "* * * * *", "tick")
    store.set_enabled("job1", False)
    jobs = store.list_all()
    assert jobs[0]["enabled"] == 0
    store.set_enabled("job1", True)
    assert store.list_all()[0]["enabled"] == 1


def test_list_enabled_filters(store):
    store.add("a", "* * * * *", "A")
    store.add("b", "* * * * *", "B")
    store.set_enabled("b", False)
    enabled = store.list_enabled()
    assert len(enabled) == 1
    assert enabled[0]["name"] == "a"


def test_cron_tools_add_invalid_expr(tmp_path):
    with patch("agents.cron_store.get_config") as mock_cfg, \
         patch("agents.cron_store._store", None):
        mock_cfg.return_value.memory_dir = str(tmp_path)
        from modules.cron_tools import add_cron
        result = add_cron("bad", "not-a-cron", "msg")
    assert "invalid" in result.lower()


def test_cron_tools_list_empty(tmp_path):
    with patch("agents.cron_store.get_config") as mock_cfg, \
         patch("agents.cron_store._store", _make_store(tmp_path)):
        mock_cfg.return_value.memory_dir = str(tmp_path)
        from modules.cron_tools import list_crons
        result = list_crons()
    assert "no cron" in result.lower()
