@echo off
REM ============================================================================
REM  OpenCue render node startup wrapper (Windows)
REM
REM  ASCII ONLY. cmd.exe parses .bat files using the OEM code page (e.g. CP950),
REM  so non-ASCII comments become mojibake and can break parsing.
REM  Chinese documentation for this file lives in notes/sandbox/08 and 09.
REM
REM  Purpose:
REM    1. Fix the working directory, so Linux-style paths handed down by Cuebot
REM       do not resolve against whichever drive happened to be current.
REM    2. Provide a clean environment, instead of inheriting a developer shell
REM       PATH which can shadow Windows built-ins.
REM    3. Start CueNIMBY alongside RQD on artist workstations, in the right
REM       order.
REM
REM  Launch this from a logon-triggered scheduled task or the Startup folder.
REM  Artist workstations must use logon triggers, not a Windows service:
REM  NIMBY and CueNIMBY both need to run inside the user session.
REM  Dedicated render nodes should use a Windows service instead.
REM ============================================================================

setlocal

set OPENCUE_HOME=C:\opencue
set OPENCUE_VENV=C:\Users\chordee\opencue-win-venv

REM Node role: workstation = artist machine, needs CueNIMBY scheduling
REM            render      = dedicated render node, no CueNIMBY
set NODE_ROLE=workstation

cd /d "%OPENCUE_HOME%"
set RQD_CONFIG_FILE=%OPENCUE_HOME%\rqd.conf

REM RQD must come up FIRST. Locking a host is performed by Cuebot calling back
REM into RQD on port 8444, so CueNIMBY cannot apply its schedule until RQD is
REM registered and listening. Starting CueNIMBY first yields
REM "RqdClientException: failed to lock host".
start "OpenCue RQD" /B "%OPENCUE_VENV%\Scripts\rqd.exe" >> "%OPENCUE_HOME%\rqd-service.log" 2>&1

if /I "%NODE_ROLE%"=="workstation" (
    REM Wait for RQD to register with Cuebot before CueNIMBY tries to lock.
    REM ping is used rather than timeout, because timeout fails when stdin is
    REM redirected, which is the case under a scheduled task.
    ping -n 21 127.0.0.1 > nul
    start "CueNIMBY" /B "%OPENCUE_VENV%\Scripts\cuenimby.exe" >> "%OPENCUE_HOME%\cuenimby.log" 2>&1
)

endlocal
