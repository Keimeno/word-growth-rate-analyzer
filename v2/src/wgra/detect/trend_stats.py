"""Robust statistics on weekly series: is a term's share growing or fading steadily, or
did one event cause the change? See docs/ARCHITECTURE-V2.md §4.3.

Every function takes one series, oldest week first. Weeks without data (no comments at
all in the scope that week) are NaN and left out.

* Theil–Sen slope of the log share: the median of the slopes between all pairs of weeks,
  so one-off spikes barely move it. Growth per month = exp(slope × 4.35).
* Mann–Kendall test: is the series monotonic? S counts the pairs of weeks that go up minus
  those that go down. Rank based, so it doesn't matter whether it runs on shares or log
  shares. Two-sided p-value from the normal approximation with the usual continuity and
  tie corrections (Kendall 1975, Gilbert 1987).
* Benjamini–Hochberg: controls the share of false discoveries when thousands of terms
  are tested at once.
* Spike share: the share of the change between the first and the second half of the
  window that disappears without its highest one or two weeks.
* Peak: the highest week against the median week, a spike is a week far above the rest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from wgra.config import LongTermConfig

WEEKS_PER_MONTH = 4.35

EMERGING = "emerging"
MAINSTREAMING = "mainstreaming"
FADING = "fading"
ONE_OFF = "one-off"
FLAT = "flat"
CATEGORIES = (EMERGING, MAINSTREAMING, FADING, ONE_OFF)


def _series(values: ArrayLike) -> NDArray[np.float64]:
    return np.asarray(values, dtype=np.float64)


def per_month(slope_per_week: float) -> float:
    """A weekly slope of the log share as a growth factor per month: 1.1 is +10%."""
    return math.exp(slope_per_week * WEEKS_PER_MONTH)


def theil_sen(y: ArrayLike, x: ArrayLike | None = None) -> tuple[float, float]:
    """(slope, intercept): the median of the pairwise slopes, and median(y) − slope · median(x).

    x defaults to the week index 0, 1, 2, … NaN weeks are left out.
    """
    values = _series(y)
    weeks = np.arange(len(values), dtype=np.float64) if x is None else _series(x)
    known = ~np.isnan(values)
    values, weeks = values[known], weeks[known]
    if len(values) < 2:
        return math.nan, math.nan
    first, second = np.triu_indices(len(values), k=1)
    distance = weeks[second] - weeks[first]
    apart = distance != 0
    slope = float(np.median((values[second] - values[first])[apart] / distance[apart]))
    return slope, float(np.median(values) - slope * np.median(weeks))


@dataclass(frozen=True, slots=True)
class MannKendall:
    # pairs of weeks going up minus pairs going down
    s: int
    variance: float
    z: float
    # two-sided: the chance of a trend at least this monotonic, up or down, without one
    p: float


def mann_kendall(y: ArrayLike) -> MannKendall:
    values = _series(y)
    values = values[~np.isnan(values)]
    n = len(values)
    first, second = np.triu_indices(n, k=1)
    s = int(np.sign(values[second] - values[first]).sum())
    # tied values (weeks without a mention) can't go up or down, which narrows S
    _, ties = np.unique(values, return_counts=True)
    variance = (n * (n - 1) * (2 * n + 5) - float(np.sum(ties * (ties - 1) * (2 * ties + 5)))) / 18
    if variance <= 0:
        return MannKendall(s, 0.0, 0.0, 1.0)
    # continuity correction: S only moves in steps of 2
    z = (s - math.copysign(1, s)) / math.sqrt(variance) if s else 0.0
    return MannKendall(s, variance, z, math.erfc(abs(z) / math.sqrt(2)))


def benjamini_hochberg(p_values: ArrayLike, tests: int | None = None) -> NDArray[np.float64]:
    """Adjusted p-values (q): a term is a discovery at a false discovery rate α if q ≤ α.

    `tests` is the number of hypotheses tested, when only some of their p-values are
    known: the others count as p = 1. Picking the most extreme of many terms and testing
    only those would otherwise find trends in noise.
    """
    p = _series(p_values)
    count = len(p)
    if not count:
        return p
    tests = count if tests is None else tests
    if tests < count:
        raise ValueError(f"{count} p-values, but only {tests} tests")
    order = np.argsort(p, kind="stable")
    scaled = p[order] * tests / np.arange(1, count + 1)
    # the smallest scaled value at or above each rank, so q keeps the order of p
    adjusted = np.minimum.accumulate(scaled[::-1])[::-1]
    q = np.empty(count)
    q[order] = np.minimum(adjusted, 1.0)
    return q


def half_change(y: ArrayLike, keep: NDArray[np.bool_] | None = None) -> float:
    """Mean of the second half of the window minus the mean of the first half.

    With an odd number of weeks the middle week is in neither half. `keep` leaves weeks
    out, NaN weeks are always left out. NaN when a half has no week left.
    """
    values = _series(y)
    keep = ~np.isnan(values) if keep is None else keep & ~np.isnan(values)
    half = len(values) // 2
    first = values[:half][keep[:half]]
    second = values[len(values) - half :][keep[len(values) - half :]]
    if not len(first) or not len(second):
        return math.nan
    return float(second.mean() - first.mean())


def spike_share(y: ArrayLike, top: int = 2) -> float:
    """How much of the change between the two halves of the window comes from the `top`
    highest weeks: 0 when the change is the same without them, 1 when none is left.

    Run on log shares, a steady trend scores low (1/7 for 13 weeks of steady growth, 1/26
    for 52: its last two weeks are the highest, but the other weeks of the second half are
    above the first half too). A burst that fades again scores high. For a decline, a
    spike at the start of the window is what would make it look like one.
    """
    values = _series(y)
    known = ~np.isnan(values)
    change = half_change(values)
    if math.isnan(change) or change == 0:
        return 0.0
    highest = np.argsort(np.where(known, values, -np.inf), kind="stable")[::-1][:top]
    keep = known.copy()
    keep[highest] = False
    rest = half_change(values, keep)
    if math.isnan(rest):
        return 1.0
    return float(np.clip(1 - rest / change, 0.0, 1.0))


def half_growth(y: ArrayLike) -> float:
    """The change between the halves of a log-share series, per month like growth.

    Unlike the Theil–Sen slope it moves with spikes: a one-off has a big change here and
    a high spike share."""
    values = _series(y)
    change = half_change(values)
    # the centers of the two halves are this many weeks apart
    distance = len(values) - len(values) // 2
    return math.nan if math.isnan(change) or not distance else per_month(change / distance)


def peak_ratio(shares: ArrayLike) -> float:
    """The highest week's share, times the median week's."""
    values = _series(shares)
    values = values[~np.isnan(values)]
    if not len(values):
        return math.nan
    median = float(np.median(values))
    highest = float(values.max())
    if median > 0:
        return highest / median
    return math.inf if highest > 0 else 1.0


def material(growth: float, minimum: float) -> bool:
    """Whether a growth factor is at least `minimum` per month, up or down."""
    return not math.isnan(growth) and abs(math.log(growth)) >= math.log(minimum)


def classify(
    growth: float,
    q: float,
    spike: float,
    change: float,
    peak: float,
    start_share: float,
    settings: LongTermConfig,
) -> str:
    """emerging, mainstreaming, fading, one-off or flat.

    growth: Theil–Sen per month; q: Benjamini–Hochberg adjusted Mann–Kendall p-value;
    spike: spike share; change: half_growth; peak: peak_ratio; start_share: the trend line
    at the start of the window, per 1,000 comments and posts.
    """
    trending = q <= settings.max_q and material(growth, settings.min_growth)
    # the change is mostly one or two weeks far above the rest: an event, not a trend.
    # Without the peak, the noise of rare terms would make one-offs.
    if (
        spike >= settings.max_spike_share
        and peak >= settings.min_peak_ratio
        and (trending or material(change, settings.min_growth))
    ):
        return ONE_OFF
    if not trending:
        return FLAT
    if growth < 1:
        return FADING
    # still rare at the start of the window, or already a common topic that keeps growing
    return EMERGING if start_share <= settings.emerging_max_base else MAINSTREAMING
