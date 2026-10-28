"""Pure-Python attendance risk service.

No Django imports. Uses math.comb for the exact binomial tail and
numpy for the Monte Carlo simulation (5000 runs, fixed seed=42).
"""

import math

import numpy as np

_MC_RUNS = 5_000
_MC_SEED = 42


# ---------------------------------------------------------------------------
# Laplace-smoothed habit rate
# ---------------------------------------------------------------------------

def habit_rate(attended: int, held: int) -> float:
    """Return the Laplace-smoothed attendance rate: (A+1)/(H+2).

    Avoids 0 or 1 extremes when H is very small.
    """
    return (attended + 1) / (held + 2)


# ---------------------------------------------------------------------------
# Exact binomial tail
# ---------------------------------------------------------------------------

def _binomial_pmf(n: int, k: int, p: float) -> float:
    """P(X = k) for X ~ Binomial(n, p)."""
    return math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k))


def probability_finish_safe(r: int, must: int, p: float) -> float:
    """Return P(X >= must) where X ~ Binomial(R, p). Exact computation.

    Special cases:
      must <= 0  -> 1.0   (already safe)
      must > R   -> 0.0   (mathematically impossible)
    """
    if must <= 0:
        return 1.0
    if must > r:
        return 0.0
    # P(X >= must) = 1 - P(X < must) = 1 - sum_{k=0}^{must-1} P(X=k)
    tail_below = sum(_binomial_pmf(r, k, p) for k in range(must))
    return max(0.0, min(1.0, 1.0 - tail_below))


def risk_label(probability: float) -> str:
    """Classify probability into Low / Medium / High risk.

    >= 0.80 -> Low
    >= 0.50 -> Medium
     < 0.50 -> High
    """
    if probability >= 0.80:
        return "Low"
    if probability >= 0.50:
        return "Medium"
    return "High"


# ---------------------------------------------------------------------------
# Monte Carlo simulation
# ---------------------------------------------------------------------------

def monte_carlo_distribution(
    held: int,
    attended: int,
    total_planned: int,
    runs: int = _MC_RUNS,
    seed: int = _MC_SEED,
) -> dict:
    """Run a Monte Carlo simulation of final attendance percentages.

    Each run draws R samples from Bernoulli(p) for the remaining classes and
    computes the final percentage: (A + sum) / T * 100.

    Args:
        held:          H -- classes held so far.
        attended:      A -- classes attended so far.
        total_planned: T -- total planned.
        runs:          Number of Monte Carlo runs (default 5000).
        seed:          Fixed RNG seed for reproducibility (default 42).

    Returns:
        dict with mc_histogram (list[int]) and mc_bins (list[float]).
    """
    r = total_planned - held
    p = habit_rate(attended, held)

    rng = np.random.default_rng(seed)

    if r > 0:
        samples = rng.binomial(n=1, p=p, size=(runs, r))
        extra_attended = samples.sum(axis=1)
    else:
        extra_attended = np.zeros(runs, dtype=int)

    final_attended = attended + extra_attended
    final_pct = (final_attended / total_planned * 100) if total_planned > 0 else np.zeros(runs)

    counts, edges = np.histogram(final_pct, bins=20, range=(0, 100))
    return {
        "mc_histogram": counts.tolist(),
        "mc_bins": edges.tolist(),
    }


def compute_risk(
    held: int,
    attended: int,
    total_planned: int,
    threshold: int,
) -> dict:
    """Compute the full risk result for display.

    Returns a dict with:
      probability  -- exact binomial P(finish >= threshold)
      label        -- "Low" | "Medium" | "High"
      mc_histogram -- list[int] of 20 bin counts
      mc_bins      -- list[float] of 21 bin edges
    """
    r = total_planned - held
    req = -(-threshold * total_planned // 100)
    must = max(0, req - attended)
    p = habit_rate(attended, held)

    prob = probability_finish_safe(r, must, p)
    label = risk_label(prob)
    mc = monte_carlo_distribution(held, attended, total_planned)

    return {
        "probability": prob,
        "label": label,
        "mc_histogram": mc["mc_histogram"],
        "mc_bins": mc["mc_bins"],
    }
