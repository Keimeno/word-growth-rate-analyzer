"""The statistics behind edges and forecasts, without scipy (a dev dependency only, the
tests compare against it).

* The probability that a follower follows is a Beta posterior: the hits and misses, plus a
  prior worth `prior_events` events centered on the follower's base rate. With a handful of
  events it stays near the base rate, with hundreds it's the hit rate.
* Whether an edge is real: a one-sided binomial test, could the hits have come from the
  base rate alone, then Benjamini–Hochberg over all pairs tested (trend_stats.py).
* A forecast made some time after the leader's onset accounts for the time that passed
  without the follower following: P(hit | nothing yet) = p·S / (1 − p + p·S), where S is
  the share of the edge's past hits that took longer than that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

_TINY = 1e-300
_EPSILON = 3e-16


def _continued_fraction(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta function (modified Lentz)."""
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > _TINY else _TINY)
    result = d
    for m in range(1, 1000):
        for numerator in (
            m * (b - m) * x / ((a - 1 + 2 * m) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 1 + 2 * m)),
        ):
            d = 1 + numerator * d
            d = 1 / (d if abs(d) > _TINY else _TINY)
            c = 1 + numerator / c
            c = c if abs(c) > _TINY else _TINY
            result *= d * c
        if abs(d * c - 1) < _EPSILON:
            break
    return result


def beta_cdf(x: float, a: float, b: float) -> float:
    """The regularized incomplete beta function I_x(a, b): P(X ≤ x) for X ~ Beta(a, b)."""
    if a <= 0 or b <= 0:
        raise ValueError("Beta parameters must be positive")
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1) / (a + b + 2):
        return front * _continued_fraction(a, b, x) / a
    return 1 - front * _continued_fraction(b, a, 1 - x) / b


def beta_quantile(q: float, a: float, b: float) -> float:
    """x with P(X ≤ x) = q for X ~ Beta(a, b), by bisection."""
    if not 0 <= q <= 1:
        raise ValueError("q is a probability")
    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        if beta_cdf(middle, a, b) < q:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def binomial_tail(hits: int, trials: int, rate: float) -> float:
    """P(X ≥ hits) for X ~ Binomial(trials, rate): the one-sided p-value of `hits`."""
    if hits <= 0:
        return 1.0
    if hits > trials:
        return 0.0
    if rate <= 0:
        return 0.0
    if rate >= 1:
        return 1.0
    return beta_cdf(rate, hits, trials - hits + 1)


def posterior(
    hits: int, misses: int, base_rate: float, prior_events: float, interval: float
) -> tuple[float, float, float]:
    """(mean, low, high) of the probability to follow, shrunk to the base rate."""
    a = hits + prior_events * base_rate
    b = misses + prior_events * (1 - base_rate)
    # a prior of 0 events: Jeffreys' prior keeps the parameters positive
    if prior_events <= 0:
        a, b = hits + 0.5, misses + 0.5
    tail = (1 - interval) / 2
    return a / (a + b), beta_quantile(tail, a, b), beta_quantile(1 - tail, a, b)


def still_to_come(lags: Sequence[float], elapsed: float, max_lag: float) -> float:
    """The share of past hits that took longer than `elapsed` hours (smoothed), 0 once the
    follow window of `max_lag` hours is over."""
    if elapsed >= max_lag:
        return 0.0
    if elapsed <= 0 or not lags:
        return 1.0
    later = sum(lag > elapsed for lag in lags)
    return (later + 0.5) / (len(lags) + 1)


def given_nothing_yet(probability: float, still: float) -> float:
    """P(hit | no follower onset yet), from P(hit) and the share of hits still to come."""
    if probability <= 0 or still <= 0:
        return 0.0
    return probability * still / (1 - probability + probability * still)


def remaining_lag(lags: Sequence[float], elapsed: float) -> float:
    """The median lag of the past hits that took longer than `elapsed`, in hours."""
    later = sorted(lag for lag in lags if lag > elapsed)
    if not later:
        return elapsed
    middle = len(later) // 2
    return later[middle] if len(later) % 2 else (later[middle - 1] + later[middle]) / 2
