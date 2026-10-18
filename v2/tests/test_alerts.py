from datetime import timedelta

from helpers import make_trend

from wgra.config import DetectConfig, NotifyConfig
from wgra.detect.alerts import (
    CAPPED,
    COOLDOWN,
    SKIPPED,
    WARMUP,
    SentAlert,
    alert_worthy,
    decide_alerts,
)

DETECT = DetectConfig(min_reference_days=3)
NOTIFY = NotifyConfig(alert_min_z=10, alert_min_authors=20, alert_min_breadth=3)


def decide(trends, recent=(), notify=NOTIFY, detect=DETECT):
    now = trends[0].detected_at
    return decide_alerts(trends, recent, now, detect, notify)


def test_only_strong_or_broad_trends_alert():
    assert alert_worthy(make_trend(z=12, authors=250), NOTIFY)
    assert not alert_worthy(make_trend(z=8, authors=250), NOTIFY)
    assert not alert_worthy(make_trend(z=12, authors=10), NOTIFY)
    assert not alert_worthy(make_trend(z=12, subsumed_by="vision pro"), NOTIFY)

    # bursting in many subreddits of a group at once is a story even with a lower score
    def group_trend(breadth: int, members: int):
        return make_trend(z=6, scope="tech", scope_type="group", breadth=breadth, members=members)

    assert alert_worthy(group_trend(6, 9), NOTIFY)
    assert not alert_worthy(group_trend(2, 2), NOTIFY)
    # but not when it's a few of the many subreddits mentioning it
    assert not alert_worthy(group_trend(3, 31), NOTIFY)


def test_a_story_alerts_once_per_run_in_its_strongest_scope():
    trends = [
        make_trend(scope="r/technology", z=12),
        make_trend(scope="tech", scope_type="group", z=15),
        make_trend(scope="tech", scope_type="group", horizon="6h", z=11),
    ]
    assert decide(trends) == [trends[1]]
    assert [trend.alert for trend in trends] == ["", "", ""]


def test_no_alerts_without_enough_history():
    trend = make_trend(reference_days=2)
    assert decide([trend]) == []
    assert trend.alert == WARMUP


def test_cooldown_unless_the_score_doubles():
    trend = make_trend(z=15)
    earlier = SentAlert("vision pro", 10.0, trend.detected_at - timedelta(hours=30))
    assert decide([trend], [earlier]) == []
    assert trend.alert == COOLDOWN

    doubled = make_trend(z=20)
    assert decide([doubled], [earlier]) == [doubled]

    long_ago = SentAlert("vision pro", 10.0, trend.detected_at - timedelta(hours=73))
    assert decide([make_trend(z=15)], [long_ago]) != []


def test_the_cooldown_spans_scopes():
    trend = make_trend(scope="tech", scope_type="group", z=15)
    earlier = SentAlert("vision pro", 12.0, trend.detected_at - timedelta(hours=1))
    assert decide([trend], [earlier]) == []


def test_daily_cap():
    trends = [make_trend(f"term {n}", z=20 - n) for n in range(4)]
    now = trends[0].detected_at
    recent = [SentAlert(f"old {n}", 12.0, now - timedelta(hours=n + 1)) for n in range(3)]
    sent = decide(trends, recent, NotifyConfig(max_alerts_per_day=5))
    assert [trend.term for trend in sent] == ["term 0", "term 1"]
    assert [trend.alert for trend in trends[2:]] == [CAPPED, CAPPED]

    # alerts older than 24 hours don't count
    yesterday = [SentAlert(f"old {n}", 12.0, now - timedelta(hours=25)) for n in range(5)]
    fresh = [make_trend(f"term {n}", z=20 - n) for n in range(4)]
    assert len(decide(fresh, yesterday, NotifyConfig(max_alerts_per_day=5))) == 4


def test_skipped_scopes_never_alert():
    trend = make_trend(scope="sample", scope_type="group")
    assert decide([trend], notify=NotifyConfig(skip_scopes=("sample",))) == []
    assert trend.alert == SKIPPED
