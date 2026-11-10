"""Microphone capture through PortAudio (sounddevice). Works on Windows and Linux."""

import numpy as np


class MicSource:
    label = "mic"

    def __init__(self, buffer, rate, device=None):
        self.buffer = buffer
        self.rate = rate
        self.device = device
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        self.buffer.write(np.array(indata[:, 0], dtype=np.float32))

    def start(self):
        import sounddevice as sd
        device = self.device
        if device is not None and str(device).isdigit():
            device = int(device)
        self._stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                      device=device, callback=self._callback)
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def list_microphones():
    import sounddevice as sd
    lines = []
    default_in = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "*" if i == default_in else " "
            host = sd.query_hostapis(d["hostapi"])["name"]
            lines.append(f"{mark} {i:3d}  {d['name']}  [{host}]")
    return lines
