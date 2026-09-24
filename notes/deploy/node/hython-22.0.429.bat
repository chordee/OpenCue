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

REM EDIT: install location of this version on THIS machine.
set HFS=C:\Program Files\Side Effects Software\Houdini 22.0.429
set HB=%HFS%\bin

if not exist "%HB%\hython.exe" (
    echo [wrapper] hython not found at "%HB%\hython.exe" 1>&2
    exit /b 127
)

"%HB%\hython.exe" %*
exit /b %ERRORLEVEL%
