# 10 — Windows 上的 Artist 用戶端工具

先前的筆記把 client 一律裝在 WSL Ubuntu，那只是為了驗證 sandbox 通不通。
**實際流程中 artist 是在 Windows 桌面工作**，他們需要在 Windows 原生環境執行
`cuesubmit`（投 job）與 `cuegui`（監控），否則農場會出現
「節點能算圖，但 artist 無法在 Windows 端投 job」的斷層。

## 安裝

沿用 Windows 的 venv（Python 3.11.9）：

```bash
C:\Users\<user>\opencue-win-venv\Scripts\python.exe -m pip install \
    ./proto ./pycue ./pyoutline ./cuegui ./cuesubmit
```

實測結果：**安裝順利**，無錯誤。

拉進來的相依：

```
opencue_cuegui, opencue_cuesubmit, opencue_pyoutline
PySide6 6.5.3 (+Addons +Essentials)
Qt.py 2.0.7, nodegraphqt 0.6.43, types-PySide6
```

註：PySide6 是先前裝 CueNIMBY 時就帶進來的，版本 6.5.3。

## CueGUI 啟動實測

```powershell
$env:CUEBOT_HOSTS = "localhost"
Start-Process "C:\Users\<user>\opencue-win-venv\Scripts\cuegui.exe"
```

行程正常啟動且 `Responding: True`。stderr 只有兩行首次執行的正常訊息：

```
WARNING Layout  Local config file not found at C:/Users/<user>/AppData/Roaming/.cuecommander/config.ini
WARNING Layout  Copying ...\cuegui\config\cuecommander.ini to C:/Users/<user>/AppData/Roaming/.cuecommander/config.ini
```

CueGUI 的介面設定會落在 `%APPDATA%\.cuecommander\config.ini`（首次執行自動建立）。

**未完成**：視窗實際外觀、job 列表是否正確顯示、操作是否正常，
無法從命令列判斷，需要人工目視確認。

## Windows 用戶端如何指定遠端 Cuebot

`pycue/opencue/config.py` 的解析順序（優先度由高到低）：

1. 環境變數 `OPENCUE_CONFIG_FILE` 指向的檔案
2. 環境變數 `OPENCUE_CONF`（已棄用，保留相容）
3. 設定基底目錄下的 `opencue.yaml`
4. 套件內建的 `default.yaml`

**設定基底目錄是平台相關的**（`config.py:54-58`）：

```python
if platform.system() == 'Windows':
    return os.path.join(os.path.expandvars('%APPDATA%'), 'opencue')
return os.path.join(os.path.expanduser('~'), '.config', 'opencue')
```

所以 Windows 上的正確位置是 **`%APPDATA%\opencue\opencue.yaml`**。

設定內容（對照 `pycue/opencue/default.yaml`）：

```yaml
cuebot.facility_default: local
cuebot.facility:
    local:
        - linux-server.studio.local:8443
```

範本見 `notes/sandbox/stack/opencue-client.yaml`。

也可以用環境變數 `CUEBOT_HOSTS` 直接覆寫（本次測試用的方式），
但那需要每台機器設環境變數，不如發一份設定檔到 `%APPDATA%\opencue\` 乾淨。

### 注意：CueNIMBY 的設定路徑與 pycue 不一致

| 元件 | Windows 上的設定路徑 |
|---|---|
| pycue / cuegui / cuesubmit | `%APPDATA%\opencue\opencue.yaml` |
| CueNIMBY | `%USERPROFILE%\.config\opencue\cuenimby.json` |

CueNIMBY 用的是 Linux 慣例的 `~/.config`，**沒有做平台判斷**
（`cuenimby/config.py:59`）。所以在 Windows 上兩個元件的設定檔分散在兩個地方，
部署時容易漏掉其中一個。這也正是坑 #10（`mkdir` 缺 `parents=True`）的來源。

## DCC 軟體內建的 Submitter

實務上 artist 多半不是開獨立的 CueSubmit，而是在 Maya / Nuke 裡直接從選單送出。
repo 裡有現成的外掛，但位置與涵蓋範圍要先講清楚：

**路徑是 `cuesubmit/plugins/`，不是頂層的 `plugins/`**（頂層沒有這個目錄）。

```
cuesubmit/plugins/maya/
    CueMayaSubmit.py
    userSetup.py            <- Maya 啟動時自動載入
    opencue_logo_small.png
cuesubmit/plugins/nuke/
    CueNukeSubmit.py
    CueNukeSubmitLauncher.py
    menu.py                 <- Nuke 選單註冊
```

**只有 Maya 與 Nuke，沒有 Blender 外掛。** 若團隊用 Blender，
需要自行以 pyoutline 包裝，或走獨立的 CueSubmit / 命令列投 job。

這兩個外掛本次都未安裝測試。進到 artist 實機測試階段時應納入評估。

## 待驗證

> **注意**：本節寫於當時，部分項目後來已補測完成。
> **最新的驗證狀態以 `19-驗證狀態總表.md` 為準。**


| 項目 | 說明 |
|---|---|
| CueGUI 介面 | 需人工目視確認視窗、job 列表、操作 |
| CueSubmit | 尚未啟動測試 |
| 實際投 job | 從 Windows 的 CueSubmit 投一個真實算圖工作（Maya/Blender/Nuke） |
| 遠端 Cuebot | 目前用 localhost，未測真正跨機器的 `opencue.yaml` 設定 |
