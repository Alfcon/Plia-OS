import pytest
from core.token_usage import record, get_stats, reset


@pytest.fixture(autouse=True)
def clear_usage():
    reset()
    yield
    reset()


def test_record_accumulates():
    record(100, 50, "llama3")
    record(200, 80, "llama3")
    stats = get_stats()
    assert stats["calls"] == 2
    assert stats["prompt_tokens"] == 300
    assert stats["completion_tokens"] == 130
    assert stats["total_tokens"] == 430


def test_reset_clears():
    record(100, 50, "llama3")
    reset()
    stats = get_stats()
    assert stats["calls"] == 0
    assert stats["total_tokens"] == 0


def test_recent_capped_at_10():
    for i in range(15):
        record(10, 5, "m")
    stats = get_stats()
    assert len(stats["recent"]) == 10


def test_recent_contains_model():
    record(42, 7, "qwen2.5")
    stats = get_stats()
    assert stats["recent"][-1]["model"] == "qwen2.5"
    assert stats["recent"][-1]["prompt"] == 42
    assert stats["recent"][-1]["completion"] == 7
