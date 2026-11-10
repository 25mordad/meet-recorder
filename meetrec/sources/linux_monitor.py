"""Linux: capture everything the default output plays, via `parec` (PulseAudio or PipeWire-Pulse).

Per-app capture is Windows-only for now; on Linux the whole system output is recorded.
"""

import shutil
import subprocess
import threading

import numpy as np


class PulseMonitorSource:
    label = "system"

    def __init__(self, buffer, rate):
        self.buffer = buffer
        self.rate = rate
        self._proc = None
        self._thread = None

    def start(self):
        if not shutil.which("parec"):
            raise RuntimeError("parec not found. Install it with: sudo apt install pulseaudio-utils")
        self._proc = subprocess.Popen(
            ["parec", "--device=@DEFAULT_MONITOR@", "--format=s16le",
             f"--rate={self.rate}", "--channels=1", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        leftover = b""
        while True:
            data = self._proc.stdout.read1(4096) if hasattr(self._proc.stdout, "read1") else self._proc.stdout.read(4096)
            if not data:
                break
            data = leftover + data
            usable = len(data) - len(data) % 2
            leftover = data[usable:]
            self.buffer.write(np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0)

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None
