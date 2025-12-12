import pytest
from helpers import make_config, make_item

from wgra.ingest.feeds import FeedScheduler, build_feeds, observed_rate


def listing(newest_id: int, count: int, seconds_apart: float, newest_time: int = 1_700_000_000):
    """A listing like reddit returns it: newest first, ids and timestamps descending."""
    return [
        make_item(newest_id - index, int(newest_time - index * seconds_apart))
        for index in range(count)
    ]


def test_subreddits_are_packed_into_comment_and_post_feeds():
    config = make_config(ingest={"max_subreddits_per_feed": 2})
    feeds = build_feeds(config)
    assert [(feed.name, feed.subreddits) for feed in feeds] == [
        ("comments-1", ("de", "programming")),
        ("posts-1", ("de", "programming")),
        ("comments-2", ("technology",)),
        ("posts-2", ("technology",)),
        ("background-all", ("all",)),
    ]
    assert feeds[0].path == "/r/de+programming/comments"
    assert feeds[1].path == "/r/de+programming/new"
    assert feeds[-1].background


def test_background_feed_can_be_disabled():
    feeds = build_feeds(make_config(background={"requests_per_minute": 0}))
    assert not any(feed.background for feed in feeds)


def test_observed_rate_uses_the_listing_time_span():
    assert observed_rate(listing(1000, 101, seconds_apart=2)) == pytest.approx(0.5)
    assert observed_rate(listing(1000, 1, seconds_apart=2)) is None
    # many items within the same second
    assert observed_rate(listing(1000, 50, seconds_apart=0)) == 49


def test_busy_feeds_are_polled_often_enough_to_see_half_a_listing_per_poll():
    config = make_config(background={"requests_per_minute": 0})
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments = feeds[0]

    # one new comment per second
    scheduler.record_success(comments, listing(1000, 100, seconds_apart=1), now=0)
    assert comments.interval == pytest.approx(50 / (99 / 99))
    assert comments.next_poll_at == pytest.approx(comments.interval)


def test_quiet_feeds_are_polled_at_the_maximum_interval():
    config = make_config(background={"requests_per_minute": 0})
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    posts = feeds[1]

    # one post per hour
    scheduler.record_success(posts, listing(1000, 100, seconds_apart=3600), now=0)
    assert posts.interval == config.ingest.max_post_poll_interval


def test_intervals_stretch_when_the_budget_is_exceeded():
    config = make_config(
        background={"requests_per_minute": 0},
        ingest={"requests_per_minute": 10, "max_subreddits_per_feed": 100},
    )
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    comments, posts = feeds

    # 50 comments per second would need a poll every second = 60 requests per minute
    scheduler.record_success(comments, listing(10_000, 100, seconds_apart=0.02), now=0)
    scheduler.record_success(posts, listing(1000, 100, seconds_apart=3600), now=0)

    demand = 60 / config.ingest.min_poll_interval + 60 / config.ingest.max_post_poll_interval
    scale = demand / 10
    assert comments.interval == pytest.approx(config.ingest.min_poll_interval * scale)
    total = sum(60 / feed.interval for feed in feeds)
    assert total == pytest.approx(10)


def test_a_full_listing_of_unseen_items_is_a_gap_and_speeds_up_polling():
    config = make_config(background={"requests_per_minute": 0})
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


def test_background_feed_reports_how_far_reddit_ids_advanced():
    config = make_config(background={"requests_per_minute": 20})
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    background = feeds[-1]

    scheduler.record_success(background, listing(1000, 20, seconds_apart=0), now=0)
    outcome = scheduler.record_success(background, listing(1300, 20, seconds_apart=0), now=3)
    assert outcome.id_span == 300
    assert not outcome.gap
    assert background.interval == pytest.approx(3.0)


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


def test_next_feed_is_the_one_due_first():
    config = make_config()
    feeds = build_feeds(config)
    scheduler = FeedScheduler(feeds, config)
    for index, feed in enumerate(feeds):
        feed.next_poll_at = 10 - index
    assert scheduler.next_feed() is feeds[-1]
