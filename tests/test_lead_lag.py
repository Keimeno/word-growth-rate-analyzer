"""Lead–lag end to end against a real ClickHouse, on ten weeks of synthetic history with a
planted structure (lead_lag_history.py): r/a leads r/b by 3 days, the sample follows r/a
by 5 days on two thirds of those terms, r/c bursts at random.

Uses a throwaway database shared by the tests of this module (conftest.py), skipped when
ClickHouse isn't reachable locally. Building it runs the detector once a day over the
history, like the live loop, so the events come from real trends.
"""

import json
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from helpers import make_config
from lead_lag_history import END, GROUPS, LEAD, SAMPLE_LEAD, START, build, detect_daily

from wgra.config import SAMPLE_SCOPE, Env
from wgra.detect.replay import replay, stored_steps
from wgra.detect.run import Analyzer
from wgra.detect.short_term import Detector
from wgra.leadlag.edges import ALL, Edge, Network, learn_edges, load_edges
from wgra.leadlag.evaluate import evaluate, report
from wgra.leadlag.events import load_events
from wgra.leadlag.forecasts import HIT, OFF, PENDING, load_forecasts, write_forecasts
from wgra.leadlag.onsets import OnsetFinder
from wgra.leadlag.run import LeadLag
from wgra.notify.ntfy import Ntfy

# the tracked group adds nothing here and costs a third of the detector's time
CONFIG = make_config(groups=GROUPS, detect={"exclude_scopes": ["tracked"]})
HOURS = 3600


@pytest.fixture(scope="module")
def history_db(module_client):
    history = build(module_client, CONFIG)
    detect_daily(module_client, CONFIG, START + timedelta(days=4), END)
    learned = LeadLag(module_client, CONFIG).learn(END)
    return module_client, history, learned


def edges_by_pair(edges: list[Edge], topic: str = ALL) -> dict[tuple[str, str], Edge]:
    return {(edge.leader, edge.follower): edge for edge in edges if edge.topic == topic}


def involves_c(edge: Edge) -> bool:
    # "first" without r/a is r/c alone
    return "r/c" in (edge.leader, edge.follower) or (
        edge.follower == "first" and edge.leader == "r/a" and edge.without_leader
    )


def test_recovers_the_planted_lead(history_db):
    client, history, learned = history_db
    assert learned.edges.training_events == len({burst.term for burst in history.bursts}), (
        "every planted term trended and became one event"
    )
    day, edges = load_edges(client)
    assert day == learned.as_of.date()
    found = edges_by_pair(edges)

    a_b = found["r/a", "r/b"]
    assert a_b.lag_median == pytest.approx(LEAD.total_seconds() / HOURS, abs=6)
    assert a_b.lag_q25 >= 72 - 8 and a_b.lag_q75 <= 72 + 8
    assert a_b.hits >= 16 and a_b.hit_rate >= 0.9
    assert a_b.q_value <= CONFIG.lead_lag.max_q
    assert a_b.lift > 1.5
    assert a_b.probability_low < a_b.probability < a_b.probability_high

    # reddit-wide follows r/a on two thirds of its terms, 5 days later
    a_sample = found["r/a", "sample"]
    assert a_sample.lag_median == pytest.approx(SAMPLE_LEAD.total_seconds() / HOURS, abs=6)
    assert 0.5 < a_sample.hit_rate < 0.8

    # the other way around, nothing
    assert ("r/b", "r/a") not in found
    # r/c is random: no edges at all, in any topic
    assert not [edge for edge in edges if involves_c(edge)]


def test_onsets_are_where_the_bursts_start(history_db):
    client, history, _ = history_db
    events = {event.term: event for event in load_events(client, START, END)}
    # an event is closed once its span (to 14 days after its first trend) is over
    assert all(
        event.closed == (event.start + timedelta(days=14) <= END) for event in events.values()
    )
    for burst in history.bursts:
        scope = "sample" if burst.subreddit == SAMPLE_SCOPE else f"r/{burst.subreddit}"
        onsets = {o.scope: o for o in events[burst.term].onsets if not o.without}
        # 2–4 mentions an hour need a few hours for the onset gates
        assert burst.start <= onsets[scope].at <= burst.start + timedelta(hours=8), burst
    lead = events[history.leading[3]]
    scopes = {(o.scope, o.without) for o in lead.onsets}
    # r/b's burst carries its group, with or without r/d and r/e; r/a's carries "first"
    assert {("second", ""), ("second", "r/d"), ("second", "r/e"), ("first", "")} <= scopes
    # the rest of "second" without r/b never crossed: d and e don't burst on lead terms
    assert ("second", "r/b") not in scopes
    # nothing in r/a for terms that never burst there
    for term in history.random + history.background:
        assert "r/a" not in {o.scope for o in events[term].onsets}


def test_edges_use_no_data_after_the_run(history_db):
    client, _, _ = history_db
    as_of = START + timedelta(days=40)
    stored = load_events(client, START, as_of)
    # the same events, their onsets computed only from the data before as_of
    fresh = load_events(client, START, as_of)
    OnsetFinder(client, CONFIG).find(fresh, as_of)
    assert {e.key for e in fresh} == {e.key for e in stored}
    network = Network.load(client)
    with_all_data = learn_edges(stored, network, as_of, CONFIG.lead_lag)
    without = learn_edges(fresh, network, as_of, CONFIG.lead_lag)
    assert edges_by_pair(with_all_data.edges) == edges_by_pair(without.edges)
    assert with_all_data.tested == without.tested
    # by then r/a -> r/b is already there, from fewer events
    early = edges_by_pair(without.edges)["r/a", "r/b"]
    assert 5 <= early.events < edges_by_pair(load_edges(client)[1])["r/a", "r/b"].events


def test_rerunning_replaces_the_days_edges(history_db):
    client, _, learned = history_db
    again = LeadLag(client, CONFIG).learn(END + timedelta(hours=2))
    assert again.as_of.date() == learned.as_of.date()
    assert again.new_sightings > 0  # the last span's trends are read again, harmlessly
    (count,) = client.query(
        "SELECT count() FROM propagation_edges WHERE day = {day:Date}",
        parameters={"day": learned.as_of.date()},
    ).result_rows[0]
    assert count == len(again.edges.edges) == len(learned.edges.edges)
    (events,) = client.query("SELECT count() FROM lead_lag_events FINAL").result_rows[0]
    assert events == learned.edges.training_events


def test_replay_measures_forecast_precision(history_db):
    client, _, _ = history_db
    config = CONFIG
    result = replay(
        client,
        config,
        START + timedelta(days=4),
        END,
        step=timedelta(days=1),
        horizons=[config.detect.horizons[0]],
        forecast_min_z=config.lead_lag.event_min_z,
    )
    evaluation = evaluate(client, config, result.sighting_steps, END)
    assert evaluation.events >= 40
    # the first weeks are spent learning, after that every lead term is forecast
    assert len(evaluation.scored) >= 8
    assert evaluation.precision is not None and evaluation.precision >= 0.8
    assert evaluation.recall is not None and evaluation.recall > 0.15
    # once an edge exists, most of the followers that follow it are forecast in time
    assert evaluation.recall_on_edges is not None and evaluation.recall_on_edges >= 0.6
    assert not [f for f in evaluation.forecasts if "r/c" in (f.leader, f.follower)]
    # b follows a after 3 days, the forecasts come a day after a: about 2 days of warning
    leads = evaluation.lead_hours()
    assert 24 <= leads[len(leads) // 2] <= 72
    brier = evaluation.brier()
    assert brier is not None and brier[0] < brier[1]
    text = report(evaluation)
    assert "precision" in text and "recall on edges" in text and "calibration" in text
    # replays write nothing
    (count,) = client.query("SELECT count() FROM forecasts").result_rows[0]
    assert count == 0

    # from the stored trends instead of the detector: the same forecasts
    steps = stored_steps(
        client, START + timedelta(days=4), END, timedelta(days=1), config.lead_lag.event_min_z
    )
    stored = evaluate(client, config, steps, END)
    assert len(stored.scored) == len(evaluation.scored)
    assert stored.precision == evaluation.precision


def recording_ntfy() -> tuple[Ntfy, list[dict]]:
    sent: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    return Ntfy("http://ntfy", "wgra", transport=httpx.MockTransport(handle)), sent


def test_forecasts_in_the_live_loop(history_db):
    client, history, _ = history_db
    term = history.leading[-1]
    a_start = history.first_burst("a", term)
    b_start = history.first_burst("b", term)
    now = a_start + timedelta(hours=20)
    trends = Detector(client, CONFIG).run(now.replace(minute=0) + timedelta(hours=1), now)
    assert any(t.term == term and t.scope == "r/a" for t in trends)

    ntfy, sent = recording_ntfy()
    env = Env("", "", "", b"", "", 0, "", "", "", grafana_url="https://grafana.test")
    on = replace(CONFIG.forecast, alert=True, alert_min_probability=0.5, alert_min_events=5)
    analyzer = Analyzer(replace(CONFIG, forecast=on), env, client, ntfy)
    step = analyzer.run_forecasts(now, trends)
    made = {(f.leader, f.follower): f for f in step.new if f.term == term}
    a_b = made["r/a", "r/b"]
    assert a_b.outcome == PENDING
    assert a_b.created_at == now
    assert a_b.expected_at == pytest.approx(
        a_b.leader_onset + timedelta(hours=a_b.lag_median), abs=timedelta(hours=24)
    )
    assert 0.5 < a_b.probability < 1
    assert not [f for f in step.new if "r/c" in (f.leader, f.follower)]
    # one alert, the likeliest follower
    assert [message["title"] for message in sent] == [f"{term}: r/a → {a_b.follower}?"]
    assert {f.alert for f in step.new} <= {"sent", "", "capped"}

    # the same run again: nothing new
    assert analyzer.run_forecasts(now + timedelta(minutes=15), trends).new == []
    # after r/b's burst the forecast is resolved as a hit
    later = b_start + timedelta(hours=10)
    resolved = analyzer.run_forecasts(later, [])
    outcome = {(f.leader, f.follower): f for f in resolved.resolved if f.term == term}
    assert outcome["r/a", "r/b"].outcome == HIT
    assert b_start <= outcome["r/a", "r/b"].follower_onset <= b_start + timedelta(hours=8)
    stored = {
        (f.leader, f.follower): f
        for f in load_forecasts(client, event_keys=[(a_b.kind, a_b.term, a_b.event_start)])
    }
    assert stored["r/a", "r/b"].outcome == HIT
    # the probability is the one it was made with
    assert stored["r/a", "r/b"].probability == pytest.approx(a_b.probability)


def test_forecast_alerts_are_off_by_default(history_db):
    client, history, _ = history_db
    term = history.leading[-2]
    now = history.first_burst("a", term) + timedelta(hours=20)
    trends = Detector(client, CONFIG).run(now.replace(minute=0) + timedelta(hours=1), now)
    ntfy, sent = recording_ntfy()
    env = Env("", "", "", b"", "", 0, "", "", "")
    step = Analyzer(CONFIG, env, client, ntfy).run_forecasts(now, trends)
    assert [f for f in step.new if f.term == term]
    assert {f.alert for f in step.new} == {OFF}
    assert sent == []
    write_forecasts(client, [])  # nothing to write is fine
