' Start OpenCue RQD (and CueNIMBY on workstations) without a console window.
'
' ASCII ONLY. Windows Script Host reads .vbs files in the ANSI code page.
' Chinese documentation: notes/deploy/02.
'
' Artist workstations: run this at user logon (logon-triggered scheduled task
' deployed by GPO, or the user's Startup folder). RQD and CueNIMBY must run in
' the user session; a Windows service runs in session 0 and cannot see user
' input or the user's mapped network drives.
'
' Dedicated render nodes: use a Windows service instead of this file.
'
' Running this file by hand was tested; starting it at logon was not.

CreateObject("Wscript.Shell").Run "C:\opencue\rqd-start.bat", 0, False
