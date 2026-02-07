from pathlib import Path

import pytest
from helpers import make_config

from wgra.config import (
    SAMPLE_GROUP,
    SAMPLE_SCOPE,
    TRACKED_GROUP,
    Env,
    load_config,
    parse_config,
)


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
