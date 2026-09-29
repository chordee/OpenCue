@echo off
REM Submit a USD file to OpenCue for husk: drop the file on this script, or run
REM     opencue_husk_submit.bat P:\projects\show\usd\shot.usd
REM The console stays open so errors can be read.
"C:\opencue\venv\Scripts\python.exe" "%~dp0opencue_husk_submit.py" %*
if errorlevel 1 pause
