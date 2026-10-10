import math

import pytest

from wgra.config import Thresholds
from wgra.detect.scoring import (
    Candidate,
    Counts,
    Prior,
    breadth,
    contains_phrase,
    log_odds,
    passes,
    subsumed_by,
)

# no prior beyond the floor: scores depend on the counts alone
FLAT = Prior(total=0, weight=0.0, floor=1.0)
GATES = Thresholds(min_mentions=10, min_authors=5, min_ratio=2.0, min_z=3.0)


def test_log_odds_is_the_monroe_formula():
    # with the same prior on both sides and α0 = α + β, the denominators are
    # n + α0 − y − α, as in the paper
    alpha, beta = 2.0, 98.0
    score = log_odds(30, 1000, 60, 28_000, (alpha, beta), (alpha, beta))
    alpha0 = alpha + beta
    delta = math.log((30 + alpha) / (1000 + alpha0 - 30 - alpha)) - math.log(
        (60 + alpha) / (28_000 + alpha0 - 60 - alpha)
    )
    sigma = math.sqrt(1 / (30 + alpha) + 1 / (60 + alpha))
    assert score.log_odds == pytest.approx(delta)
    assert score.sigma == pytest.approx(sigma)
    assert score.z == pytest.approx(delta / sigma)
    assert score.ratio == pytest.approx(math.exp(delta))


def test_a_stable_term_scores_about_zero():
    # the same share of comments in the window and the 28 days before
    score = Counts(100, 10_000, 2800, 280_000).score(FLAT)
    assert score.ratio == pytest.approx(1, abs=0.02)
    assert abs(score.z) < 0.2


def test_a_burst_scores_its_ratio():
    score = Counts(300, 10_000, 2800, 280_000).score(FLAT)
    # an odds ratio, for small shares about the ratio of the shares: 3% vs 1%
    assert score.ratio == pytest.approx((0.03 / 0.97) / (0.01 / 0.99), rel=0.01)
    assert score.z > 10


def test_the_score_grows_with_mentions_and_evidence():
    scores = [Counts(y, 10_000, 280, 280_000).score(FLAT).z for y in (10, 20, 40, 80)]
    assert scores == sorted(scores)
    # the same ratio on ten times the data is much stronger evidence
    small = Counts(20, 1_000, 280, 280_000).score(FLAT)
    large = Counts(200, 10_000, 2800, 2_800_000).score(FLAT)
    assert small.ratio == pytest.approx(large.ratio, rel=0.05)
    assert large.z > 2 * small.z


def test_a_brand_new_term_gets_a_finite_score():
    score = Counts(20, 10_000, 0, 280_000).score(FLAT)
    assert math.isfinite(score.z)
    assert score.ratio > 100
    assert score.z > 3


def test_new_terms_need_a_floor():
    with pytest.raises(ValueError, match="floor"):
        Counts(20, 10_000, 0, 280_000).score(Prior(total=0, weight=0.0, floor=0.0))


def test_prior_comes_from_the_sample_share():
    prior = Prior(total=1_000_000, weight=0.1, floor=1.0)
    # 1,000 pseudo-documents, the term is in 1% of the sample
    alpha, beta = prior.pseudo_counts(sample_mentions=10_000, documents=1000)
    assert alpha == pytest.approx(1000 * 0.01 + 1)
    assert beta == pytest.approx(1000 * 0.99 + 1)
    # without a sample only the floor is left
    assert Prior(total=0, weight=0.1, floor=1.0).pseudo_counts(0, 1000) == (1.0, 1001.0)
    # counts that don't add up can't make the prior negative
    assert Prior(total=100, weight=0.1, floor=1.0).pseudo_counts(150, 1000) == (1001.0, 1.0)


@pytest.mark.parametrize("weight", [0.0, 0.05, 0.5])
def test_the_prior_does_not_move_stable_terms(weight):
    # common on reddit (5% of the sample) but rare in the scope (0.1%), and stable: with
    # the same pseudo-counts on both sides, the small window would be pulled up
    counts = Counts(10, 10_000, 280, 280_000, sample_mentions=50_000)
    score = counts.score(Prior(total=1_000_000, weight=weight, floor=1.0))
    assert score.ratio == pytest.approx(1, abs=0.1)


def test_the_prior_damps_bursts_of_terms_common_elsewhere():
    # a term that's everywhere on reddit gets a bit more mentions in a scope where it's
    # rare: likely spill-over, not the scope's own trend
    counts = Counts(30, 10_000, 280, 280_000, sample_mentions=50_000)
    flat = counts.score(Prior(total=1_000_000, weight=0.0, floor=1.0))
    informed = counts.score(Prior(total=1_000_000, weight=0.05, floor=1.0))
    assert flat.ratio == pytest.approx(3, rel=0.05)
    assert informed.ratio < 0.8 * flat.ratio
    # the scope's own vocabulary, rarer on reddit than here, is barely touched
    topical = Counts(300, 10_000, 2800, 280_000, sample_mentions=100)
    assert topical.score(Prior(total=1_000_000, weight=0.05, floor=1.0)).ratio == pytest.approx(
        topical.score(FLAT).ratio, rel=0.01
    )


def test_without_history_the_window_is_compared_with_the_sample():
    # the first day: no reference period yet. 5% of the window's documents mention the
    # term, 1% of the sample's
    prior = Prior(total=1_000_000, weight=0.05, floor=1.0)
    first_day = Counts(500, 10_000, 0, 0, sample_mentions=10_000).score(prior)
    assert first_day.ratio == pytest.approx(5, rel=0.03)
    # a few hours of history: half real, half the sample's share
    some_history = Counts(500, 10_000, 250, 5_000, sample_mentions=10_000).score(prior)
    assert 1 < some_history.ratio < first_day.ratio
    # with history, the sample no longer stands in for it
    stable = Counts(500, 10_000, 14_000, 280_000, sample_mentions=10_000).score(prior)
    assert stable.ratio == pytest.approx(1, abs=0.05)


def test_gates():
    burst = Counts(300, 10_000, 2800, 280_000).score(FLAT)
    assert passes(burst, 300, 50, GATES)
    assert not passes(burst, 9, 50, GATES)
    assert not passes(burst, 300, 4, GATES)
    assert passes(burst, 300, None, GATES)
    mild = Counts(150, 10_000, 2800, 280_000).score(FLAT)
    assert not passes(mild, 150, 50, GATES)  # 1.5x, below min_ratio
    weak = Counts(12, 10_000, 2, 28_000).score(FLAT)
    assert weak.ratio > 2
    assert not passes(weak, 12, 50, Thresholds(min_z=20))


def test_contains_phrase():
    assert contains_phrase("vision pro", "pro")
    assert contains_phrase("apple vision pro", "vision pro")
    assert not contains_phrase("vision pro", "vision pro")
    assert not contains_phrase("improve", "pro")
    assert not contains_phrase("pro max", "max pro")


def candidate(term: str, mentions: int, reference_mentions: int, kind: str = "word") -> Candidate:
    return Candidate(kind, term, Counts(mentions, 10_000, reference_mentions, 280_000), 50)


def test_a_word_explained_by_a_trending_phrase_is_subsumed():
    phrase = candidate("vision pro", 300, 0, "phrase")
    # "pro" has its usual 2800 mentions plus the 300 of "vision pro"
    pro = candidate("pro", 400, 2800)
    assert subsumed_by(pro, [phrase, pro], FLAT, GATES) == "vision pro"


def test_a_word_with_its_own_burst_is_kept():
    phrase = candidate("vision pro", 300, 0, "phrase")
    # "pro" triples even without "vision pro"
    pro = candidate("pro", 300 + 300, 1000)
    assert subsumed_by(pro, [phrase, pro], FLAT, GATES) is None


def test_nested_phrases_count_once():
    # every comment with "apple vision pro" also has "vision pro", subtracting both
    # would subtract those comments twice
    short = candidate("vision pro", 300, 0, "phrase")
    long = candidate("apple vision pro", 250, 0, "phrase")
    pro = candidate("pro", 300 + 280, 1000)
    assert subsumed_by(pro, [short, long, pro], FLAT, GATES) is None
    assert subsumed_by(short, [short, long, pro], FLAT, GATES) is None


def test_only_words_and_phrases_are_subsumed():
    phrase = candidate("github com", 300, 0, "phrase")
    domain = candidate("github.com", 300, 0, "domain")
    assert subsumed_by(domain, [phrase, domain], FLAT, GATES) is None


def test_breadth_counts_member_subreddits_where_the_term_bursts():
    members = [
        Counts(20, 1_000, 0, 28_000),  # bursting
        Counts(15, 2_000, 5, 56_000),  # bursting
        Counts(10, 1_000, 280, 28_000),  # mentioned as usual
        Counts(2, 1_000, 0, 28_000),  # too few mentions to tell
        Counts(0, 1_000, 0, 28_000),  # not mentioned
    ]
    assert breadth(members, FLAT, min_z=3.0, min_mentions=3) == (2, 4)
