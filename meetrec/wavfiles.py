"""Crash-safe chunked WAV recording and joining the chunks into one file.

Each part file has its header patched on every flush, so after a crash every part is a
valid WAV up to the last flush. Joining also trusts the file size, not the header, so a
part cut off between flushes still keeps all the audio it holds.
"""

import os
import struct
from pathlib import Path

import numpy as np

HEADER_SIZE = 44


def _header(rate, data_bytes, channels=1, bits=16):
    block = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits)
            + b"data" + struct.pack("<I", data_bytes))


def to_pcm16(samples):
    samples = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (samples * 32767).astype("<i2").tobytes()


class CrashSafeWav:
    def __init__(self, path, rate):
        self.path = Path(path)
        self.rate = rate
        self.data_bytes = 0
        self._f = open(self.path, "wb")
        self._f.write(_header(rate, 0))

    def write_pcm(self, pcm):
        self._f.write(pcm)
        self.data_bytes += len(pcm)

    def flush(self):
        self._f.seek(4)
        self._f.write(struct.pack("<I", 36 + self.data_bytes))
        self._f.seek(40)
        self._f.write(struct.pack("<I", self.data_bytes))
        self._f.seek(0, os.SEEK_END)
        self._f.flush()
        os.fsync(self._f.fileno())

    def close(self):
        if not self._f.closed:
            self.flush()
            self._f.close()


class ChunkedRecorder:
    """Writes mono 16-bit audio as part-0001.wav, part-0002.wav, ... in parts_dir."""

    def __init__(self, parts_dir, rate, chunk_seconds=60, flush_seconds=2):
        self.parts_dir = Path(parts_dir)
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        self.rate = rate
        self.chunk_frames = int(chunk_seconds * rate)
        self.flush_frames = max(1, int(flush_seconds * rate))
        self.part_index = 0
        self.total_frames = 0
        self._current = None
        self._frames_in_part = 0
        self._since_flush = 0

    def _open_next(self):
        if self._current:
            self._current.close()
        self.part_index += 1
        self._current = CrashSafeWav(self.parts_dir / f"part-{self.part_index:04d}.wav", self.rate)
        self._frames_in_part = 0

    def write(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        pos = 0
        while pos < samples.size:
            if self._current is None or self._frames_in_part >= self.chunk_frames:
                self._open_next()
            take = min(samples.size - pos, self.chunk_frames - self._frames_in_part)
            self._current.write_pcm(to_pcm16(samples[pos:pos + take]))
            self._frames_in_part += take
            self._since_flush += take
            self.total_frames += take
            pos += take
            if self._since_flush >= self.flush_frames:
                self._current.flush()
                self._since_flush = 0

    def close(self):
        if self._current:
            self._current.close()
            self._current = None


def _read_rate(path):
    with open(path, "rb") as f:
        head = f.read(HEADER_SIZE)
    if len(head) < HEADER_SIZE or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise ValueError(f"{path} is not a WAV file written by meetrec")
    return struct.unpack("<I", head[24:28])[0]


def assemble(parts_dir, out_path):
    """Join every part in parts_dir into out_path. Returns the number of seconds written."""
    parts = sorted(Path(parts_dir).glob("part-*.wav"))
    if not parts:
        raise FileNotFoundError(f"no part-*.wav files in {parts_dir}")
    rate = _read_rate(parts[0])
    out = CrashSafeWav(out_path, rate)
    for part in parts:
        if _read_rate(part) != rate:
            raise ValueError(f"{part} has a different sample rate")
        size = part.stat().st_size - HEADER_SIZE
        size -= size % 2  # a crash can leave half a sample at the end
        with open(part, "rb") as f:
            f.seek(HEADER_SIZE)
            remaining = size
            while remaining > 0:
                block = f.read(min(remaining, 1 << 20))
                if not block:
                    break
                out.write_pcm(block)
                remaining -= len(block)
    out.close()
    return out.data_bytes / 2 / rate
