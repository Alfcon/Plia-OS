from modules.example_module import get_time, set_reminder


def test_get_time_returns_hhmm():
    result = get_time()
    parts = result.split(":")
    assert len(parts) == 2
    assert parts[0].isdigit() and parts[1].isdigit()


def test_set_reminder_returns_confirmation():
    result = set_reminder(message="take meds", minutes=30)
    assert "take meds" in result
    assert "30" in result
