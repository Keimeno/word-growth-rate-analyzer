"""Reddit's channels: a tracked subreddit is "r/<name>", lowercase like reddit's names.

Besides the tracked subreddits, Reddit has two channels of its own:

* r/all: everything the r/all sample finds in subreddits we don't track is counted here.
  Per subreddit, a sample of a few percent would be far too thin to say anything, and
  thousands of tiny subreddits would mostly add rows that are counted once. It's
  Reddit's platform channel, the prior of every Reddit scope's scores.
* r/_search: posts naming a watched product anywhere on reddit, found by search, and the
  comment trees under some of them (the churn radar, docs/CHURN-RADAR.md §2.2). Search
  isn't a complete stream, so these counts aren't shares of anything: the detectors never
  see it, only the radar counts it. Subreddit names can't start with an underscore, so it
  can't clash with one.
"""

PLATFORM = "reddit"
DOC_TYPES = ("comment", "post")
PREFIX = "r/"
SAMPLE = "r/all"
SEARCH = "r/_search"
# how the sample reads in messages
SAMPLE_LABEL = "reddit-wide (the r/all sample)"


def is_channel(name: str) -> bool:
    """Whether a channel id is Reddit's: "r/" and a name."""
    return name.startswith(PREFIX) and len(name) > len(PREFIX)


def channel_of(subreddit: str) -> str:
    return PREFIX + subreddit.lower()


def subreddit_of(channel: str) -> str:
    return channel.removeprefix(PREFIX)
