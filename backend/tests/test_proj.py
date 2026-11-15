"""uhd.proj: pipeline-built transformers give the same numbers as from_crs and stay cheap in new threads."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from pyproj import Transformer

from uhd.proj import transformer

RNG = np.random.default_rng(0)
SAMPLES = {
    3857: (RNG.uniform(2.3e6, 4.6e6, 2000), RNG.uniform(5.4e6, 7.0e6, 2000)),
    4326: (RNG.uniform(21.5, 41.0, 2000), RNG.uniform(43.5, 53.0, 2000)),
    3035: (RNG.uniform(5.0e6, 6.6e6, 2000), RNG.uniform(2.3e6, 3.6e6, 2000)),
}


@pytest.mark.parametrize("src,dst", [(3857, 3035), (3035, 3857), (4326, 3035), (3035, 4326)])
def test_same_numbers_as_from_crs(src, dst):
    x, y = SAMPLES[src]
    a = Transformer.from_crs(src, dst, always_xy=True).transform(x, y)
    b = transformer(src, dst).transform(x, y)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_cheap_in_new_threads():
    t = transformer(3857, 3035)
    x, y = SAMPLES[3857]
    t.transform(x[:10], y[:10])
    took = []

    def f():
        t0 = time.perf_counter()
        t.transform(x[:10], y[:10])
        took.append(time.perf_counter() - t0)

    ths = [threading.Thread(target=f) for _ in range(20)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    assert max(took) < 0.05  # from_crs: 0.1–0.9 s per new thread (proj.db operation search)
