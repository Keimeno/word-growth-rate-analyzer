"""The lead–lag statistics against scipy (a dev dependency only) and by hand."""

import math

import numpy as np
import pytest
from scipy import special, stats

from wgra.leadlag.stats import (
    beta_cdf,
    beta_quantile,
    binomial_tail,
    given_nothing_yet,
    posterior,
    remaining_lag,
    still_to_come,
)


@pytest.mark.parametrize(
    ("x", "a", "b"),
    [(0.3, 2.0, 5.0), (0.9, 0.5, 0.5), (0.01, 30.0, 2.0), (0.5, 200.0, 180.0), (0.999, 1.0, 1.0)],
)
def test_beta_cdf_matches_scipy(x, a, b):
    assert beta_cdf(x, a, b) == pytest.approx(special.betainc(a, b, x), abs=1e-12)


def test_beta_cdf_edges():
    assert beta_cdf(0, 2, 3) == 0
    assert beta_cdf(1, 2, 3) == 1
    with pytest.raises(ValueError):
        beta_cdf(0.5, 0, 1)


@pytest.mark.parametrize("q", [0.1, 0.5, 0.9])
@pytest.mark.parametrize(("a", "b"), [(18.4, 1.6), (0.72, 3.28), (3.0, 40.0)])
def test_beta_quantile_matches_scipy(q, a, b):
    assert beta_quantile(q, a, b) == pytest.approx(stats.beta.ppf(q, a, b), abs=1e-9)


@pytest.mark.parametrize(
    ("hits", "trials", "rate"), [(18, 18, 0.45), (9, 18, 0.18), (2, 11, 0.45), (0, 5, 0.3)]
)
def test_binomial_tail_is_the_one_sided_p_value(hits, trials, rate):
    assert binomial_tail(hits, trials, rate) == pytest.approx(
        stats.binom.sf(hits - 1, trials, rate), rel=1e-9, abs=1e-15
    )


def test_binomial_tail_edges():
    assert binomial_tail(6, 5, 0.5) == 0
    assert binomial_tail(3, 5, 0.0) == 0
    assert binomial_tail(3, 5, 1.0) == 1


def test_posterior_shrinks_to_the_base_rate():
    # no events: the base rate, with a wide interval
    mean, low, high = posterior(0, 0, 0.2, prior_events=4, interval=0.8)
    assert mean == pytest.approx(0.2)
    assert low < 0.05 and high > 0.4
    # 3 of 3 is far from a certainty
    mean, low, high = posterior(3, 0, 0.2, prior_events=4, interval=0.8)
    assert mean == pytest.approx((3 + 0.8) / 7)
    assert low < mean < high < 0.9
    # with hundreds of events the hit rate wins
    mean, low, high = posterior(270, 30, 0.2, prior_events=4, interval=0.8)
    assert mean == pytest.approx(0.9, abs=0.01)
    assert high - low < 0.05
    assert (low, high) == pytest.approx(
        tuple(stats.beta.ppf([0.1, 0.9], 270 + 0.8, 30 + 3.2)), abs=1e-9
    )


def test_time_without_the_follower_lowers_the_chance():
    lags = [24.0, 48.0, 72.0]
    assert still_to_come(lags, 0, 168) == 1
    assert still_to_come(lags, 10, 168) == pytest.approx(3.5 / 4)
    assert still_to_come(lags, 50, 168) == pytest.approx(1.5 / 4)
    # the follow window is over
    assert still_to_come(lags, 168, 168) == 0
    # P(hit | nothing yet) = p·S / (1 − p + p·S)
    assert given_nothing_yet(0.8, 1.0) == pytest.approx(0.8)
    assert given_nothing_yet(0.8, 0.375) == pytest.approx(0.3 / 0.5)
    assert given_nothing_yet(0.8, 0.0) == 0
    # the lag still expected: the median of the longer ones
    assert remaining_lag(lags, 10) == 48
    assert remaining_lag(lags, 30) == 60
    assert remaining_lag(lags, 80) == 80


def test_quantile_is_monotonic():
    values = [beta_quantile(q, 2.5, 7.5) for q in np.linspace(0.01, 0.99, 25)]
    assert values == sorted(values)
    assert not any(math.isnan(v) for v in values)
