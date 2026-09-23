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

set MAYA_ROOT=D:\programs\Autodesk\Maya2027
set MAYA_BIN=%MAYA_ROOT%\bin

if not exist "%MAYA_BIN%\Render.exe" (
    echo [wrapper] Render.exe not found at "%MAYA_BIN%\Render.exe" 1>&2
    exit /b 127
)

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
