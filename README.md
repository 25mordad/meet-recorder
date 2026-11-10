# meet-recorder

A small command-line recorder that saves the full audio of an online meeting
(Google Meet, or any meeting that runs in the browser) as **one mono WAV file**,
so you can transcribe it afterwards with Whisper or any other speech-to-text tool.

It records what the browser plays (everyone else in the call) and your microphone
(you) at the same time, mixes them live into a single track, and writes it to disk
as it goes.

## What it is for

- Keeping a full recording of meetings you take part in, without a bot joining the call
  and without a paid Google Workspace plan.
- Getting a clean audio file to turn into a transcript, meeting notes or a summary later.
- Working with any meeting tool that runs in a browser (Meet, Zoom web, Teams web, Jitsi).
  On Windows you can also point it at any other app.

It does not transcribe anything itself. It only produces the audio file.

## What it does

- **Records only the meeting app (Windows).** It uses WASAPI *process loopback*, which
  captures the audio of one process tree (Chrome by default) and nothing else. Notification
  sounds, music or videos in other apps stay out of the recording.
- **Works with headphones.** The capture follows the app, not the output device. Wired, USB
  and Bluetooth headphones all work, and switching or plugging them in mid-meeting does not
  break the recording.
- **Mixes your microphone in live.** The result is one mono track with both sides of the
  conversation, at 16 kHz by default (what Whisper uses).
- **Keeps real time.** A wall clock drives the mixer. When nobody speaks it writes silence,
  so a minute in the file is a minute of the meeting.
- **Survives crashes.** Audio is written in 60-second part files and forced to disk every
  2 seconds, so a crash or power cut loses at most about 2 seconds. When you stop, the parts
  are joined into `recordings/meeting-YYYYMMDD-HHMMSS.wav`.
- **Linux too.** On Linux it records everything the default output plays, plus the
  microphone. Per-app capture is Windows-only for now.

## Status

Early version. The mixing, chunked writing and joining are covered by tests. The Windows
process-loopback capture still needs testing on more Windows machines. Run `test.bat` first,
because it starts a real one-second capture.

## Requirements

- **Windows 10 version 2004 (build 19041) or newer**, or Windows 11, or a Linux desktop with
  PulseAudio or PipeWire.
- **Python 3.10 or newer.**

## Install

Everything installs into a `.venv` folder inside the project. Nothing is installed
system-wide and no administrator rights are needed. To uninstall, delete the folder.

### Windows

1. Install Python from [python.org](https://www.python.org/downloads/windows/). The default
   "install for current user" option does not need admin rights.
2. Download this repository (green **Code** button, then **Download ZIP**) and unzip it, or
   use `git clone`.
3. Double-click **`setup.bat`**. It creates `.venv` and installs the dependencies into it.
4. Double-click **`test.bat`**. All tests should pass.

### Linux

```sh
sudo apt install libportaudio2 pulseaudio-utils   # audio libraries (Ubuntu/Debian)
./setup.sh                                         # creates .venv and installs into it
.venv/bin/python -m pytest
```

## Use

1. Join the meeting in Chrome.
2. Start recording:
   - Windows: double-click **`record.bat`**
   - Linux: `.venv/bin/python -m meetrec record`
3. While it records, a line shows the elapsed time and a level meter for each side.
4. Stop with **Ctrl+C**. The file is saved in `recordings/`.

Chrome must already be running when you start. If you close and reopen Chrome during the
meeting, start a new recording.

### Options

Add these after `record.bat` in a terminal, or after `python -m meetrec record`:

| option | meaning |
|---|---|
| `--app msedge` | record Edge, `firefox` or a process id instead of Chrome (Windows) |
| `--all-system` | record all system audio instead of one app |
| `--no-mic` | do not record the microphone |
| `--mic 3` | choose a microphone; list them with `python -m meetrec devices` |
| `--mic-gain 1.5`, `--system-gain 0.8` | balance the two sides of the mix |
| `--rate 48000` | output sample rate: 16000 (default), 24000 or 48000 |
| `--out D:\meetings` | output folder (default `recordings`) |
| `--chunk-seconds`, `--flush-seconds` | part length and disk-flush interval (default 60 and 2) |
| `--keep-parts` | keep the part files after joining them |

### After a crash

If the program stopped before it could join the parts, join them yourself:

```
python -m meetrec assemble recordings\meeting-20261110-153000.parts
```

## Transcribing the result

Any speech-to-text tool that accepts WAV will work. For example, locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper):

```sh
pip install faster-whisper
python -c "from faster_whisper import WhisperModel; m = WhisperModel('large-v3'); \
print(''.join(s.text for s in m.transcribe('recordings/meeting-....wav')[0]))"
```

## How it works

```
Chrome audio (process loopback) ─┐
                                 ├─► mixer (wall clock, 48 kHz) ─► 16 kHz ─► part files ─► meeting.wav
microphone (PortAudio) ──────────┘
```

| file | role |
|---|---|
| `meetrec/sources/win_process_loopback.py` | Windows per-process capture (`ActivateAudioInterfaceAsync`, pure ctypes) |
| `meetrec/sources/linux_monitor.py` | Linux capture of the default output (`parec`) |
| `meetrec/sources/mic.py` | microphone capture (`sounddevice`) |
| `meetrec/mixer.py` | clock-driven mixing, silence filling, drift handling |
| `meetrec/resample.py` | 48 kHz to 16/24 kHz low-pass decimation |
| `meetrec/wavfiles.py` | crash-safe part files and joining |

## Consent

Recording people without telling them is illegal in many places. Tell everyone in the
meeting that you are recording.
