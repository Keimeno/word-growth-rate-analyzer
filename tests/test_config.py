from pathlib import Path

import pytest
import yaml
from helpers import make_config

from wgra.config import (
    SAMPLE_GROUP,
    SAMPLE_SCOPE,
    TRACKED_GROUP,
    Env,
    load_config,
    parse_config,
)
from wgra.text.intents import INTENT_KINDS


def test_subreddit_names_are_normalized_and_deduplicated():
    config = parse_config({"groups": {"a": ["r/Rust", "/r/golang", "rust"], "b": ["Rust"]}})
    assert config.groups == {"a": ("golang", "rust"), "b": ("rust",)}
    assert config.subreddits == ("golang", "rust")


def test_group_memberships_include_tracked_and_sample():
    memberships = make_config().group_memberships()
    assert (TRACKED_GROUP, "technology") in memberships
    assert (TRACKED_GROUP, "de") in memberships
    assert (SAMPLE_GROUP, SAMPLE_SCOPE) in memberships
    assert ("tech", "technology") in memberships


def test_languages_default_to_english():
    config = make_config()
    assert config.language("de") == "de"
    assert config.language("technology") == "en"


def test_scope_pools_untracked_subreddits():
    config = make_config()
    assert config.scope("technology") == "technology"
    assert config.scope("askreddit") == SAMPLE_SCOPE


@pytest.mark.parametrize("name", [TRACKED_GROUP, SAMPLE_GROUP])
def test_reserved_group_names(name):
    with pytest.raises(ValueError, match="reserved"):
        parse_config({"groups": {name: ["rust"]}})


def test_a_group_is_required():
    with pytest.raises(ValueError, match="at least one group"):
        parse_config({"groups": {}})


def test_detect_and_notify_defaults():
    config = make_config()
    assert [h.name for h in config.detect.horizons] == ["24h", "6h"]
    assert config.detect.horizons[1].same_hours
    assert config.detect.thresholds_for("tech").min_mentions == 10
    assert config.notify.max_alerts_per_day == 5


def test_detect_thresholds_with_per_scope_overrides():
    config = make_config(
        detect={
            "min_mentions": 20,
            "min_ratio": 3,
            "prior_weight": 0.1,
            "horizons": {"12h": {"window_hours": 12, "reference_days": 14}},
            "scopes": {"r/DE": {"min_mentions": 5}},
            "exclude_scopes": ["sample"],
        },
        notify={"digest_time": "07:30", "timezone": "Europe/Berlin", "skip_scopes": []},
    )
    detect = config.detect
    assert detect.thresholds_for("tech").min_mentions == 20
    assert detect.thresholds_for("r/de").min_mentions == 5
    # unchanged settings of an override come from the defaults above it
    assert detect.thresholds_for("r/de").min_ratio == 3
    assert detect.prior_weight == 0.1
    assert [(h.name, h.window_hours, h.reference_days) for h in detect.horizons] == [
        ("12h", 12, 14)
    ]
    assert detect.exclude_scopes == ("sample",)
    assert config.notify.timezone == "Europe/Berlin"
    assert config.notify.skip_scopes == ()


@pytest.mark.parametrize(
    "notify", [{"digest_time": "8 am"}, {"digest_time": "25:00"}, {"timezone": "Mars/Base"}]
)
def test_invalid_notify_settings(notify):
    with pytest.raises(Exception, match=r"digest_time|Mars"):
        make_config(notify=notify)


def test_the_shipped_config_parses():
    config = load_config(Path(__file__).parent.parent / "config.yaml")
    assert config.detect.horizons
    assert "tech" in config.groups


def test_empty_notification_settings_mean_the_defaults(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "x")
    monkeypatch.setenv("NTFY_URL", "")
    monkeypatch.setenv("NTFY_TOPIC", "")
    monkeypatch.setenv("GRAFANA_URL", "https://grafana.example/")
    env = Env.from_environ(require_reddit=False)
    assert env.ntfy_url == "http://localhost:3609"
    assert env.ntfy_topic == "wgra"
    assert env.grafana_url == "https://grafana.example"


def test_long_term_defaults_and_overrides():
    defaults = make_config().long_term
    assert defaults.horizons == (13, 26, 52)
    assert defaults.group_rate == "macro"
    assert defaults.min_mentions_per_week == 20
    config = make_config(
        long_term={
            "horizons": [26, 13, 13],
            "group_rate": "pooled",
            "run_at": "01:15",
            "exclude_scopes": ["r/DE", "tracked"],
        },
        notify={"report_day": "Sunday", "report_time": "18:00", "report_size": 3},
    )
    assert config.long_term.horizons == (13, 26)
    assert config.long_term.group_rate == "pooled"
    assert config.long_term.exclude_scopes == ("r/de", "tracked")
    assert (config.notify.report_day, config.notify.report_time) == ("sunday", "18:00")


@pytest.mark.parametrize(
    ("section", "values", "message"),
    [
        ("long_term", {"group_rate": "median"}, "macro or pooled"),
        ("long_term", {"horizons": [2]}, "at least 4"),
        ("long_term", {"run_at": "midnight"}, "run_at"),
        ("long_term", {"min_growth": 0.95}, "above 1"),
        ("notify", {"report_day": "someday"}, "weekday"),
        ("notify", {"report_time": "25:00"}, "report_time"),
    ],
)
def test_invalid_long_term_settings(section, values, message):
    with pytest.raises(ValueError, match=message):
        make_config(**{section: values})


def test_intents_have_their_own_gates_by_default():
    detect = make_config().detect
    assert set(detect.kinds) >= {
        "word",
        "switch",
        "alternative",
        "complaint",
        "need",
        "considering",
    }
    switch = detect.thresholds_for("tech", "switch")
    assert (switch.min_mentions, switch.min_authors, switch.min_z) == (3, 3, 3.0)
    considering = detect.thresholds_for("tech", "considering")
    assert (considering.min_mentions, considering.min_authors) == (3, 3)
    assert detect.max_stored("considering") == 20
    assert detect.thresholds_for("tech", "word").min_mentions == 10
    assert (detect.max_stored("word"), detect.max_stored("need")) == (50, 20)
    config = make_config()
    assert config.long_term.min_mentions_per_week_for("switch") == 2
    assert config.long_term.min_mentions_per_week_for("phrase") == 20
    assert config.lead_lag.onset_min_mentions_for("complaint") == 3
    assert config.lead_lag.onset_min_mentions_for("word") == 5
    assert config.long_term.min_mentions_per_week_for("considering") == 2
    assert config.lead_lag.onset_min_mentions_for("considering") == 3
    assert config.intents.enabled and config.intents.sample


def test_kind_thresholds_go_on_top_of_scope_thresholds():
    config = make_config(
        detect={
            "min_mentions": 12,
            "scopes": {"r/de_EDV": {"min_mentions": 5, "min_authors": 2}},
            "kind_thresholds": {"switch": {"min_mentions": 2}, "domain": {"min_ratio": 3}},
        }
    )
    detect = config.detect
    # what a kind sets wins, the rest comes from the scope
    assert detect.thresholds_for("r/de_edv", "switch").min_mentions == 2
    assert detect.thresholds_for("r/de_edv", "switch").min_authors == 3
    assert detect.thresholds_for("r/de_edv", "word").min_authors == 2
    assert detect.thresholds_for("tech", "domain").min_ratio == 3
    # the other intents keep their defaults
    assert detect.thresholds_for("tech", "need").min_mentions == 3


def test_per_kind_settings_are_checked():
    with pytest.raises(ValueError, match="unknown kinds: swtich"):
        make_config(detect={"kind_thresholds": {"swtich": {"min_mentions": 2}}})
    with pytest.raises(ValueError, match="unknown min_mention"):
        make_config(detect={"kind_thresholds": {"switch": {"min_mention": 2}}})
    with pytest.raises(ValueError, match="unknown kinds"):
        make_config(long_term={"kind_min_mentions_per_week": {"swtich": 1}})
    config = make_config(
        long_term={"kind_min_mentions_per_week": {"need": 5}},
        lead_lag={"kind_onset_min_mentions": {"switch": 2}},
        intents={"sample": False},
    )
    assert config.long_term.min_mentions_per_week_for("need") == 5
    assert config.long_term.min_mentions_per_week_for("switch") == 2
    assert config.lead_lag.onset_min_mentions_for("switch") == 2
    assert not config.intents.sample


def test_the_shipped_config_parses_with_intents():
    config = load_config(Path(__file__).parents[1] / "config.yaml")
    assert config.intents.enabled
    assert config.detect.thresholds_for("tech", "switch").min_mentions <= 5
    # every intent kind has its gates written out in the shipped config
    raw = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text())
    assert set(raw["detect"]["kind_thresholds"]) == set(INTENT_KINDS)
    assert set(raw["long_term"]["kind_min_mentions_per_week"]) == set(INTENT_KINDS)
    assert set(raw["lead_lag"]["kind_onset_min_mentions"]) == set(INTENT_KINDS)
