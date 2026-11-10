"""Streaming integer-factor decimation (e.g. 48 kHz -> 16 kHz) with a windowed-sinc low-pass."""

import numpy as np


class Decimator:
    def __init__(self, factor, taps_per_phase=24):
        if factor < 1 or int(factor) != factor:
            raise ValueError("factor must be a positive integer")
        self.factor = int(factor)
        if self.factor == 1:
            return
        n = self.factor * taps_per_phase + 1
        cutoff = 0.45 / self.factor  # cycles per input sample, just under the new Nyquist
        m = np.arange(n) - (n - 1) / 2
        h = 2 * cutoff * np.sinc(2 * cutoff * m) * np.hamming(n)
        self.h = (h / h.sum()).astype(np.float32)
        self.history = np.zeros(n - 1, dtype=np.float32)
        self.phase = 0

    def process(self, x):
        x = np.asarray(x, dtype=np.float32)
        if self.factor == 1 or x.size == 0:
            return x
        buf = np.concatenate([self.history, x])
        y = np.convolve(buf, self.h, mode="valid")  # one output per new input sample
        self.history = buf[-(self.h.size - 1):]
        out = y[self.phase::self.factor]
        self.phase = (self.phase - y.size) % self.factor
        return out.astype(np.float32)
