@echo off
REM ============================================================================
REM  OpenCue DCC wrapper - Houdini 22.0.429
REM
REM  ASCII ONLY (cmd.exe parses .bat in the OEM code page).
REM
REM  Every render node keeps its wrappers at the SAME path:
REM      C:\opencue\bin\hython-<version>.bat
REM  but each file points at wherever that version happens to live on that
REM  machine. Job commands therefore never contain a machine-specific install
REM  path, and several DCC versions can coexist on one node.
REM
REM  A node only has wrapper files for the versions it actually has installed,
REM  and advertises those versions through RQD_TAGS. Layer tags then keep a job
REM  away from nodes that cannot run it.
REM ============================================================================

set HFS=D:\programs\Side Effects Software\Houdini 22.0.429
set HB=%HFS%\bin

if not exist "%HB%\hython.exe" (
    echo [wrapper] hython not found at "%HB%\hython.exe" 1>&2
    exit /b 127
)

"%HB%\hython.exe" %*
exit /b %ERRORLEVEL%
