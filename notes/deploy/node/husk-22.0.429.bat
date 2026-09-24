@echo off
REM ============================================================================
REM  OpenCue DCC wrapper - Houdini husk 22.0.429 (USD / Karma renderer)
REM  ASCII ONLY.
REM
REM  Usage from an OpenCue job:
REM      husk-22.0.429.bat <scene.usd> <output pattern with $F4>
REM
REM  The frame number comes from CUE_IFRAME, injected per frame by RQD, so the
REM  job command itself stays frame-agnostic.
REM
REM  husk renders a USD stage directly and does not need to open the .hip file,
REM  so it starts faster than a full hython session. Use it as stage 2 of a
REM  two-stage pipeline: stage 1 exports the USD, stage 2 renders it.
REM ============================================================================

REM EDIT: install location of this version on THIS machine.
set HFS=C:\Program Files\Side Effects Software\Houdini 22.0.429
set HB=%HFS%\bin

if not exist "%HB%\husk.exe" (
    echo [wrapper] husk not found at "%HB%\husk.exe" 1>&2
    exit /b 127
)

REM --- DCC license servers ---------------------------------------------------
REM set ADSKFLEX_LICENSE_FILE=@license-server.studio.local
REM set foundry_LICENSE=4101@license-server.studio.local
REM ---------------------------------------------------------------------------

set SCENE=%~1
set OUTPUT=%~2

if "%CUE_IFRAME%"=="" (
    echo [wrapper] CUE_IFRAME is not set 1>&2
    exit /b 2
)

echo [wrapper] husk 22.0.429 ^| frame %CUE_IFRAME% ^| scene %SCENE%
"%HB%\husk.exe" --make-output-path -f %CUE_IFRAME% -n 1 -o "%OUTPUT%" "%SCENE%"
exit /b %ERRORLEVEL%
