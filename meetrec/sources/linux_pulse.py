"""Linux capture via `parec` (PulseAudio or PipeWire-Pulse) that follows the devices the meeting app uses.

Every second it asks the sound server which output (sink) the app plays to and which input (source)
it records from, and moves the capture there. So a meeting heard on a USB/Bluetooth headset is
recorded from that headset, even when it is not the system default, and switching devices
mid-meeting is followed. When the app has no stream open, the system defaults are used.
"""

import json
import shutil
import subprocess
import threading

import numpy as np

POLL_SECONDS = 1.0


def _pactl_json(*args):
    try:
        out = subprocess.run(["pactl", "-f", "json", *args], capture_output=True, text=True, timeout=5)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def _pactl(*args):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _is_app(stream, app):
    props = stream.get("properties", {})
    names = " ".join(str(props.get(k, "")) for k in
                     ("application.process.binary", "application.name", "application.id")).lower()
    return bool(app) and app.lower() in names


def _app_device(kind, app):
    """Device index the app's newest stream uses: kind 'sink' (playback) or 'source' (recording)."""
    streams = _pactl_json("list", "sink-inputs" if kind == "sink" else "source-outputs")
    mine = [s for s in streams if _is_app(s, app) and not s.get("corked", False)] or \
           [s for s in streams if _is_app(s, app)]
    return mine[-1][kind] if mine else None


def resolve_device(kind, app):
    """(parec device name, human description) for the current target of `kind`."""
    devices = _pactl_json("list", "sinks" if kind == "sink" else "sources")
    by_index = {d.get("index"): d for d in devices}
    index = _app_device(kind, app) if app else None
    dev = by_index.get(index)
    if dev is None:
        default = _pactl("get-default-sink" if kind == "sink" else "get-default-source")
        dev = next((d for d in devices if d.get("name") == default), None)
        if dev is None:
            return ("@DEFAULT_MONITOR@" if kind == "sink" else "@DEFAULT_SOURCE@"), "default"
    name = dev.get("monitor_source") if kind == "sink" else dev.get("name")
    return name, dev.get("description") or dev.get("name")


class FollowingPulseSource:
    """kind='sink': what the app plays (monitor of its output). kind='source': the app's microphone."""

    def __init__(self, buffer, rate, kind, app=None, on_switch=None):
        self.buffer = buffer
        self.rate = rate
        self.kind = kind
        self.app = app
        self.label = "system" if kind == "sink" else "mic"
        self.on_switch = on_switch or (lambda label, desc: None)
        self.device = None
        self.description = None
        self._proc = None
        self._reader = None
        self._watcher = None
        self._stopping = threading.Event()

    def start(self):
        for tool in ("parec", "pactl"):
            if not shutil.which(tool):
                raise RuntimeError(f"{tool} not found. Install it with: sudo apt install pulseaudio-utils")
        self._switch(*resolve_device(self.kind, self.app))
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()

    def _switch(self, device, description):
        self._stop_proc()
        self.device, self.description = device, description
        self._proc = subprocess.Popen(
            ["parec", f"--device={device}", "--format=s16le", f"--rate={self.rate}", "--channels=1",
             "--latency-msec=20", "--client-name=meetrec"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._reader = threading.Thread(target=self._read, args=(self._proc,), daemon=True)
        self._reader.start()
        self.on_switch(self.label, description)

    def _watch(self):
        while not self._stopping.wait(POLL_SECONDS):
            device, description = resolve_device(self.kind, self.app)
            if device != self.device or (self._proc and self._proc.poll() is not None):
                self._switch(device, description)

    def _read(self, proc):
        leftover = b""
        while True:
            data = proc.stdout.read1(4096)
            if not data:
                break
            data = leftover + data
            usable = len(data) - len(data) % 2
            leftover = data[usable:]
            self.buffer.write(np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0)

    def _stop_proc(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._reader:
            self._reader.join(timeout=2)  # never two readers writing into the buffer at once
            self._reader = None

    def stop(self):
        self._stopping.set()
        if self._watcher:
            self._watcher.join(timeout=3)
        self._stop_proc()

