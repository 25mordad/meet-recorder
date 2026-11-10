import struct
import threading
import time
import wave

import numpy as np
import pytest

from meetrec import recorder
from meetrec.buffer import SampleBuffer
from meetrec.mixer import Mixer
from meetrec.resample import Decimator
from meetrec.sources.procs import find_root_pid, normalize_name
from meetrec.wavfiles import ChunkedRecorder, CrashSafeWav, assemble, to_pcm16


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# --- buffer ---

def test_buffer_read_pads_with_silence():
    b = SampleBuffer()
    b.write([0.1, 0.2])
    out = b.read(5)
    assert out.tolist() == pytest.approx([0.1, 0.2, 0, 0, 0])
    assert b.available() == 0


def test_buffer_read_splits_chunks_and_drop():
    b = SampleBuffer()
    b.write([1, 2, 3])
    b.write([4, 5])
    b.drop(2)
    assert b.read(2).tolist() == [3, 4]
    assert b.available() == 1


# --- mixer ---

def test_mixer_follows_clock_and_fills_silence():
    clock = FakeClock()
    a, s = SampleBuffer(), SampleBuffer()
    m = Mixer([a, s], rate=1000, latency=0.1, clock=clock)
    assert m.step().size == 0                 # starts the clock
    clock.t = 0.05
    assert m.step().size == 0                 # still inside the latency window
    a.write(np.full(200, 0.25))               # only one source delivers anything
    clock.t = 0.3
    out = m.step()
    assert out.size == 200                    # 0.3 s - 0.1 s latency at 1 kHz
    assert np.allclose(out, 0.25)             # silent source counted as zeros
    clock.t = 1.1
    out = m.step()
    assert out.size == 800 and np.allclose(out, 0)  # nothing delivered: pure silence, timeline kept
    assert m.emitted == 1000


def test_mixer_sums_and_clips():
    clock = FakeClock()
    a, s = SampleBuffer(), SampleBuffer()
    m = Mixer([a, s], rate=100, latency=0.0, gains=[1.0, 0.5], clock=clock)
    m.step()
    a.write([0.2, 0.9])
    s.write([0.2, 0.6])
    clock.t = 0.02
    assert m.step().tolist() == pytest.approx([0.3, 1.0])


def test_mixer_drops_backlog_from_fast_source():
    clock = FakeClock()
    a = SampleBuffer()
    m = Mixer([a], rate=100, latency=0.0, max_backlog=0.5, clock=clock)
    m.step()
    a.write(np.arange(300, dtype=np.float32) / 1000)  # 3 s of audio arrives at once
    clock.t = 0.1
    out = m.step()
    assert out.size == 10
    assert a.available() == 50                 # only max_backlog kept
    assert out[0] == pytest.approx(0.24)                     # oldest audio was dropped


# --- decimator ---

def _tone(freq, rate, seconds):
    t = np.arange(int(rate * seconds)) / rate
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def test_decimator_keeps_speech_band_and_removes_alias():
    d = Decimator(3)
    low = np.concatenate([d.process(block) for block in np.array_split(_tone(1000, 48000, 1.0), 37)])
    assert low.size == 16000
    assert np.sqrt(np.mean(low[2000:] ** 2)) == pytest.approx(1 / np.sqrt(2), rel=0.03)
    d2 = Decimator(3)
    high = d2.process(_tone(15000, 48000, 1.0))
    assert np.sqrt(np.mean(high[2000:] ** 2)) < 0.01


def test_decimator_block_size_does_not_matter():
    x = _tone(440, 48000, 0.3)
    whole = Decimator(3).process(x)
    d = Decimator(3)
    parts = np.concatenate([d.process(x[i:i + 7]) for i in range(0, x.size, 7)])
    assert np.allclose(whole, parts, atol=1e-5)


# --- wav files ---

def test_crash_safe_wav_is_valid_after_flush_without_close(tmp_path):
    path = tmp_path / "a.wav"
    w = CrashSafeWav(path, 16000)
    w.write_pcm(to_pcm16(np.zeros(1600)))
    w.flush()
    # simulate a crash: never call close()
    with wave.open(str(path)) as r:
        assert r.getframerate() == 16000 and r.getnframes() == 1600


def test_chunked_recorder_splits_and_assembles(tmp_path):
    rec = ChunkedRecorder(tmp_path / "x.parts", rate=1000, chunk_seconds=1, flush_seconds=0.5)
    signal = np.linspace(-0.5, 0.5, 2500, dtype=np.float32)
    for block in np.array_split(signal, 13):
        rec.write(block)
    rec.close()
    parts = sorted((tmp_path / "x.parts").glob("part-*.wav"))
    assert [p.name for p in parts] == ["part-0001.wav", "part-0002.wav", "part-0003.wav"]
    seconds = assemble(tmp_path / "x.parts", tmp_path / "x.wav")
    assert seconds == pytest.approx(2.5)
    with wave.open(str(tmp_path / "x.wav")) as r:
        data = np.frombuffer(r.readframes(r.getnframes()), dtype="<i2")
    assert np.array_equal(data, np.frombuffer(to_pcm16(signal), dtype="<i2"))


def test_assemble_recovers_audio_written_after_last_flush(tmp_path):
    parts = tmp_path / "p.parts"
    parts.mkdir()
    w = CrashSafeWav(parts / "part-0001.wav", 1000)
    w.write_pcm(to_pcm16(np.full(100, 0.1)))
    w.flush()
    w.write_pcm(to_pcm16(np.full(50, 0.2)) + b"\x01")  # unflushed tail + half a sample
    w._f.flush()                                      # data reached the disk, header did not
    seconds = assemble(parts, tmp_path / "p.wav")
    assert seconds == pytest.approx(0.15)
    with open(parts / "part-0001.wav", "rb") as f:
        assert struct.unpack("<I", f.read(44)[40:44])[0] == 200  # header still says 100 frames


def test_assemble_without_parts_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble(tmp_path, tmp_path / "out.wav")


# --- browser process lookup ---

def test_find_root_pid_picks_main_browser_process():
    procs = [
        (4, 0, "System", 0),
        (100, 50, "explorer.exe", 1),
        (200, 100, "chrome.exe", 10),   # main browser
        (201, 200, "chrome.exe", 11),   # renderer
        (202, 200, "chrome.exe", 12),   # audio service
        (300, 100, "Chrome.exe", 20),   # a second, newer instance
        (400, 100, "msedge.exe", 5),
    ]
    assert find_root_pid(procs, "chrome.exe") == 200
    assert find_root_pid(procs, "msedge.exe") == 400
    assert find_root_pid(procs, "firefox.exe") is None


def test_normalize_name():
    assert normalize_name("Chrome") == "chrome.exe"
    assert normalize_name("msedge.exe") == "msedge.exe"


# --- whole pipeline with fake sources ---

class FakeSource:
    def __init__(self, buffer, value, rate=48000):
        self.buffer, self.value, self.rate = buffer, value, rate
        self._stop = threading.Event()

    def start(self):
        def run():
            while not self._stop.is_set():
                self.buffer.write(np.full(self.rate // 100, self.value, dtype=np.float32))
                time.sleep(0.01)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()


def test_record_end_to_end_with_fake_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "build_system_source",
                        lambda buf, app, all_system: (FakeSource(buf, 0.2), "fake"))
    path = recorder.record(tmp_path, mic=False, rate=16000, chunk_seconds=1, stop_after=2.5)
    assert not list(tmp_path.glob("*.parts"))  # parts removed after joining
    with wave.open(str(path)) as r:
        assert r.getnchannels() == 1 and r.getframerate() == 16000
        frames = r.getnframes()
        data = np.frombuffer(r.readframes(frames), dtype="<i2") / 32767
    assert 2.3 < frames / 16000 < 3.0
    middle = data[8000:-8000]
    assert np.median(middle) == pytest.approx(0.2, abs=0.01)


def test_record_rejects_rate_that_does_not_divide(tmp_path):
    with pytest.raises(ValueError):
        recorder.record(tmp_path, rate=44100)
