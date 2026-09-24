@echo off
REM ============================================================================
REM  OpenCue DCC wrapper - Maya 2027 (Render.exe)
REM  ASCII ONLY.
REM
REM  Usage from an OpenCue job:
REM      maya-render-2027.bat <scene.ma> <output_dir> [renderer]
REM
REM  The frame number comes from CUE_IFRAME, injected per frame by RQD, so the
REM  job command itself stays frame-agnostic.
REM ============================================================================

REM EDIT: install location of this version on THIS machine.
set MAYA_ROOT=C:\Program Files\Autodesk\Maya2027
set MAYA_BIN=%MAYA_ROOT%\bin

if not exist "%MAYA_BIN%\Render.exe" (
    echo [wrapper] Render.exe not found at "%MAYA_BIN%\Render.exe" 1>&2
    exit /b 127
)


REM --- Crash reporter ---------------------------------------------------------
REM A crashing mayabatch.exe opens Autodesk's Customer Error Reporting dialog
REM (cer_dialog.exe) on the desktop. On a render node nobody answers it, and on
REM an artist workstation it pops up in front of the artist. Turn it off.
set MAYA_DISABLE_CER=1
REM ---------------------------------------------------------------------------

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

set SCENE=%~1
set OUTDIR=%~2
set RENDERER=%~3
if "%RENDERER%"=="" set RENDERER=sw

if "%CUE_IFRAME%"=="" (
    echo [wrapper] CUE_IFRAME is not set 1>&2
    exit /b 2
)

echo [wrapper] Maya 2027 ^| frame %CUE_IFRAME% ^| renderer %RENDERER%
"%MAYA_BIN%\Render.exe" -r %RENDERER% -s %CUE_IFRAME% -e %CUE_IFRAME% -rd "%OUTDIR%" "%SCENE%"
exit /b %ERRORLEVEL%
