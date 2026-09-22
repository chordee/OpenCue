' 隱藏視窗啟動 OpenCue RQD 的範本。
'
' 用途：讓 RQD 在使用者登入時自動啟動，且不留一個 console 視窗給 artist。
'
' 安裝方式（需使用者自行放置，本次未自動安裝）：
'   複製到 %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
'
' 為什麼用啟動資料夾而非 Windows 服務：
'   RQD 必須跑在使用者 session，NIMBY 才偵測得到鍵鼠活動。
'   系統服務跑在 session 0，看不到使用者輸入，NIMBY 會失效。
'
' 正式大規模部署時，IT 應改用 GPO 派送「登入時觸發」的排程工作，
' 而不是逐台放啟動資料夾。

CreateObject("Wscript.Shell").Run "C:\opencue\rqd-start.bat", 0, False
