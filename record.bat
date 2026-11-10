@echo off
rem Records Chrome + microphone into recordings\. Extra options pass through, e.g.:
rem   record.bat --app msedge
rem   record.bat --all-system
cd /d "%~dp0"
.venv\Scripts\python -m meetrec record %*
pause
