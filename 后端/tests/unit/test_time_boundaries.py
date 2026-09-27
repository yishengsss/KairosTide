from datetime import UTC, datetime, timedelta

from kairos.domain.scheduling import is_active


def test_event_uses_half_open_interval() -> None:
    start = datetime(2026, 9, 25, 6, tzinfo=UTC)
    end = start + timedelta(hours=1)

    assert not is_active(start, end, start - timedelta(microseconds=1))
    assert is_active(start, end, start)
    assert is_active(start, end, end - timedelta(microseconds=1))
    assert not is_active(start, end, end)
