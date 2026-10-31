from datetime import UTC, date, datetime, timedelta

import pytest
from helpers import make_config

from wgra.config import Horizon
from wgra.detect.short_term import GROUP, SUBREDDIT, Detector, Scope, Window, next_hour, prior_days


def test_live_runs_include_the_current_hour():
    assert next_hour(datetime(2026, 10, 10, 14, 37, 12, tzinfo=UTC)) == datetime(
        2026, 10, 10, 15, tzinfo=UTC
    )


def test_window_bounds():
    end = datetime(2026, 10, 10, 15, tzinfo=UTC)
    window = Window(Horizon("24h", 24, reference_days=28), end)
    assert window.start == end - timedelta(hours=24)
    assert window.reference_start == end - timedelta(hours=24, days=28)
    assert window.parameters()["end"] == int(end.timestamp())
    with pytest.raises(ValueError, match="full hour"):
        Window(Horizon("24h", 24), end + timedelta(minutes=15))


def test_prior_days_end_with_the_windows_last_day():
    assert prior_days(datetime(2026, 10, 10, 15, tzinfo=UTC), 90) == (
        date(2026, 7, 13),
        date(2026, 10, 10),
    )
    # a window ending at midnight ends on the day before
    assert prior_days(datetime(2026, 10, 10, tzinfo=UTC), 1) == (
        date(2026, 10, 9),
        date(2026, 10, 9),
    )


def test_stopwords_are_never_trends_in_any_language_of_the_scope():
    detector = Detector(None, make_config())  # type: ignore[arg-type]
    german = detector.stopwords(Scope("r/de", SUBREDDIT, ("de",)))
    english = detector.stopwords(Scope("r/technology", SUBREDDIT, ("technology",)))
    mixed = detector.stopwords(Scope("tracked", GROUP, ("de", "technology")))
    assert {"the", "und", "war"} <= german
    assert "the" in english
    assert "war" not in english
    # "war" is "was" in german, but a word worth watching in english subreddits
    assert "the" in mixed
    assert "war" not in mixed
