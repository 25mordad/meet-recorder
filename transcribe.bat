@echo off
rem Transcribes a recording. Drag a .wav onto this file, or: transcribe.bat recordings\meeting-....wav --lang es
cd /d "%~dp0"
.venv\Scripts\python -m meetrec transcribe %*
pause
