"""Runs one recording session: sources -> mixer -> decimator -> chunked WAV -> final WAV."""

import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from .buffer import SampleBuffer
from .mixer import Mixer
from .resample import Decimator
from .wavfiles import ChunkedRecorder, assemble

MIX_RATE = 48000


def build_system_source(buffer, app, all_system):
    if sys.platform == "win32":
        from .sources import procs
        from .sources.win_process_loopback import ProcessLoopbackSource, own_pid
        if all_system:
            # Everything except this recorder itself.
            return ProcessLoopbackSource(buffer, own_pid(), include_tree=False), "all system audio"
        if str(app).isdigit():
            pid = int(app)
        else:
            name = procs.normalize_name(app)
            pid = procs.find_root_pid(procs.running_processes(), name)
            if pid is None:
                raise RuntimeError(f"{name} is not running. Open the meeting in it first, then start recording.")
        return ProcessLoopbackSource(buffer, pid, include_tree=True), f"{app} (pid {pid})"
    from .sources.linux_monitor import PulseMonitorSource
    return PulseMonitorSource(buffer, MIX_RATE), "all system audio (default output monitor)"


def _bar(level, width=20):
    filled = min(width, int(level * width + 0.999)) if level > 0.001 else 0
    return "#" * filled + "." * (width - filled)


def record(out_dir, app="chrome", all_system=False, mic=True, mic_device=None, rate=16000,
           chunk_seconds=60, flush_seconds=2, keep_parts=False, mic_gain=1.0, system_gain=1.0,
           stop_after=None):
    if MIX_RATE % rate:
        raise ValueError(f"--rate must divide {MIX_RATE} (e.g. 48000, 24000, 16000)")
    out_dir = Path(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final_path = out_dir / f"meeting-{stamp}.wav"
    parts_dir = out_dir / f"meeting-{stamp}.parts"

    sources, buffers, gains = [], [], []
    system_buf = SampleBuffer()
    system_src, system_desc = build_system_source(system_buf, app, all_system)
    sources.append(system_src)
    buffers.append(system_buf)
    gains.append(system_gain)
    mic_buf = None
    if mic:
        from .sources.mic import MicSource
        mic_buf = SampleBuffer()
        sources.append(MicSource(mic_buf, MIX_RATE, mic_device))
        buffers.append(mic_buf)
        gains.append(mic_gain)

    started = []
    try:
        for src in sources:
            src.start()
            started.append(src)
    except Exception:
        for src in started:
            src.stop()
        raise

    mixer = Mixer(buffers, MIX_RATE, gains=gains)
    decimator = Decimator(MIX_RATE // rate)
    writer = ChunkedRecorder(parts_dir, rate, chunk_seconds, flush_seconds)
    print(f"Recording {system_desc}" + (" + microphone" if mic else "") + f" -> {final_path}")
    print("Press Ctrl+C to stop.")
    t0 = time.monotonic()
    last_status = 0.0
    try:
        while stop_after is None or time.monotonic() - t0 < stop_after:
            time.sleep(0.05)
            writer.write(decimator.process(mixer.step()))
            now = time.monotonic()
            if now - last_status >= 1.0:
                last_status = now
                secs = int(writer.total_frames / rate)
                line = f"\r{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}  system {_bar(system_buf.take_peak())}"
                if mic_buf:
                    line += f"  mic {_bar(mic_buf.take_peak())}"
                print(line, end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping...")
        for src in sources:
            src.stop()
        writer.write(decimator.process(mixer.drain()))
        writer.close()

    seconds = assemble(parts_dir, final_path)
    if not keep_parts:
        shutil.rmtree(parts_dir)
    print(f"Saved {final_path} ({seconds:.0f} s)")
    return final_path
