"""Matching strategies: the three control-selection algorithms.

- ``basic_strategy`` — Greedy (Nearest Neighbor)
- ``intermediate_strategy`` — Refined Greedy (Hill Climbing)
- ``stochastic_genetic_search`` — Stochastic (Genetic Search), the "Advanced
  (Thorough)" strategy

All are pure functions (no Streamlit) that take a fixed candidate pool and the
vectorised scorer from ``make_fast_metrics_fn`` (falling back to a reference
scorer where noted).  They return index-label lists plus the metric dicts the
live app builds its optimisation table from; ``MatchResult`` is the typed,
serialisable envelope for tests and non-UI callers.
"""

from __future__ import annotations

import numpy as np
from sklearn.neighbors import NearestNeighbors

from .models import MatchResult


def basic_strategy(pool_df, p_scaled, t_cent, n, fast_metrics):
    """Greedy (Nearest Neighbor): take the n nearest pool regions to the test centroid.

    Returns ``(c_idx, metrics)`` — the selected index labels and the metric dict
    from ``fast_metrics`` (or the reference scorer passed in).
    """
    nn = NearestNeighbors(n_neighbors=min(n, len(pool_df))).fit(p_scaled)
    _, ind = nn.kneighbors(t_cent)
    c_idx = [pool_df.index[j] for j in ind[0][:n]]
    metrics = fast_metrics(c_idx)
    return c_idx, metrics


def intermediate_strategy(pool_df, p_scaled, t_cent, n, fast_metrics, max_hill_climbing_swaps=15):
    """Refined Greedy (Hill Climbing).

    Fetch ``n + max_hill_climbing_swaps`` ranked neighbours so that, after the
    first ``n`` seed the group, ``pot_swaps`` can actually contain up to
    ``max_hill_climbing_swaps`` swap candidates.  Every selected position is
    tested against every swap candidate; swaps that improve Weighted Structural
    Distance are kept, and the loop runs until no improving swap remains.

    Returns ``(curr_idx, metrics, conv)`` — the selected index labels, the final
    metric dict (``weighted_structural_distance`` / ``mean_abs_smd``), and the
    convergence series of best scores.
    """
    nn_w = NearestNeighbors(n_neighbors=min(len(pool_df), n + max_hill_climbing_swaps)).fit(
        p_scaled
    )
    _, ind_w = nn_w.kneighbors(t_cent)
    curr_idx = [pool_df.index[j] for j in ind_w[0][:n]]
    pot_swaps = [pool_df.index[j] for j in ind_w[0] if pool_df.index[j] not in curr_idx][
        :max_hill_climbing_swaps
    ]
    curr_metrics = fast_metrics(curr_idx)
    curr_score = curr_metrics["weighted_structural_distance"]
    curr_mean_abs_smd = curr_metrics["mean_abs_smd"]
    conv = [curr_score]
    improved = True
    while improved:
        improved = False
        best_improvement = 0
        best_swap_tuple = None
        # Consider every selected position and every available swap candidate.
        for j in range(len(curr_idx)):
            for swap_in in pot_swaps:
                temp = curr_idx.copy()
                temp[j] = swap_in
                new_metrics = fast_metrics(temp)
                new_score = new_metrics["weighted_structural_distance"]
                # Accept/reject swaps based on Weighted Structural Distance, not Mean Abs SMD.
                improvement = curr_score - new_score
                if improvement > best_improvement:
                    best_improvement = improvement
                    best_swap_tuple = (
                        temp,
                        swap_in,
                        new_score,
                        new_metrics["mean_abs_smd"],
                    )
        if best_improvement > 0 and best_swap_tuple:
            curr_idx, swap_in, curr_score, curr_mean_abs_smd = best_swap_tuple
            if swap_in in pot_swaps:
                pot_swaps.remove(swap_in)
            conv.append(curr_score)
            improved = True
    metrics = {"weighted_structural_distance": curr_score, "mean_abs_smd": curr_mean_abs_smd}
    return curr_idx, metrics, conv


def nearest_neighbor_start(pool_df, p_scaled, t_cent, n):
    """Nearest-neighbour candidate start for the stochastic search."""
    nn_start = NearestNeighbors(n_neighbors=min(n, len(pool_df))).fit(p_scaled)
    _, ind_start = nn_start.kneighbors(t_cent)
    return [pool_df.index[j] for j in ind_start[0][:n]]


def stochastic_genetic_search(
    pool_df,
    test_df_run,
    active_features,
    weights,
    n,
    calculate_metrics_fn,
    eligible_means,
    eligible_stds,
    nn_start_idx,
    n_iterations=1000,
    random_state=42,
    fast_metrics_fn=None,
):
    """
    Stochastic (Genetic Search) — the "Advanced (Thorough)" matching strategy.

    Starts from a good nearest-neighbour candidate group, then repeatedly swaps one
    selected control for one unselected control at random. Candidate groups are scored
    on Weighted Structural Distance (optimisation objective; Mean Abs SMD is diagnostic
    only). Swaps that improve the score are kept; the best group found is tracked and
    returned. Reproducible via a fixed random seed.

    fast_metrics_fn: optional vectorised scorer from make_fast_metrics_fn() taking an
    index-label list directly. When provided it replaces the per-candidate
    calculate_metrics_fn call (same outputs, no per-call dataframe slicing/copying).

    Returns:
        best_idx: list of selected control indices for this n
        best_metrics: the metrics dict for best_idx (from the scoring function)
        evaluated_count: number of candidate groups scored during the search
        convergence: list of best Weighted Structural Distance values over the search
    """
    pool_indices = list(pool_df.index)
    evaluated_count = 0
    convergence = []
    rng = np.random.default_rng(random_state)

    if n <= 0 or n > len(pool_indices):
        empty_metrics = calculate_metrics_fn(
            test_df_run, pool_df.loc[[]], active_features, weights, eligible_means, eligible_stds
        )
        return [], empty_metrics, 0, convergence

    def score(idx_list):
        nonlocal evaluated_count
        if fast_metrics_fn is not None:
            metrics = fast_metrics_fn(idx_list)
        else:
            metrics = calculate_metrics_fn(
                test_df_run,
                pool_df.loc[idx_list],
                active_features,
                weights,
                eligible_means,
                eligible_stds,
            )
        evaluated_count += 1
        return metrics["weighted_structural_distance"], metrics

    # ---- Start from a good nearest-neighbour candidate group ----
    current_idx = list(nn_start_idx)
    current_score, current_metrics = score(current_idx)
    convergence.append(current_score)

    best_idx = list(current_idx)
    best_score = current_score
    best_metrics = current_metrics

    for _iteration in range(n_iterations):
        # Set membership keeps this O(pool) instead of O(pool x n); iteration order over
        # pool_indices is unchanged, so the seeded RNG picks the same swaps as before.
        current_set = set(current_idx)
        available = [idx for idx in pool_indices if idx not in current_set]
        if not available or not current_idx:
            break
        remove_idx = current_idx[rng.integers(0, len(current_idx))]
        add_idx = available[rng.integers(0, len(available))]
        candidate_idx = [idx for idx in current_idx if idx != remove_idx] + [add_idx]
        cand_score, cand_metrics = score(candidate_idx)
        # Keep swaps that improve the score (Weighted Structural Distance).
        if cand_score < current_score:
            current_idx, current_score, current_metrics = candidate_idx, cand_score, cand_metrics
            if current_score < best_score:
                best_score = current_score
                best_idx = list(current_idx)
                best_metrics = current_metrics
            convergence.append(current_score)

    return best_idx, best_metrics, evaluated_count, convergence


def to_match_result(
    strategy: str,
    idx,
    metrics,
    conv,
    evaluated_count: int,
    seed: int | None = None,
) -> MatchResult:
    """Envelope a strategy outcome into the typed, serialisable ``MatchResult``."""
    return MatchResult(
        strategy=strategy,
        control_indices=tuple(idx),
        weighted_structural_distance=metrics.get("weighted_structural_distance"),
        mean_abs_smd=metrics.get("mean_abs_smd"),
        smd_list=tuple(metrics.get("smd_list", [])),
        candidates_evaluated=evaluated_count,
        convergence=tuple(conv),
        seed=seed,
    )
