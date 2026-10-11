"""Lead–lag without a database: onsets, events, edges, forecasts and their evaluation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from helpers import make_config

from wgra.config import (
    ForecastConfig,
    LeadLagConfig,
    NotifyConfig,
    parse_config,
)
from wgra.detect.scoring import Counts, Prior, score_arrays
from wgra.leadlag.edges import ALL, Edge, Network, learn_edges
from wgra.leadlag.evaluate import Evaluation, first_per_follower, scheduled_run
from wgra.leadlag.events import Event, Onset, Sighting, assign_events, event_span, topic_of
from wgra.leadlag.forecasts import (
    HIT,
    MISS,
    OFF,
    PENDING,
    EdgeIndex,
    Forecast,
    decide,
    decide_forecast_alerts,
    resolve,
)
from wgra.leadlag.onsets import first_crossings
from wgra.notify.messages import ForecastSummary, forecast_message

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
T0 = datetime(2026, 3, 2, tzinfo=UTC)


def test_score_arrays_is_counts_score_for_every_element():
    rng = np.random.default_rng(1)
    total = rng.integers(50, 5000, 200).astype(float)
    reference_total = rng.integers(0, 100_000, 200).astype(float)
    mentions = np.minimum(rng.integers(0, 100, 200), total).astype(float)
    reference_mentions = np.minimum(rng.integers(0, 500, 200), reference_total).astype(float)
    prior = Prior(total=1_000_000, weight=0.05, floor=1.0)
    log_odds, z = score_arrays(mentions, total, reference_mentions, reference_total, 300, prior)
    for i in range(200):
        score = Counts(
            int(mentions[i]),
            int(total[i]),
            int(reference_mentions[i]),
            int(reference_total[i]),
            300,
        ).score(prior)
        assert log_odds[i] == pytest.approx(score.log_odds, rel=1e-12, abs=1e-12)
        assert z[i] == pytest.approx(score.z, rel=1e-12, abs=1e-12)


SMALL = LeadLagConfig(window_hours=4, reference_days=2, min_reference_days=1)
PRIOR = Prior(total=0, weight=0.0, floor=1.0)


def series(hours: int, start: int, rate: float) -> np.ndarray:
    values = np.zeros(hours)
    values[start:] = rate
    return values


def test_first_crossing_is_the_first_hour_the_window_passes():
    hours, first = 120, 4 + 48 - 1
    totals = np.full((3, hours), 100.0)
    mentions = np.stack(
        [
            series(hours, 80, 2.0),  # 2 an hour from hour 80: 6 mentions in the window at 82
            np.full(hours, 1.0),  # always the same share: never
            series(hours, 100, 0.5),  # too few
        ]
    )
    crossings = first_crossings(mentions, totals, 0, PRIOR, first, SMALL)
    assert crossings[0] is not None
    assert crossings[0].index == 82
    assert crossings[0].mentions == 6
    assert crossings[0].ratio > SMALL.onset_min_ratio
    assert crossings[0].z >= SMALL.onset_min_z
    assert crossings[1] is None
    assert crossings[2] is None


def test_no_onset_without_enough_history():
    hours, first = 120, 51
    totals = np.full((2, hours), 100.0)
    totals[1, :70] = 0  # the second scope's data starts at hour 70
    mentions = np.stack([series(hours, 85, 2.0), series(hours, 95, 2.0)])
    crossings = first_crossings(mentions, totals, 0, PRIOR, first, SMALL)
    # with history the burst at 85 crosses at 87
    assert crossings[0] is not None and crossings[0].index == 87
    # the window must start a day (min_reference_days) after the first data: from 94 on
    assert crossings[1] is not None and crossings[1].index == 97
    early = np.stack([series(hours, 85, 2.0)] * 2)
    late_data = first_crossings(early, totals, 0, PRIOR, first, SMALL)[1]
    assert late_data is None or late_data.index >= 94 + SMALL.window_hours - 1
    with pytest.raises(ValueError):
        first_crossings(mentions, totals, 0, PRIOR, 10, SMALL)


def test_a_crossing_only_uses_the_hours_before_it():
    hours, first = 120, 51
    totals = np.full((1, hours), 100.0)
    mentions = series(hours, 80, 2.0)[None, :]
    full = first_crossings(mentions, totals, 0, PRIOR, first, SMALL)[0]
    cut = first_crossings(mentions[:, :83], totals[:, :83], 0, PRIOR, first, SMALL)[0]
    assert full == cut


def sighting(term: str, scope: str, at: datetime, z: float = 6.0) -> Sighting:
    return Sighting("word", term, scope, at, z)


def test_trends_within_a_span_are_one_event():
    settings = LeadLagConfig(lookback_hours=72, max_lag_days=7)
    sightings = [
        sighting("iphone", "r/apple", T0 + DAY, z=9),
        sighting("iphone", "r/apple", T0),
        sighting("iphone", "tech", T0 + 3 * DAY, z=7),
        # 14 days after the first: the next event
        sighting("iphone", "r/apple", T0 + 14 * DAY),
        sighting("other", "r/apple", T0),
    ]
    events = sorted(assign_events(sightings, [], settings), key=lambda e: (e.term, e.start))
    assert [(e.term, e.start) for e in events] == [
        ("iphone", T0),
        ("iphone", T0 + 14 * DAY),
        ("other", T0),
    ]
    assert events[0].scopes == {"r/apple": 9, "tech": 7}
    assert events[0].last_seen == T0 + 3 * DAY

    # stored events anchor the next run's sightings
    later = assign_events([sighting("iphone", "tech", T0 + 15 * DAY)], events, settings)
    assert [(e.start, e.last_seen) for e in later] == [(T0 + 14 * DAY, T0 + 15 * DAY)]
    # a sighting before the latest event that no event covers is dropped
    assert assign_events([sighting("iphone", "x", T0 - 30 * DAY)], events[:2], settings) == []

    span = event_span(T0 + timedelta(minutes=20), settings)
    assert span.start == T0 - 72 * HOUR
    assert span.end == T0 + 14 * DAY
    assert span.leaders_until == T0 + 7 * DAY


def test_the_topic_is_the_group_it_trended_in_most():
    groups = {"tech": ["apple", "android", "linux"], "news": ["news"], "mac": ["apple"]}
    assert topic_of({"r/linux": 8, "news": 5}, groups) == "tech"
    assert topic_of({"news": 9, "r/linux": 8}, groups) == "news"
    # r/apple is in tech and mac: the smaller group
    assert topic_of({"r/apple": 8}, groups) == "mac"
    assert topic_of({"sample": 8}, groups) == ""
    # as of a time, from the sightings
    event = Event("word", "x", T0, T0)
    for item in [sighting("x", "news", T0, 4), sighting("x", "r/linux", T0 + DAY, 9)]:
        event.add(item, keep=True)
    assert topic_of(event.scopes_at(T0), groups) == "news"
    assert topic_of(event.scopes_at(T0 + DAY), groups) == "tech"


def onset(scope: str, at: datetime, without: str = "") -> Onset:
    return Onset(scope, without, at, 10, 3.0, 5.0)


def event(start: datetime, *onsets: Onset, until: datetime | None = None) -> Event:
    return Event(
        "word",
        f"t{start:%m%d}",
        start,
        start,
        scopes={"r/a": 6.0},
        onsets=list(onsets),
        onsets_until=until,
    )


NETWORK = Network(
    ["a", "b", "c"],
    {"pair": ("a", "b"), "solo": ("c",)},
    {"a": T0 - 30 * DAY, "b": T0 - 30 * DAY, "c": T0 + 50 * DAY, "_sample": T0 - 30 * DAY},
)
LOOSE = LeadLagConfig(min_events=1, min_hits=1, max_q=1.0, topics=False)


def pairs_of(edges: list[Edge]) -> dict[tuple[str, str], Edge]:
    return {(edge.leader, edge.follower): edge for edge in edges if edge.topic == ALL}


def test_followers_of_a_leader():
    followers = {(f.scope, f.type, f.without) for f in NETWORK.followers("r/a")}
    assert followers == {
        ("r/b", "subreddit", ""),
        ("r/c", "subreddit", ""),
        # a's own group without a, c's group as it is
        ("pair", "group", "r/a"),
        ("solo", "group", ""),
        ("sample", "sample", ""),
    }
    # a group of one isn't followed by its only subreddit
    assert ("solo", "group", "r/c") not in {
        (f.scope, f.type, f.without) for f in NETWORK.followers("r/c")
    }


def test_edges_count_hits_misses_and_what_isnt_known_yet():
    events = [
        # b follows a after 2 days, and so does the rest of their group
        event(T0, onset("r/a", T0), onset("r/b", T0 + 2 * DAY), onset("pair", T0 + 2 * DAY, "r/a")),
        # b doesn't follow
        event(T0 + 20 * DAY, onset("r/a", T0 + 20 * DAY)),
        # b was first: a can't lead it here
        event(T0 + 40 * DAY, onset("r/b", T0 + 40 * DAY - HOUR), onset("r/a", T0 + 40 * DAY)),
        # the window is still open as of the run: neither a hit nor a miss yet
        event(T0 + 60 * DAY, onset("r/a", T0 + 60 * DAY)),
    ]
    as_of = T0 + 63 * DAY
    result = learn_edges(events, NETWORK, as_of, LOOSE)
    edges = pairs_of(result.edges)
    a_b = edges["r/a", "r/b"]
    assert (a_b.events, a_b.hits, a_b.leader_onsets) == (2, 1, 4)
    assert a_b.lags == [48.0]
    assert a_b.lag_median == 48
    # base rate: b crossed in 2 of the 3 closed events (the last one isn't closed)
    assert result.closed_events == 3
    assert a_b.base_rate == pytest.approx((2 + 0.5) / (3 + 1))
    assert a_b.probability == pytest.approx((1 + 4 * a_b.base_rate) / (2 + 4))
    assert a_b.lift == pytest.approx(a_b.probability / a_b.base_rate)

    rest = next(e for e in result.edges if e.follower == "pair")
    assert rest.without_leader and rest.follower_key == ("pair", "r/a")
    # in the third event b crossed an hour before a: one hit the other way around
    b_a = edges["r/b", "r/a"]
    assert (b_a.events, b_a.hits, b_a.lags) == (1, 1, [1.0])
    # r/c only has data from day 50 on (3 days of history needed): only the last event,
    # whose outcome isn't known yet
    assert ("r/a", "r/c") not in edges


def test_edges_use_nothing_after_the_run():
    # an earlier event that is over gives the base rates; without one nothing is tested
    events = [
        event(T0 - 20 * DAY, onset("sample", T0 - 20 * DAY)),
        event(T0, onset("r/a", T0), onset("r/b", T0 + 2 * DAY)),
    ]
    assert learn_edges(events[1:], NETWORK, T0 + 3 * DAY, LOOSE).tested == 0
    # a day in: b's onset hasn't happened, and the window isn't over
    assert pairs_of(learn_edges(events, NETWORK, T0 + DAY, LOOSE).edges) == {}
    # the onset's hour must be over
    at_onset = T0 + 2 * DAY
    assert ("r/a", "r/b") not in pairs_of(learn_edges(events, NETWORK, at_onset, LOOSE).edges)
    after = pairs_of(learn_edges(events, NETWORK, at_onset + HOUR, LOOSE).edges)
    assert after["r/a", "r/b"].hits == 1
    # onsets computed before as_of only know that much
    stale = [events[0], event(T0, onset("r/a", T0), onset("r/b", T0 + 2 * DAY), until=T0 + DAY)]
    assert pairs_of(learn_edges(stale, NETWORK, T0 + 30 * DAY, LOOSE).edges) == {}


def test_edges_need_significance():
    # 6 hits of 6 for b, which crosses in few other events: an edge
    leading = [
        event(
            T0 + i * 15 * DAY,
            onset("r/a", T0 + i * 15 * DAY),
            onset("r/b", T0 + i * 15 * DAY + 3 * DAY),
        )
        for i in range(6)
    ]
    # bursts in c only, followed by nothing
    others = [
        event(T0 + i * 7 * DAY + HOUR, onset("r/c", T0 + i * 7 * DAY + HOUR)) for i in range(25)
    ]
    strict = LeadLagConfig(topics=False)
    result = learn_edges(leading + others, NETWORK, T0 + 175 * DAY, strict)
    assert [(e.leader, e.follower) for e in result.edges] == [("r/a", "r/b")]
    edge = result.edges[0]
    assert edge.q_value <= strict.max_q
    assert edge.lag_median == 72
    assert edge.probability_low < edge.probability < edge.probability_high
    # c's bursts were tested too, they're just never followed
    assert result.tested > len(NETWORK.followers("r/a"))

    # with as few events, but b crossing in most events anyway, a's lead says nothing
    common = [event(e.start, *e.onsets, onset("r/b", e.start + 2 * HOUR)) for e in others]
    result = learn_edges(leading + common, NETWORK, T0 + 175 * DAY, strict)
    assert ("r/a", "r/b") not in pairs_of(result.edges)


EDGE = Edge(
    topic=ALL,
    leader="r/a",
    follower="r/b",
    follower_type="subreddit",
    without_leader=False,
    leader_onsets=12,
    events=10,
    hits=8,
    hit_rate=0.8,
    base_rate=0.2,
    probability=0.8,
    probability_low=0.6,
    probability_high=0.9,
    lift=4.0,
    p_value=1e-5,
    q_value=1e-4,
    lag_median=48,
    lag_q25=24,
    lag_q75=72,
    lags=[24.0, 48.0, 72.0],
)


def test_a_forecast_for_a_follower_that_hasnt_started():
    settings, forecast_settings = LeadLagConfig(), ForecastConfig()
    start = T0
    current = event(start, onset("r/a", start - 10 * HOUR + 10 * HOUR))
    now = start + 10 * HOUR
    index = EdgeIndex([EDGE])
    [made] = decide(current, {"r/a"}, index, now, {}, settings, forecast_settings)
    assert (made.leader, made.follower, made.outcome) == ("r/a", "r/b", PENDING)
    # 10 hours passed: all three past hits took longer
    still = 3.5 / 4
    assert made.probability == pytest.approx(0.8 * still / (0.2 + 0.8 * still))
    assert made.expected_at == start + 48 * HOUR
    assert made.due_by == start + 7 * DAY
    assert (made.edge_events, made.edge_hits, made.lift) == (10, 8, 4.0)

    # not for a leader that isn't trending now, a follower that started, or too late
    assert decide(current, {"r/c"}, index, now, {}, settings, forecast_settings) == []
    started = event(start, onset("r/a", start), onset("r/b", start + 5 * HOUR))
    assert decide(started, {"r/a"}, index, now, {}, settings, forecast_settings) == []
    late = start + 7 * DAY
    assert decide(current, {"r/a"}, index, late, {}, settings, forecast_settings) == []
    # or for edges below the gates
    strict = ForecastConfig(min_lift=5)
    assert decide(current, {"r/a"}, index, now, {}, settings, strict) == []
    unlikely = ForecastConfig(min_probability=0.95)
    assert decide(current, {"r/a"}, index, now, {}, settings, unlikely) == []

    # resolved as a hit once the follower crosses, as a miss after the due time
    current.onsets.append(onset("r/b", start + 40 * HOUR))
    assert not resolve(made, current, start + 40 * HOUR)  # the hour isn't over
    assert resolve(made, current, start + 41 * HOUR)
    assert (made.outcome, made.follower_onset) == (HIT, start + 40 * HOUR)
    assert not resolve(made, current, start + 50 * HOUR)

    [other] = decide(
        event(start, onset("r/a", start)), {"r/a"}, index, now, {}, settings, forecast_settings
    )
    nothing = event(start, onset("r/a", start))
    assert not resolve(other, nothing, start + 7 * DAY)
    assert resolve(other, nothing, start + 7 * DAY + HOUR)
    assert other.outcome == MISS


def test_topic_edges_win_over_all():
    topical = replace(EDGE, topic="tech", probability=0.95, lift=5.0)
    index = EdgeIndex([EDGE, topical])
    assert index.of("r/a", "tech") == [topical]
    assert index.of("r/a", "news") == [EDGE]
    assert index.of("r/a", "") == [EDGE]
    assert index.leaders == {"r/a"} and len(index) == 1


def forecast(term: str, probability: float, **values: object) -> Forecast:
    fields: dict[str, object] = {
        "kind": "word",
        "term": term,
        "event_start": T0,
        "follower": "r/b",
        "leader": "r/a",
        "follower_type": "subreddit",
        "without_leader": False,
        "topic": ALL,
        "created_at": T0,
        "leader_onset": T0,
        "expected_at": T0 + 2 * DAY,
        "due_by": T0 + 7 * DAY,
        "probability": probability,
        "probability_low": probability - 0.1,
        "probability_high": probability + 0.1,
        "base_rate": 0.2,
        "lift": 4.0,
        "edge_events": 20,
        "edge_hits": 15,
        "lag_q25": 24.0,
        "lag_median": 48.0,
        "lag_q75": 72.0,
    }
    fields.update(values)
    return Forecast(**fields)  # type: ignore[arg-type]


def test_forecast_alerts_are_off_by_default_and_share_the_cap():
    new = [forecast("one", 0.9), forecast("two", 0.8), forecast("three", 0.7)]
    notify = NotifyConfig(max_alerts_per_day=5)
    assert decide_forecast_alerts(new, 0, 0, notify, ForecastConfig()) == []
    assert {item.alert for item in new} == {OFF}

    on = ForecastConfig(alert=True, alert_min_probability=0.75, alert_max_per_day=2)
    new = [forecast("one", 0.9), forecast("two", 0.8), forecast("three", 0.7)]
    assert [item.term for item in decide_forecast_alerts(new, 0, 0, notify, on)] == ["one", "two"]
    # 4 alerts today already: one left of the cap
    new = [forecast("one", 0.9), forecast("two", 0.8)]
    assert [item.term for item in decide_forecast_alerts(new, 4, 0, notify, on)] == ["one"]
    assert new[1].alert == "capped"
    # forecast alerts have their own share of it
    new = [forecast("one", 0.9)]
    assert decide_forecast_alerts(new, 2, 2, notify, on) == []
    # one alert per term, its likeliest follower; edges with few events don't alert
    new = [
        forecast("one", 0.9),
        forecast("one", 0.95, follower="sample"),
        forecast("few", 0.99, edge_events=3),
    ]
    sent = decide_forecast_alerts(new, 0, 0, notify, on)
    assert [(item.term, item.follower) for item in sent] == [("one", "sample")]


def test_evaluation_scores_and_calibration():
    scored = [
        forecast("a", 0.9, outcome=HIT, follower_onset=T0 + 2 * DAY),
        forecast("b", 0.9, outcome=HIT, follower_onset=T0 + DAY),
        forecast("c", 0.3, outcome=MISS),
        forecast("d", 0.3, outcome=HIT, follower_onset=T0 + 3 * DAY),
    ]
    evaluation = Evaluation(
        T0, T0 + DAY, 10, 4, 1, 5, forecasts=scored, scored=scored, followed=5, forecast_in_time=3
    )
    assert evaluation.precision == 0.75
    assert evaluation.recall == 0.6
    assert evaluation.lead_hours() == [24.0, 48.0, 72.0]
    brier, base = evaluation.brier() or (0, 0)
    assert brier == pytest.approx((0.01 + 0.01 + 0.09 + 0.49) / 4)
    assert base == pytest.approx((0.64 * 3 + 0.04) / 4)
    bins = {(round(b.low, 1), b.forecasts, round(b.observed, 2)) for b in evaluation.calibration()}
    assert bins == {(0.2, 2, 0.5), (0.8, 2, 1.0)}


def test_the_first_forecast_per_follower_counts():
    early = forecast("x", 0.6, created_at=T0)
    later = forecast("x", 0.9, created_at=T0 + HOUR, leader="r/c")
    likelier = forecast("x", 0.7, created_at=T0, leader="r/d")
    assert first_per_follower([later, early, likelier]) == [likelier]


def test_scheduled_run():
    assert scheduled_run(datetime(2026, 3, 2, 0, 0, tzinfo=UTC), "01:00") == datetime(
        2026, 3, 1, 1, 0, tzinfo=UTC
    )
    assert scheduled_run(datetime(2026, 3, 2, 1, 30, tzinfo=UTC), "01:00") == datetime(
        2026, 3, 2, 1, 0, tzinfo=UTC
    )


def test_config():
    config = make_config(
        lead_lag={"max_lag_days": 5, "min_events": 8, "run_at": "02:30"},
        forecast={"alert": True, "min_probability": 0.4},
        wikipedia={"enabled": True, "project": "de.wikipedia"},
    )
    assert config.lead_lag.max_lag_days == 5
    assert config.lead_lag.min_events == 8
    assert config.forecast.alert is True
    assert config.wikipedia.project == "de.wikipedia"
    # off by default: forecast alerts and Wikipedia
    defaults = make_config()
    assert defaults.forecast.alert is False
    assert defaults.wikipedia.enabled is False
    assert defaults.lead_lag.enabled and defaults.forecast.enabled
    for bad in (
        {"lead_lag": {"run_at": "25:00"}},
        {"lead_lag": {"interval": 1.5}},
        {"lead_lag": {"max_lag_days": 0}},
        {"forecast": {"min_probability": 2}},
        {"lead_lag": {"unknown": 1}},
    ):
        with pytest.raises((ValueError, TypeError)):
            parse_config({"groups": {"tech": ["technology"]}, **bad})


def test_forecast_message():
    message = forecast_message(
        ForecastSummary(
            term="ollama",
            leader="r/localllama",
            follower="sample",
            leader_onset=datetime(2026, 10, 13, 14, tzinfo=UTC),
            expected_at=datetime(2026, 10, 15, 14, tzinfo=UTC),
            due_by=datetime(2026, 10, 20, 14, tzinfo=UTC),
            probability=0.62,
            probability_low=0.45,
            probability_high=0.78,
            base_rate=0.09,
            edge_events=15,
            edge_hits=12,
            lag_median=60,
        ),
        "https://grafana.test",
    )
    assert message.title == "ollama: r/localllama → sample?"
    assert "Rising in r/localllama since Tue 14:00 UTC." in message.body
    assert "Of 15 terms that rose in r/localllama before reddit-wide (the r/all sample), 12 " in (
        message.body
    )
    assert "within 7.0 days, after 2.5 days (median)" in message.body
    assert "Chance this time: 62% (45%–78%), against 9% for any trending term" in message.body
    assert message.click.startswith("https://grafana.test/d/wgra-terms?var-terms=ollama")
    assert ("Early warning", "https://grafana.test/d/wgra-early-warning") in message.links
