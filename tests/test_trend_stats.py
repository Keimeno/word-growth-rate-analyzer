import math

import numpy as np
import pytest
from scipy import stats

from wgra.config import LongTermConfig
from wgra.detect.trend_stats import (
    EMERGING,
    FADING,
    FLAT,
    MAINSTREAMING,
    ONE_OFF,
    benjamini_hochberg,
    classify,
    half_change,
    half_growth,
    mann_kendall,
    peak_ratio,
    per_month,
    spike_share,
    theil_sen,
)

nan = math.nan


def test_growth_per_month():
    assert per_month(0) == 1
    # 4.35 weeks a month
    assert per_month(math.log(1.1) / 4.35) == pytest.approx(1.1)


def test_theil_sen_ignores_an_outlier():
    # pairwise slopes: six times 1, then 33.3, 49.5, 98 and −96: the median is 1
    assert theil_sen([0, 1, 2, 100, 4]) == pytest.approx((1.0, 0.0))
    # least squares is pulled up to 10.7 per week
    assert np.polyfit(range(5), [0, 1, 2, 100, 4], 1)[0] == pytest.approx(10.7)


def test_theil_sen_leaves_out_weeks_without_data():
    # weeks 0, 2 and 3
    assert theil_sen([1, nan, 5, 7]) == pytest.approx((2.0, 1.0))
    assert math.isnan(theil_sen([1, nan])[0])


def test_theil_sen_matches_scipy():
    rng = np.random.default_rng(1)
    for _ in range(20):
        y = rng.normal(size=26).cumsum()
        expected = stats.theilslopes(y, np.arange(26), method="separate")
        assert theil_sen(y) == pytest.approx((expected.slope, expected.intercept))


def test_mann_kendall_reference_values():
    # by hand: all 10 pairs go up. Var(S) = 5·4·15/18, Z = (10 − 1)/√Var(S)
    up = mann_kendall([1, 2, 3, 4, 5])
    assert up.s == 10
    assert up.variance == pytest.approx(16.6667, abs=1e-4)
    assert up.z == pytest.approx(2.2045, abs=1e-4)
    assert up.p == pytest.approx(0.0275, abs=1e-4)

    down = mann_kendall([5, 4, 3, 2, 1])
    assert (down.s, down.z, down.p) == (-10, -up.z, up.p)

    # one tie: 5 pairs up, one even. Var(S) = (4·3·13 − 2·1·9)/18 = 7.667, Z = 4/√7.667
    tied = mann_kendall([1, 1, 2, 3])
    assert tied.s == 5
    assert tied.variance == pytest.approx(138 / 18)
    assert tied.z == pytest.approx(1.4446, abs=1e-4)
    assert tied.p == pytest.approx(0.1486, abs=1e-4)


def test_mann_kendall_without_a_trend():
    flat = mann_kendall([3, 1, 3, 1, 3, 1])
    assert flat.z == pytest.approx(0, abs=0.5)
    assert flat.p > 0.5
    constant = mann_kendall([2, 2, 2, 2])
    assert (constant.s, constant.p) == (0, 1.0)
    assert mann_kendall([1, nan, 2, nan, 3]).s == 3


def test_mann_kendall_matches_kendalls_tau():
    """S and its tie-corrected variance against scipy's Kendall tau test, which is the
    same test without the continuity correction."""
    rng = np.random.default_rng(2)
    for _ in range(20):
        # small integers: plenty of ties
        y = rng.integers(0, 6, size=26).astype(float) + np.arange(26) * rng.uniform(0, 0.3)
        result = mann_kendall(y)
        tau = stats.kendalltau(np.arange(26), y, method="asymptotic")
        expected_z = math.copysign(stats.norm.isf(tau.pvalue / 2), tau.statistic)
        assert result.s / math.sqrt(result.variance) == pytest.approx(expected_z)


def test_benjamini_hochberg():
    # sorted: 0.005, 0.01, 0.03, 0.04 → × 4/rank: 0.02, 0.02, 0.04, 0.04
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    assert q == pytest.approx([0.02, 0.04, 0.04, 0.02])
    # never above 1, and keeps the order of p
    assert benjamini_hochberg([0.9, 0.8]) == pytest.approx([0.9, 0.9])
    assert len(benjamini_hochberg([])) == 0

    p = np.random.default_rng(3).uniform(size=500) ** 3
    assert benjamini_hochberg(p) == pytest.approx(stats.false_discovery_control(p, method="bh"))


def test_benjamini_hochberg_counts_untested_terms_as_p_1():
    p = np.array([0.001, 0.01, 0.02])
    padded = np.r_[p, np.ones(97)]
    expected = stats.false_discovery_control(padded, method="bh")[:3]
    assert benjamini_hochberg(p, tests=100) == pytest.approx(expected)
    # 0.001 × 100 / 1
    assert benjamini_hochberg(p, tests=100)[0] == pytest.approx(0.1)
    with pytest.raises(ValueError, match="tests"):
        benjamini_hochberg(p, tests=2)


def test_half_change_leaves_out_the_middle_week():
    # 13 weeks: the first 6 against the last 6
    y = np.arange(13, dtype=float)
    assert half_change(y) == 7.0
    assert half_change([1, nan, nan, 4]) == 3.0
    assert math.isnan(half_change([nan, 1]))


def test_spike_share_is_low_for_steady_trends():
    # the last two weeks are the highest, removing them leaves 6/7 of the change
    rising = 0.05 * np.arange(13)
    assert spike_share(rising) == pytest.approx(1 / 7)
    assert spike_share(-rising) == pytest.approx(1 / 7)
    assert spike_share(0.05 * np.arange(52)) == pytest.approx(1 / 26)
    # a level that steps up and stays: 3 quarters of the change are left
    step = np.r_[np.zeros(9), np.ones(4)]
    assert spike_share(step) == pytest.approx(0.25)


def test_spike_share_is_high_for_one_off_events():
    spike = np.zeros(13)
    spike[11] = 3.0
    assert spike_share(spike) == 1.0
    # a burst that fades again
    burst = np.r_[np.zeros(9), [2.3, 1.4, 0.7, 0.4]]
    assert spike_share(burst) == pytest.approx(1 - (1.1 / 4) / (4.8 / 6))
    assert spike_share(burst, top=1) < spike_share(burst)
    # a spike in the first week makes a decline
    start = np.r_[[3.0], np.zeros(12)]
    assert half_change(start) < 0
    assert spike_share(start) == 1.0


def test_spike_share_without_change():
    assert spike_share(np.ones(13)) == 0.0
    # a spike against the direction of the change doesn't explain it
    rising_after_a_spike = np.r_[[2.0], 0.1 * np.arange(1, 13)]
    assert half_change(rising_after_a_spike) > 0
    assert spike_share(rising_after_a_spike) == 0.0
    # unless it's big enough to turn the change around: then it's all the spike
    assert half_change(np.r_[[5.0], 0.1 * np.arange(1, 13)]) < 0
    assert spike_share(np.r_[[5.0], 0.1 * np.arange(1, 13)]) == 1.0


def test_peak_ratio():
    assert peak_ratio([1, 1, 2, 1, 6]) == 6.0
    assert peak_ratio([0, 0, 0, 1, 0]) == math.inf
    assert peak_ratio([0, 0]) == 1.0
    assert peak_ratio([2, nan, 1, 1]) == 2.0


def test_half_growth_is_per_month():
    # 0.05 per week: the halves of 13 weeks are 7 weeks apart
    assert half_growth(0.05 * np.arange(13)) == pytest.approx(per_month(0.05))


SETTINGS = LongTermConfig(
    max_q=0.05, min_growth=1.05, max_spike_share=0.5, min_peak_ratio=3, emerging_max_base=1
)


@pytest.mark.parametrize(
    ("growth", "q", "spike", "change", "peak", "start", "expected"),
    [
        # significant growth from a low base, spread over many weeks
        (1.2, 0.001, 0.1, 1.2, 2.0, 0.5, EMERGING),
        # the same from 5 per 1,000
        (1.2, 0.001, 0.1, 1.2, 2.0, 5.0, MAINSTREAMING),
        (0.8, 0.001, 0.1, 0.8, 2.0, 5.0, FADING),
        # most of the change is one or two weeks far above the rest
        (1.2, 0.001, 0.7, 1.2, 4.0, 0.5, ONE_OFF),
        (1.0, 0.6, 0.9, 1.5, 20.0, 0.5, ONE_OFF),
        (1.0, 0.6, 0.9, 0.6, 20.0, 0.5, ONE_OFF),
        # spiky, but no change to speak of
        (1.0, 0.6, 0.9, 1.01, 20.0, 0.5, FLAT),
        # the highest weeks aren't far above the rest: noise
        (1.0, 0.6, 0.9, 1.5, 1.5, 0.5, FLAT),
        (1.2, 0.001, 0.7, 1.2, 1.5, 0.5, EMERGING),
        # not significant after the correction for testing many terms
        (1.2, 0.2, 0.1, 1.2, 2.0, 0.5, FLAT),
        # significant, but too slow to matter
        (1.02, 0.001, 0.1, 1.02, 2.0, 0.5, FLAT),
    ],
)
def test_classify(growth, q, spike, change, peak, start, expected):
    assert classify(growth, q, spike, change, peak, start, SETTINGS) == expected
