"""Thread-safe FIFO of mono float32 samples, filled by a capture thread and drained by the mixer."""

import threading
from collections import deque

import numpy as np


class SampleBuffer:
    def __init__(self):
        self._chunks = deque()
        self._count = 0
        self._lock = threading.Lock()
        self.peak = 0.0  # loudest sample since the last take_peak(), for the level meter

    def write(self, samples):
        samples = np.asarray(samples, dtype=np.float32).ravel()
        if samples.size == 0:
            return
        with self._lock:
            self._chunks.append(samples)
            self._count += samples.size
            self.peak = max(self.peak, float(np.max(np.abs(samples))))

    def available(self):
        with self._lock:
            return self._count

    def read(self, n):
        """Return exactly n samples; whatever the source has not delivered is filled with silence."""
        out = np.zeros(n, dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < n and self._chunks:
                chunk = self._chunks[0]
                take = min(n - filled, chunk.size)
                out[filled:filled + take] = chunk[:take]
                filled += take
                if take == chunk.size:
                    self._chunks.popleft()
                else:
                    self._chunks[0] = chunk[take:]
                self._count -= take
        return out

    def drop(self, n):
        """Throw away the n oldest samples (used when a source runs ahead of the clock)."""
        with self._lock:
            while n > 0 and self._chunks:
                chunk = self._chunks[0]
                if chunk.size <= n:
                    self._chunks.popleft()
                    self._count -= chunk.size
                    n -= chunk.size
                else:
                    self._chunks[0] = chunk[n:]
                    self._count -= n
                    n = 0

    def take_peak(self):
        with self._lock:
            peak, self.peak = self.peak, 0.0
        return peak
