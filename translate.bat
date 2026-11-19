@echo off
rem Translates a transcript with Claude: translate.bat recordings\meeting-....txt --to English
cd /d "%~dp0"
.venv\Scripts\python -m meetrec translate %*
pause
