@echo off
REM ============================================================================
REM  OpenCue DCC wrapper - Nuke 17.0v1
REM  ASCII ONLY.
REM
REM  Usage from an OpenCue job:
REM      nuke-17.0v1.bat <python_script.py>
REM
REM  -t runs Nuke in terminal (python) mode. The script reads CUE_IFRAME to
REM  decide which frame to render.
REM ============================================================================

REM EDIT: install location of this version on THIS machine.
set NUKE_ROOT=C:\Program Files\Nuke17.0v1
set NUKE_EXE=%NUKE_ROOT%\Nuke17.0.exe

if not exist "%NUKE_EXE%" (
    echo [wrapper] Nuke not found at "%NUKE_EXE%" 1>&2
    exit /b 127
)

REM Nuke needs a writable disk cache. Without NUKE_DISK_CACHE it derives a path
REM from the environment and falls back to C:\temp\nuke, which does not exist
REM on a render node, so every frame fails with
REM     ERROR: Unable to create disk cache at C:/temp/nuke.

REM --- DCC license servers ---------------------------------------------------
REM RQD does NOT inherit the interactive user's environment (see notes 12,
REM trap #14: it passes TMP but not TEMP). Anything the renderer needs must be
REM set here explicitly, license servers included. Uncomment and point at the
REM studio license server before using Arnold, MtoA or batch Nuke.
REM
REM set ADSKFLEX_LICENSE_FILE=@license-server.studio.local
REM set foundry_LICENSE=4101@license-server.studio.local
REM set solidangle_LICENSE=5053@license-server.studio.local
REM ---------------------------------------------------------------------------

if "%NUKE_DISK_CACHE%"=="" set NUKE_DISK_CACHE=C:\opencue\tmp\nuke
if not exist "%NUKE_DISK_CACHE%" mkdir "%NUKE_DISK_CACHE%"

echo [wrapper] Nuke 17.0v1 ^| frame %CUE_IFRAME% ^| cache %NUKE_DISK_CACHE%
"%NUKE_EXE%" -t %*
exit /b %ERRORLEVEL%
