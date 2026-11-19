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
- **Linux too.** On Linux it records the output device Chrome plays to and the microphone
  Chrome uses, even when they are not the system default (for example a USB or Bluetooth
  headset), and follows them if you switch devices mid-meeting. Everything else playing on that
  same device is recorded too; true per-app capture is Windows-only for now. At the start, and on
  every switch, it prints which device it is recording from.

## Status

Early version. The mixing, chunked writing and joining are covered by tests. The Windows
process-loopback capture still needs testing on more Windows machines. Run `test.bat` first,
because it starts a real one-second capture.

### Change log

**2026-11-19**

- **Linux bug fixed: meetings on a headset were recorded as silence.** The Linux capture used to
  record only the *default* output and the *default* microphone. A meeting played on a USB headset
  (Jabra Link 380) that was not the default was not captured at all: a 22-minute Spanish meeting
  came out at about -58 dB, and only the last words were left in the transcript. The earlier test
  passed because the sound then came from the laptop speakers, which were the default. Now the
  recorder follows the devices Chrome uses (`meetrec/sources/linux_pulse.py`).
  Tested: a tone played "as Chrome" on the Jabra, with the laptop speakers as the default, was
  recorded; a recording stream opened "as Chrome" on the Jabra mic was picked as the microphone.
  **Still to test in a real meeting.**
- **New: `meetrec transcribe`** (local Whisper, `transcribe.bat`). It reads our WAV files itself,
  because faster-whisper 1.2.1 cannot open files with PyAV 19 (`unexpected keyword argument
  'metadata_errors'`). It runs at lowest CPU priority on 2 cores by default, so the computer stays
  usable (`--threads` for more).
- **New: `meetrec translate`** (Claude through the `claude` command, `translate.bat`). Tested on a
  short Spanish sample into Persian; not yet run on a full meeting.

### How to test (checklist)

1. Join a meeting in Chrome, with the headset you normally use.
2. Start `record`. The first lines must name your headset:
   `system: recording from <headset>` and `mic: recording from <headset mic>`.
3. While someone talks, the `system` bar must move; while you talk, the `mic` bar must move.
   If the `system` bar stays at `....................`, the meeting is not being recorded.
4. After a few minutes, stop with Ctrl+C. Then run `transcribe ... --lang <language>`, and after
   that `translate ... --to <language>`.

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
| `--app msedge` | record Edge, `firefox` or a process id instead of Chrome (on Linux: follow that app's devices, e.g. `--app brave`) |
| `--all-system` | record all system audio instead of one app |
| `--no-mic` | do not record the microphone |
| `--mic 3` | choose a fixed microphone instead of the app's; list them with `python -m meetrec devices` |
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

### 1. Transcribe (local, free)

Runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your own computer. The
model (about 1.6 GB) is downloaded once; after that no internet is needed.

- Windows: drag the `.wav` onto **`transcribe.bat`**, or `transcribe.bat recordings\meeting-....wav --lang es`
- Linux: `.venv/bin/python -m meetrec transcribe recordings/meeting-....wav --lang es`

It writes `meeting-....txt` (one line per sentence, with `[hh:mm:ss]` timestamps) and
`meeting-....srt` (subtitles) next to the WAV.

| option | meaning |
|---|---|
| `--lang es` | spoken language (`en`, `fa`, `de`, ...). Leave out to detect it |
| `--model large-v3` | best quality but about 4x slower. Default `large-v3-turbo`; `medium`, `small` are faster |
| `--out folder` | where to write the files |
| `--threads 4` | CPU cores to use. Default 2, at lowest priority, so the computer stays usable |

With the default 2 cores, expect roughly as long as the meeting itself, or more.

### 2. Translate (Claude)

Uses the [Claude Code](https://claude.com/claude-code) command `claude`, with whatever login it
already has. The timestamps are kept, one translated line per original line.

- Windows: `translate.bat recordings\meeting-....txt --to English`
- Linux: `.venv/bin/python -m meetrec translate recordings/meeting-....txt --to Persian`

It writes `meeting-....english.txt` (or `.persian.txt`, ...). `--model opus` uses a stronger
model; `--chunk-lines` sets how many lines go to Claude per call (default 120).

## How it works

```
Chrome audio (process loopback) ─┐
                                 ├─► mixer (wall clock, 48 kHz) ─► 16 kHz ─► part files ─► meeting.wav
microphone (PortAudio) ──────────┘
```

| file | role |
|---|---|
| `meetrec/sources/win_process_loopback.py` | Windows per-process capture (`ActivateAudioInterfaceAsync`, pure ctypes) |
| `meetrec/sources/linux_pulse.py` | Linux capture (`parec`) that follows the app's output and microphone |
| `meetrec/sources/mic.py` | microphone capture (`sounddevice`) |
| `meetrec/mixer.py` | clock-driven mixing, silence filling, drift handling |
| `meetrec/resample.py` | 48 kHz to 16/24 kHz low-pass decimation |
| `meetrec/wavfiles.py` | crash-safe part files and joining |

## Consent

Recording people without telling them is illegal in many places. Tell everyone in the
meeting that you are recording.
