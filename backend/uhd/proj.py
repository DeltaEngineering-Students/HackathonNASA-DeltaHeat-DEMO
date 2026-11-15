"""pyproj transformers that are cheap to use from many threads.

pyproj keeps the PROJ object of a ``Transformer`` per thread (``threading.local``): the first ``transform`` in every new
thread rebuilds it. For ``Transformer.from_crs`` that rebuild repeats PROJ's operation search in proj.db — measured on
the VM at 0.14 s alone and 0.5–0.9 s each when 40 threads start at once (≈ 5 s wall, serialised, the event loop
stalled up to 0.6 s). The API runs tiles and reports in a threadpool whose idle threads exit after 10 s, so a fresh
worker (deploy) or a burst after a quiet spell paid that for every thread × every transformer: the 10–24 s tile,
/api/analyze and /api/places stalls after a restart.

``transformer(a, b)`` returns the same operation that ``from_crs(a, b, always_xy=True)`` uses, built from its PROJ
pipeline string: identical numbers, ~1 ms per new thread. Falls back to ``from_crs`` when there is no single pipeline.
"""

from __future__ import annotations

from functools import lru_cache

from pyproj import Transformer
from pyproj.transformer import TransformerGroup


@lru_cache(maxsize=None)
def transformer(src, dst) -> Transformer:
    try:
        g = TransformerGroup(src, dst, always_xy=True)
        if g.transformers and g.best_available:
            return Transformer.from_pipeline(g.transformers[0].definition)
    except Exception:  # noqa: BLE001 — never fail on the fast path; from_crs is always correct
        pass
    return Transformer.from_crs(src, dst, always_xy=True)
