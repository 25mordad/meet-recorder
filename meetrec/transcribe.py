"""Speech-to-text for a recording, locally with faster-whisper (no internet after the model download)."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _stamp(seconds, srt=False):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}" if srt else f"{h:02d}:{m:02d}:{s:02d}"


def write_outputs(segments, txt_path, srt_path):
    """segments: list of (start, end, text). Writes a timestamped .txt and an .srt."""
    with open(txt_path, "w", encoding="utf-8") as txt:
        for start, _end, text in segments:
            txt.write(f"[{_stamp(start)}] {text}\n")
    with open(srt_path, "w", encoding="utf-8") as srt:
        for i, (start, end, text) in enumerate(segments, 1):
            srt.write(f"{i}\n{_stamp(start, True)} --> {_stamp(end, True)}\n{text}\n\n")


def load_audio(path):
    """16 kHz mono float32. Our recordings are read directly; other files go through ffmpeg."""
    import wave
    import numpy as np
    try:
        with wave.open(str(path), "rb") as w:
            if w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2:
                return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    except wave.Error:
        pass
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return str(path)  # let faster-whisper decode it
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768


def transcribe(wav, model="large-v3-turbo", language=None, out_dir=None, device="auto", compute_type="int8", threads=2):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper is not installed. Run: pip install -r requirements-transcribe.txt")

    wav = Path(wav)
    out_dir = Path(out_dir) if out_dir else wav.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / (wav.stem + ".txt")
    srt_path = out_dir / (wav.stem + ".srt")

    # stay out of the way: lowest CPU priority and only a few cores, so the computer stays usable
    if hasattr(os, "nice"):
        os.nice(19)
    print(f"Loading model {model} ({threads} threads, low priority) ...", flush=True)
    m = WhisperModel(model, device=device, compute_type=compute_type, cpu_threads=threads, num_workers=1)
    seg_iter, info = m.transcribe(load_audio(wav), language=language, vad_filter=True, beam_size=5)
    print(f"Language: {info.language} ({info.language_probability:.0%}), length {_stamp(info.duration)}", flush=True)

    segments = []
    t0 = time.time()
    for seg in seg_iter:
        text = seg.text.strip()
        if not text:
            continue
        segments.append((seg.start, seg.end, text))
        pct = seg.end / info.duration * 100 if info.duration else 0
        print(f"\r{pct:5.1f}%  [{_stamp(seg.start)}] {text[:70]:<70}", end="", file=sys.stderr, flush=True)
        # write as we go, so an interrupted run still leaves a usable partial transcript
        if len(segments) % 20 == 0:
            write_outputs(segments, txt_path, srt_path)
    print(file=sys.stderr)
    write_outputs(segments, txt_path, srt_path)
    print(f"Saved {txt_path} and {srt_path} ({len(segments)} segments, {time.time() - t0:.0f} s)")
    return txt_path
