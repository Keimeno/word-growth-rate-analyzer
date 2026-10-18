"""Burst scoring: the weighted log odds ratio with an informative Dirichlet prior.

Monroe, Colaresi & Quinn (2008), "Fightin' Words", compare how over-represented a word
is in one corpus against another. Here the two corpora are the window W (the last 24h)
and the reference period B before it (28 days), and the counts are documents: comments
and posts that mention the term (y) out of all comments and posts (n). For a single
term the Dirichlet prior is a Beta(α, β) prior on "a document mentions it", with the
term's share π_w in the r/all sample as its mean:

    α_c = m_c · π_w + floor          m_W = κ · n_W
    β_c = m_c · (1 − π_w) + floor    m_B = κ · n_B + max(n_W − n_B, 0)
    δ_w = log((y_W + α_W) / (n_W − y_W + β_W)) − log((y_B + α_B) / (n_B − y_B + β_B))
    σ²_w ≈ 1 / (y_W + α_W) + 1 / (y_B + α_B)
    z_w = δ_w / σ_w

z is the strength of the evidence and what trends are ranked by. exp(δ) is the "times
its usual share" figure that's shown.

Two changes to the paper's formula, which adds the same α_w = α0 · π_w to both sides:

* The paper compares corpora of similar size. Here B is 28 times W, and the same
  pseudo-counts would pull the small window toward the reddit-wide share far harder than
  the reference: a term that's common on reddit but rare in a subreddit would look like
  it's rising while nothing changes. So each side gets pseudo-counts in proportion to its
  size (m_c = κ · n_c). A term whose share doesn't change scores 0, whatever its reddit-wide
  share. The prior blends both shares with the reddit-wide share by the same amount,
  which damps bursts of terms that are common on reddit but rare in the scope (likely
  spill-over from elsewhere) and leaves the scope's own vocabulary alone.
* The floor gives every term a pseudo-mention, so a term that never appeared in the
  sample or the reference period still gets a finite score: brand-new names are what we
  want to find. Without it, σ would be infinite for them.

While a scope has less history than one window (the first day), the reddit-wide share
stands in for the missing part: max(n_W − n_B, 0) pseudo-documents, as if the scope had
a window's worth of history at the reddit-wide share. On the first day this shows what's
distinctive for a scope, and it fades out as real history comes in. Alerts wait for a
few days of history anyway (DetectConfig.min_reference_days).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from wgra.config import Thresholds

WORD = "word"
PHRASE = "phrase"


@dataclass(frozen=True, slots=True)
class Prior:
    """The background the prior comes from, the r/all sample."""

    # documents in the sample, over the prior period
    total: int
    # κ: how many documents the prior is worth, as a share of a side's documents
    weight: float
    floor: float

    def pseudo_counts(self, sample_mentions: int, documents: float) -> tuple[float, float]:
        """(α, β): pseudo-documents with and without the term, out of `documents`."""
        # the term and scope tables are written separately, never trust them to add up
        share = min(sample_mentions / self.total, 1.0) if self.total else 0.0
        return documents * share + self.floor, documents * (1 - share) + self.floor


@dataclass(frozen=True, slots=True)
class Score:
    # α_W, the pseudo-mentions the window got from the prior
    alpha: float
    log_odds: float
    sigma: float

    @property
    def z(self) -> float:
        return self.log_odds / self.sigma

    @property
    def ratio(self) -> float:
        return math.exp(self.log_odds)


def log_odds(
    mentions: int,
    total: int,
    reference_mentions: int,
    reference_total: int,
    prior: tuple[float, float],
    reference_prior: tuple[float, float],
) -> Score:
    """δ, σ of the window against the reference period, see the module docstring.

    `prior` and `reference_prior` are the (α, β) pseudo-counts of each side.
    """
    (alpha, beta), (reference_alpha, reference_beta) = prior, reference_prior
    if min(alpha, beta, reference_alpha, reference_beta) <= 0:
        raise ValueError("the pseudo-counts must be positive, use a prior floor")
    # a document can't mention a term more than once, guard against inconsistent counts
    # (the term and scope tables are written separately, a crash in between can skew them)
    mentions = min(mentions, total)
    reference_mentions = min(reference_mentions, reference_total)
    window = math.log((mentions + alpha) / (total - mentions + beta))
    reference = math.log(
        (reference_mentions + reference_alpha)
        / (reference_total - reference_mentions + reference_beta)
    )
    sigma = math.sqrt(1 / (mentions + alpha) + 1 / (reference_mentions + reference_alpha))
    return Score(alpha=alpha, log_odds=window - reference, sigma=sigma)


@dataclass(frozen=True, slots=True)
class Counts:
    """A term's counts in one scope, for the window and the reference period."""

    mentions: int
    total: int
    reference_mentions: int
    reference_total: int
    sample_mentions: int = 0

    def score(self, prior: Prior) -> Score:
        # see "the first day" above
        missing_history = max(self.total - self.reference_total, 0)
        return log_odds(
            self.mentions,
            self.total,
            self.reference_mentions,
            self.reference_total,
            prior.pseudo_counts(self.sample_mentions, prior.weight * self.total),
            prior.pseudo_counts(
                self.sample_mentions, prior.weight * self.reference_total + missing_history
            ),
        )


def score_arrays(
    mentions: NDArray[np.float64],
    total: NDArray[np.float64],
    reference_mentions: NDArray[np.float64],
    reference_total: NDArray[np.float64],
    sample_mentions: float,
    prior: Prior,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """(δ, z) of `Counts.score` for many windows at once, for example every hour of a term's
    series (the onsets in leadlag/onsets.py). The same formula, element by element."""
    share = min(sample_mentions / prior.total, 1.0) if prior.total else 0.0
    window_documents = prior.weight * total
    reference_documents = prior.weight * reference_total + np.maximum(total - reference_total, 0)
    alpha = window_documents * share + prior.floor
    beta = window_documents * (1 - share) + prior.floor
    reference_alpha = reference_documents * share + prior.floor
    reference_beta = reference_documents * (1 - share) + prior.floor
    if prior.floor <= 0:
        raise ValueError("the pseudo-counts must be positive, use a prior floor")
    mentions = np.minimum(mentions, total)
    reference_mentions = np.minimum(reference_mentions, reference_total)
    log_odds = np.log((mentions + alpha) / (total - mentions + beta)) - np.log(
        (reference_mentions + reference_alpha)
        / (reference_total - reference_mentions + reference_beta)
    )
    sigma = np.sqrt(1 / (mentions + alpha) + 1 / (reference_mentions + reference_alpha))
    return log_odds, log_odds / sigma


def passes(score: Score, mentions: int, authors: int | None, thresholds: Thresholds) -> bool:
    """The gates. authors=None skips the author gate (when it can't be known)."""
    return (
        mentions >= thresholds.min_mentions
        and (authors is None or authors >= thresholds.min_authors)
        and score.ratio >= thresholds.min_ratio
        and score.z >= thresholds.min_z
    )


def contains_phrase(longer: str, shorter: str) -> bool:
    """Whether the words of `shorter` appear in a row within `longer`."""
    return longer != shorter and f" {shorter} " in f" {longer} "


@dataclass(frozen=True, slots=True)
class Candidate:
    kind: str
    term: str
    counts: Counts
    authors: int


def subsumed_by(
    candidate: Candidate,
    trending: Sequence[Candidate],
    prior: Prior,
    thresholds: Thresholds,
) -> str | None:
    """The phrase that explains this term's burst, if any.

    "vision pro" trending makes "vision" and "pro" trend too. They are suppressed when
    their burst is mostly explained by the phrase: without the comments mentioning the
    phrase, they wouldn't pass the gates any more. Every comment that mentions "vision
    pro" mentions "pro", so the phrase's counts are subtracted from the word's. Of nested
    phrases ("vision pro", "apple vision pro") only the shortest counts, its comments
    include the longer one's.
    """
    if candidate.kind not in (WORD, PHRASE):
        return None
    longer = [
        other
        for other in trending
        if other.kind == PHRASE and contains_phrase(other.term, candidate.term)
    ]
    shortest = [
        phrase
        for phrase in longer
        if not any(contains_phrase(phrase.term, other.term) for other in longer)
    ]
    if not shortest:
        return None

    counts = candidate.counts
    residual = Counts(
        mentions=max(counts.mentions - sum(p.counts.mentions for p in shortest), 0),
        total=counts.total,
        reference_mentions=max(
            counts.reference_mentions - sum(p.counts.reference_mentions for p in shortest), 0
        ),
        reference_total=counts.reference_total,
        sample_mentions=counts.sample_mentions,
    )
    if passes(residual.score(prior), residual.mentions, None, thresholds):
        return None
    return max(shortest, key=lambda phrase: phrase.counts.mentions).term


def breadth(
    member_counts: Iterable[Counts], prior: Prior, min_z: float, min_mentions: int
) -> tuple[int, int]:
    """(subreddits where the term bursts, subreddits mentioning it) within a group."""
    bursting = mentioning = 0
    for counts in member_counts:
        if counts.mentions == 0:
            continue
        mentioning += 1
        if counts.mentions >= min_mentions and counts.score(prior).z > min_z:
            bursting += 1
    return bursting, mentioning
