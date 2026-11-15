"""Tiny thread-safe LRU dict (the API calls science from a threadpool), bounded by entry count and optionally bytes."""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable


class LRU:
    def __init__(self, maxsize: int, maxbytes: int | None = None, sizeof: Callable[[object], int] | None = None):
        self.maxsize = maxsize
        self.maxbytes = maxbytes
        self._sizeof = sizeof or (lambda v: 0)
        self._d: OrderedDict = OrderedDict()   # key -> (value, nbytes)
        self.nbytes = 0
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key][0]
            return default

    def put(self, key, value) -> None:
        n = int(self._sizeof(value)) if self.maxbytes is not None else 0
        with self._lock:
            if key in self._d:
                self.nbytes -= self._d.pop(key)[1]
            if self.maxbytes is not None and n > self.maxbytes:
                return                          # larger than the whole budget: do not cache
            self._d[key] = (value, n)
            self.nbytes += n
            while len(self._d) > self.maxsize or (self.maxbytes is not None and self.nbytes > self.maxbytes):
                self.nbytes -= self._d.popitem(last=False)[1][1]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self.nbytes = 0

    def __len__(self) -> int:
        return len(self._d)
