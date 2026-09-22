@echo off
REM OpenCue RQD 啟動包裝（Windows render node / artist 工作站）
REM
REM 目的：
REM   1. 固定工作目錄 —— 避免 Linux 風格路徑被解析到不同磁碟機（見 notes 08 坑 #7）
REM   2. 乾淨環境 —— 不要從開發者 shell 繼承 PATH（見 notes 08 坑 #8）
REM
REM 由排程工作在「使用者登入時」呼叫。
REM 注意：artist 工作站要用排程工作而非 Windows 服務，因為 NIMBY 需要偵測
REM       鍵鼠活動，而系統服務跑在 session 0 看不到使用者輸入。

cd /d C:\opencue

set RQD_CONFIG_FILE=C:\opencue\rqd.conf

"C:\Users\chordee\opencue-win-venv\Scripts\rqd.exe" >> C:\opencue\rqd-service.log 2>&1
