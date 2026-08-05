"""Random-stream derivation for the power spike (NumPy >= 1.24 compatible).

``numpy.random.Generator.spawn`` was introduced in NumPy 1.25, but the project
supports ``numpy>=1.24``. Independent Monte-Carlo streams (threshold
calibration, alternative simulation, diagnostics) are therefore derived from a
single seed via ``SeedSequence.spawn`` — available since NumPy 1.17 — and each
child sequence builds its own fresh ``default_rng``.
"""

from __future__ import annotations

import numpy as np


def child_rngs(seed, n):
    """Return ``n`` independent, reproducible :class:`np.random.Generator` streams.

    ``seed`` may be an int or a :class:`np.random.SeedSequence`. The seed
    sequence spawns ``n`` child sequences and each child builds a fresh
    ``default_rng``, so the streams are independent of one another and the
    derivation works on NumPy >= 1.24 (``Generator.spawn`` needs >= 1.25).

    The children are spawned directly from ``SeedSequence(seed)`` — exactly the
    child sequences that ``np.random.default_rng(seed).spawn(n)`` produces — so
    results are identical to the NumPy >= 1.25 path.
    """
    seq = seed if isinstance(seed, np.random.SeedSequence) else np.random.SeedSequence(seed)
    children = seq.spawn(n)
    return tuple(np.random.default_rng(child) for child in children)
