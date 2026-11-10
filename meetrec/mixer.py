"""Mixes several sources into one mono stream, paced by the wall clock.

The clock, not the sources, decides how many samples exist. A source that is silent
(Windows sends no packets while nothing plays) or briefly late is filled with zeros,
and a source that runs ahead is trimmed, so the recording always matches real time.
"""

import time

import numpy as np


class Mixer:
    def __init__(self, buffers, rate, latency=0.25, max_backlog=0.5, gains=None, clock=time.monotonic):
        self.buffers = list(buffers)
        self.rate = rate
        self.latency = latency          # how far behind real time we read, to absorb packet jitter
        self.max_backlog = max_backlog  # extra buffered audio allowed before the oldest is dropped
        self.gains = list(gains) if gains else [1.0] * len(self.buffers)
        self.clock = clock
        self.start = None
        self.emitted = 0

    def step(self):
        now = self.clock()
        if self.start is None:
            self.start = now
        target = round((now - self.start - self.latency) * self.rate)
        n = target - self.emitted
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        out = np.zeros(n, dtype=np.float32)
        backlog_limit = int(self.max_backlog * self.rate)
        for buf, gain in zip(self.buffers, self.gains):
            excess = buf.available() - n - backlog_limit
            if excess > 0:
                buf.drop(excess)
            out += buf.read(n) * gain
        np.clip(out, -1.0, 1.0, out=out)
        self.emitted += n
        return out

    def drain(self):
        """At stop: emit what is still buffered, up to the latency window."""
        n = int(self.latency * self.rate)
        if self.start is None or n <= 0:
            return np.zeros(0, dtype=np.float32)
        out = np.zeros(n, dtype=np.float32)
        for buf, gain in zip(self.buffers, self.gains):
            out += buf.read(n) * gain
        np.clip(out, -1.0, 1.0, out=out)
        self.emitted += n
        return out
