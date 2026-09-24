@echo off
REM ============================================================================
REM  OpenCue DCC wrapper - Maya 2027 Render.exe, pass-through
REM  ASCII ONLY.
REM
REM  Used by the in-Maya submitter (CueSubmit). CueSubmit builds the command
REM      Render -r file -s <start> -e <end> [-cam <camera>] <scene>
REM  and this wrapper forwards every argument unchanged, so it can stand in
REM  for Render.exe. Scripted jobs use maya-render-2027.bat instead.
REM
REM  CueSubmit splits its command on spaces, so neither this path nor the
REM  scene path may contain spaces.
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
REM RQD does NOT inherit the interactive user's environment. Uncomment and
REM point at the studio license server before using Arnold / MtoA.
REM
REM set ADSKFLEX_LICENSE_FILE=@license-server.studio.local
REM set solidangle_LICENSE=5053@license-server.studio.local
REM ---------------------------------------------------------------------------

echo [wrapper] Maya 2027 Render.exe %*
"%MAYA_BIN%\Render.exe" %*
exit /b %ERRORLEVEL%
