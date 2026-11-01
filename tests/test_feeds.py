import pytest
from helpers import make_config, make_item, no_sample

from undercurrent.sources.reddit.feeds import (
    MAX_SAMPLE_POLLS_IN_FLIGHT,
    FeedScheduler,
    build_feeds,
    observed_rate,
)


def listing(newest_id: int, count: int, seconds_apart: float, newest_time: int = 1_700_000_000):
    """A listing like reddit returns it: newest first, ids and timestamps descending."""
    return [
        make_item(newest_id - index, int(newest_time - index * seconds_apart))
        for index in range(count)
    ]


def test_subreddits_are_packed_into_comment_and_post_feeds():
    config = make_config(platforms={"reddit": {"max_subreddits_per_feed": 2}})
    feeds = build_feeds(config)
    assert [(feed.name, feed.subreddits) for feed in feeds] == [
        ("comments-1", ("de", "programming")),
        ("posts-1", ("de", "programming")),
        ("comments-2", ("technology",)),
        ("posts-2", ("technology",)),
        ("posts-all", ("all",)),
        ("sample-all", ("all",)),
    ]
    assert feeds[0].path == "/r/de+programming/comments"
    assert feeds[1].path == "/r/de+programming/new"
    assert feeds[-2].path == "/r/all/new"
    assert feeds[-2].complete
    assert feeds[-1].sample


def test_the_sample_feed_can_be_disabled():
    feeds = build_feeds(make_config(platforms=no_sample()))
    assert not any("all" in feed.subreddits for feed in feeds)


def test_r_alls_posts_can_be_left_out():
    feeds = build_feeds(make_config(platforms={"reddit": {"sample": {"posts": False}}}))
    assert [feed.name for feed in feeds if "all" in feed.subreddits] == ["sample-all"]


def test_observed_rate_uses_the_listing_time_span():
    assert observed_rate(listing(1000, 101, seconds_apart=2)) == pytest.approx(0.5)
    assert observed_rate(listing(1000, 1, seconds_apart=2)) is None
    # many items within the same second
    assert observed_rate(listing(1000, 50, seconds_apart=0)) == 49


def test_busy_feeds_are_polled_often_enough_to_see_half_a_listing_per_poll():
    config = make_config(platforms=no_sample())
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments = feeds[0]

    # one new comment per second
    scheduler.record_success(comments, listing(1000, 100, seconds_apart=1), now=0)
    assert comments.interval == pytest.approx(50 / (99 / 99))
    assert comments.next_poll_at == pytest.approx(comments.interval)


def test_quiet_feeds_are_polled_at_the_maximum_interval():
    config = make_config(platforms=no_sample())
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    posts = feeds[1]

    # one post per hour
    scheduler.record_success(posts, listing(1000, 100, seconds_apart=3600), now=0)
    assert posts.interval == config.platforms.reddit.max_post_poll_interval


def test_intervals_stretch_when_the_budget_is_exceeded():
    config = make_config(
        platforms=no_sample(requests_per_minute=10, max_subreddits_per_feed=100),
    )
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments, posts = feeds

    # 50 comments per second would need a poll every second = 60 requests per minute
    scheduler.record_success(comments, listing(10_000, 100, seconds_apart=0.02), now=0)
    scheduler.record_success(posts, listing(1000, 100, seconds_apart=3600), now=0)

    demand = (
        60 / config.platforms.reddit.min_poll_interval
        + 60 / config.platforms.reddit.max_post_poll_interval
    )
    scale = demand / 10
    assert comments.interval == pytest.approx(config.platforms.reddit.min_poll_interval * scale)
    total = sum(60 / feed.interval for feed in feeds)
    assert total == pytest.approx(10)


def test_a_full_listing_of_unseen_items_is_a_gap_and_speeds_up_polling():
    config = make_config(platforms=no_sample())
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments = feeds[0]

    first = scheduler.record_success(comments, listing(1000, 100, seconds_apart=1), now=0)
    assert not first.gap
    rate = comments.rate
    assert rate is not None

    overlapping = scheduler.record_success(comments, listing(1050, 100, seconds_apart=1), now=50)
    assert not overlapping.gap

    # ids 1051..1149 were never seen and the listing is full: we missed some
    gap = scheduler.record_success(comments, listing(1250, 100, seconds_apart=1), now=100)
    assert gap.gap
    assert comments.rate == pytest.approx(rate * 2)
    assert comments.newest_id == 1250


def test_the_sample_feed_reports_how_far_reddit_ids_advanced():
    config = make_config(platforms={"reddit": {"sample": {"requests_per_minute": 20}}})
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    sample = feeds[-1]

    scheduler.record_success(sample, listing(1000, 20, seconds_apart=0), now=0)
    outcome = scheduler.record_success(sample, listing(1300, 20, seconds_apart=0), now=3)
    assert outcome.id_span == 300
    assert not outcome.gap
    assert sample.interval == pytest.approx(3.0)


def test_failures_back_off_exponentially_and_honor_retry_after():
    config = make_config()
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    feed = feeds[0]

    scheduler.record_failure(feed, now=100)
    assert feed.next_poll_at == 105
    scheduler.record_failure(feed, now=100)
    assert feed.next_poll_at == 110
    scheduler.record_failure(feed, now=100, retry_after=60)
    assert feed.next_poll_at == 160

    scheduler.record_success(feed, listing(1000, 10, seconds_apart=10), now=200)
    assert feed.failures == 0


def test_feeds_are_due_when_their_time_has_come():
    config = make_config()
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    for index, feed in enumerate(feeds):
        feed.next_poll_at = 10 - index
    assert scheduler.next_due_at() == 10 - (len(feeds) - 1)
    assert scheduler.due(9) == feeds[1:]


def test_polls_overlap_up_to_a_limit():
    config = make_config(
        platforms={
            "reddit": {
                "max_subreddits_per_feed": 100,
                "sample": {"requests_per_minute": 60, "posts": False},
            }
        }
    )
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments, posts, sample = feeds

    assert scheduler.due(0) == feeds
    for feed in feeds:
        scheduler.start(feed, now=0)
    # each next poll is due an interval later, answered or not: the sample's a second
    assert scheduler.due(1) == [sample]
    for now in range(1, MAX_SAMPLE_POLLS_IN_FLIGHT):
        scheduler.start(sample, now)
    assert sample.next_poll_at == MAX_SAMPLE_POLLS_IN_FLIGHT
    # as many unanswered as it may: the sample waits for an answer
    assert scheduler.due(1000) == [comments, posts]
    # a complete feed's poll overlaps one slow answer, not two
    assert scheduler.due(300) == [comments]
    scheduler.start(comments, now=300)
    assert scheduler.due(1000) == [posts]

    # an answer reschedules from the last poll started, which may not be its own
    scheduler.record_success(comments, listing(1000, 100, seconds_apart=1), now=0)
    scheduler.finish(comments)
    assert comments.next_poll_at == 300 + 50
    scheduler.record_success(sample, listing(1000, 20, seconds_apart=0), now=0)
    scheduler.finish(sample)
    assert sample.next_poll_at == MAX_SAMPLE_POLLS_IN_FLIGHT


def test_the_sample_gets_what_the_tracked_feeds_leave():
    config = make_config(
        platforms={
            "reddit": {
                "requests_per_minute": 10,
                "max_subreddits_per_feed": 100,
                "sample": {"requests_per_minute": 10, "min_requests_per_minute": 2, "posts": False},
            }
        }
    )
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments, posts, sample = feeds
    quiet = 60 / config.platforms.reddit.max_post_poll_interval

    # before the first answers: comments every 300s, posts every 900s
    assert scheduler.sample_requests_per_minute() == pytest.approx(10 - 60 / 300 - quiet)
    # one comment a second: a poll every 50s
    scheduler.record_success(comments, listing(1000, 100, seconds_apart=1), now=0)
    assert scheduler.sample_requests_per_minute() == pytest.approx(10 - 60 / 50 - quiet)
    # more than the budget: the tracked feeds get all but the sample's minimum
    scheduler.record_success(comments, listing(10_000, 100, seconds_apart=0.02), now=1)
    assert scheduler.sample_requests_per_minute() == 2
    assert scheduler.interval(sample) == 30
    assert 60 / scheduler.interval(comments) + 60 / scheduler.interval(posts) == pytest.approx(8)


def test_r_alls_posts_are_polled_completely_before_the_sample():
    config = make_config(
        platforms={"reddit": {"requests_per_minute": 40, "sample": {"requests_per_minute": 40}}}
    )
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    all_posts = next(feed for feed in feeds if feed.path == "/r/all/new")

    # eight posts a second: a poll every 6.25s sees half a listing of new ones
    scheduler.record_success(all_posts, listing(10_000, 97, seconds_apart=0.125), now=0)
    assert all_posts.interval == pytest.approx(6.25)
    # its 9.6 requests a minute come off the budget before the sample's
    quiet = 60 / 300 + 60 / 900
    assert scheduler.sample_requests_per_minute() == pytest.approx(40 - quiet - 9.6)


def test_the_sample_takes_at_most_its_requests_per_minute():
    config = make_config(platforms={"reddit": {"sample": {"requests_per_minute": 30}}})
    scheduler = FeedScheduler(build_feeds(config), config)
    assert scheduler.sample_requests_per_minute() == 30


def radar_config(**reddit: object):
    return make_config(
        platforms=no_sample(**reddit),
        radar={
            "enabled": True,
            "search_interval_minutes": 15,
            "watchlists": {
                "pkm": {"group": "tech", "products": {"notion": ["Notion AI"], "apple notes": []}}
            },
        },
    )


def test_watched_products_get_search_feeds():
    feeds = build_feeds(radar_config())
    searches = [feed for feed in feeds if feed.search]
    assert [feed.name for feed in searches] == ["search-notion", "search-apple-notes"]
    assert searches[0].path == "/search"
    assert searches[0].params == {"q": '"notion" OR "notion ai"', "sort": "new", "type": "link"}
    assert not searches[0].complete
    assert feeds[0].params == {}


def test_searches_poll_at_a_fixed_interval_and_take_their_share_of_the_budget():
    config = radar_config(requests_per_minute=10, max_subreddits_per_feed=1)
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    search = next(feed for feed in feeds if feed.search)

    outcome = scheduler.record_success(search, listing(1000, 100, seconds_apart=1), now=0)
    assert not outcome.gap
    assert search.interval == 15 * 60
    # two searches every 15 minutes leave 10 - 8/60 requests a minute for the tracked feeds
    assert scheduler._tracked_budget == pytest.approx(10 - 2 * 4 / 60)
