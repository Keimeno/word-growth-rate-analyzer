import pytest
from helpers import make_config

from wgra.config import SAMPLE_GROUP, SAMPLE_SCOPE, TRACKED_GROUP, parse_config


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
