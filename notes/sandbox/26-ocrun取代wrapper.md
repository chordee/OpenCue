# 26 — 以 `ocrun` 取代 DCC wrapper

正式做法整理在 [`notes/deploy/02-算圖節點.md` 第五節](../deploy/02-算圖節點.md#五呼叫-dccocrun)，本篇是動機、設計與實測紀錄。

---

## 一、動機

原本每個 DCC 版本在每台節點上都有一支 `.bat`（`C:\opencue\bin\hython-22.0.429.bat` 等）：

- 每新增一個版本就要多一支檔案，每台機器都要改其中的安裝路徑
- 加入 Linux 節點時，每支都要再寫一份 shell 版本
- 參數格式有兩種：`maya-render-2027.bat` 吃自訂參數（場景、輸出目錄、算圖器），
  `Render-2027.bat` 則原封不動轉給 `Render.exe`，名稱相近、容易混淆

wrapper 實際做的只有三件事：查出本機的安裝位置、設定環境變數、轉交參數。
這些用 Python 寫一份，就能在 Windows 與 Linux 共用。

---

## 二、設計

```
ocrun <產品> <版本> <程式> [參數...]
ocrun maya 2027 Render -r file -s #IFRAME# -e #IFRAME# P:/proj/scene.ma
```

| 部分 | 放在哪 | 每台是否不同 |
|---|---|---|
| 查詢與執行邏輯 | [`node/ocrun/ocrun.py`](../deploy/node/ocrun/ocrun.py)，以 pip 安裝進 venv | 相同 |
| 各 DCC 共通的環境（`MAYA_DISABLE_CER`、`TEMP`、`NUKE_DISK_CACHE`） | `ocrun.py` | 相同 |
| 版本 → 安裝目錄、授權伺服器 | `dcc.toml`（範本 [`node/dcc-windows.toml`](../deploy/node/dcc-windows.toml)） | 不同 |

幾個決定：

- **frame 編號改用 Cuebot 的 token**：舊 wrapper 自己讀 `CUE_IFRAME` 再組參數，
  所以每個 DCC 要寫一套參數格式。Cuebot 派工時會把指令中的 `#IFRAME#` 換成 frame 編號
  （`DispatchSupportService.java:718`），`ocrun` 因此不需要懂任何 DCC 的參數，一律原封轉交
- **frame 找得到 `ocrun` 的原因**：`rqd.conf` 設定 `RQD_USE_PATH_ENV_VAR = 1` 時，
  frame 的 PATH 就是 RQD 的 PATH（`rqmachine.py:571`）。`rqd-start.bat` 在 PATH 加上 venv 的 `Scripts`，
  job 指令就能直接寫 `ocrun`，不必寫 `C:\...` 這種只在 Windows 成立的路徑
- **設定檔位置**：Windows 是 `C:\opencue\dcc.toml`，Linux 是 `/opt/opencue/dcc.toml`；
  可用環境變數 `OPENCUE_DCC_CONFIG` 覆寫（可以放在 job 的環境變數裡）
- **只用標準函式庫**：`tomllib` 從 Python 3.11 起內建，不需額外套件
- **找不到版本或程式時以 exit 127 結束**，並在 frame log 寫明原因。不帶參數執行時列出本機設定

與舊 wrapper 的對照：

| 舊 wrapper | `ocrun` |
|---|---|
| `hython-22.0.429.bat script.py` | `ocrun houdini 22.0.429 hython script.py` |
| `husk-22.0.429.bat scene.usd out.$F4.exr` | `ocrun houdini 22.0.429 husk --make-output-path -f #IFRAME# -n 1 -o out.$F4.exr scene.usd` |
| `maya-render-2027.bat scene.ma outdir sw` | `ocrun maya 2027 Render -r sw -s #IFRAME# -e #IFRAME# -rd outdir scene.ma` |
| `Render-2027.bat -r file ...`（從 Maya 投遞） | `ocrun maya 2027 Render -r file ...` |
| `nuke-17.0v1.bat script.py` | `ocrun nuke 17.0v1 Nuke17.0 -t script.py` |

---

## 三、實測（2026-09-25）

### 1. 單元測試

[`node/ocrun/test_ocrun.py`](../deploy/node/ocrun/test_ocrun.py) 涵蓋：回傳 exit code、環境變數、
含空白的參數、版本或程式不存在、安裝後的 entry point。

| 環境 | 結果 |
|---|---|
| Windows venv（Python 3.11.9） | 5 項通過 |
| Linux 容器（`python:3.11-slim`），`pip install` 後執行 | 5 項通過，`ocrun` 安裝在 `/usr/local/bin/ocrun` |

### 2. 直接執行

```
> ocrun
configured in C:\opencue\dcc.toml:
  maya 2027  D:\programs\Autodesk\Maya2027\bin
  houdini 22.0.429  D:\programs\Side Effects Software\Houdini 22.0.429\bin
  nuke 17.0v1  D:\programs\Nuke17.0v1

> ocrun houdini 22.0.429 hython -c "import hou; print(hou.applicationVersionString())"
22.0.429
```

安裝路徑含空白（`Side Effects Software`）沒有問題。

### 3. 經 RQD 算圖

以 [`lab/submit_dcc.py`](lab/submit_dcc.py) 與 [`lab/submit_houdini_twostage.py`](lab/submit_houdini_twostage.py) 投遞（已改用 `ocrun`）：

| job | 程式 | frame | 結果 |
|---|---|---|---|
| `houdini_render_22_0_429` | hython（Karma） | 1-2 | 全部 SUCCEEDED |
| `maya_render_2027` | Render（`-r sw`） | 1-2 | 全部 SUCCEEDED |
| `nuke_render_17_0v1` | Nuke17.0 `-t` | 1-2 | 全部 SUCCEEDED |
| `houdini_twostage` | hython 匯出 USD → husk | 1 + 2 | 全部 SUCCEEDED |

全部 exit 0、沒有重試，輸出檔都有更新。frame log 的第一行由 `ocrun` 印出，`#IFRAME#` 已被替換：

```
[ocrun] maya 2027: D:\programs\Autodesk\Maya2027\bin\Render.EXE -r sw -s 2 -e 2 -rd C:/opencue/render/maya C:/opencue/scenes/test.ma
[ocrun] houdini 22.0.429: D:\programs\Side Effects Software\Houdini 22.0.429\bin\husk.EXE --make-output-path -f 1 -n 1 -o C:/opencue/render/twostage.$F4.exr C:/opencue/render/twostage.usda
```

Nuke 沒有另外設定 `NUKE_DISK_CACHE` 也成功，確認 `ocrun` 補上的 `TEMP` 與快取目錄有效
（沒有這兩個變數時的失敗見 [`17` 場景 7](17-故障排查與常見疏失速查.md#場景-7nuke-算圖全面失敗報-unable-to-create-disk-cache)）。

### 4. 從 Maya 投遞

投遞工具的指令改為 `ocrun maya <版本> Render`（[`client/maya/opencue_maya_submit.py`](../deploy/client/maya/opencue_maya_submit.py)），
以程式操作投遞介面送出（方法同 [`25` 第四節](25-Maya內投遞.md#四實測)）：

```
built : ocrun maya 2027 Render -r file -s #FRAME_START# -e #FRAME_END# -cam renderCam1 C:/opencue/scenes/test.ma
```

CueSubmit 會用空白切開指令，`ocrun maya 2027 Render` 本來就是四個參數，不受影響。2 個 frame 全部成功。

### 5. 砍 frame

投遞一個執行 600 秒的 hython frame，執行中砍掉 job：

| 時間點 | `ocrun.exe` | `hython.exe` |
|---|---|---|
| 執行中 | 1 | 1 |
| 砍掉後 15 秒 | 0 | 0 |

RQD 在 Windows 以 `taskkill /F /T /PID` 結束整個程序樹（`rqnetwork.py:172`），
中間多一層 `ocrun` 不會留下孤兒程序。

第一次砍的時候 job 沒有任何反應：`job.kill()` 沒有附理由，Cuebot 在 log 記下
`**Invalid Job Kill Request**` 後就不處理了，但回傳給呼叫端的是成功。附上 `reason` 後正常。
見 [`17` 場景 26](17-故障排查與常見疏失速查.md#場景-26用-api-砍-job沒有錯誤但-job-繼續跑)。

### 6. 含空白的參數

指令 `["ocrun", "houdini", "22.0.429", "hython", '"C:/opencue/tmp/a b/t.py"', '"x y"']`，
腳本收到的 `sys.argv`：

```
['C:/opencue/tmp/a b/t.py', 'x y']
```

加上雙引號的參數經過 RQD 的 `.bat`、`ocrun` 後完整傳到 DCC，外層引號已去掉。
沒加引號時仍會被切開，規則與先前相同（[`17` 場景 24](17-故障排查與常見疏失速查.md#場景-24路徑含空白時-frame-失敗)）。

---

## 四、加入 Linux 節點時還要做的事

`ocrun` 與 job 指令已經不分平台，Linux 節點上需要：

- venv 安裝 RQD 與 `ocrun`，設定檔放在 `/opt/opencue/dcc.toml`
- RQD 的啟動方式（systemd），同樣要把 venv 的 `bin` 加進 PATH，並設定 `RQD_USE_PATH_ENV_VAR = 1`
- `TZ` 的處理與 Windows 不同：Linux 上空的 `TZ` 代表 UTC，見 [`29`](29-frame的時區.md)

以下是換成 Python 也不會自動解決的，**都還沒做**：

| 項目 | 說明 |
|---|---|
| 磁碟機代號 | Linux 沒有 `P:\`。指令中的路徑可以由 `ocrun` 轉換；場景檔內部引用的路徑要靠各 DCC 的機制（Maya dirmap、`HOUDINI_PATHMAP`、Nuke filename filter） |
| 派工 | Cuebot 會比對 job 與節點的 OS（`DispatchQuery.java` 的 `str_os`）。目前的投遞規則是指定 `os="Windows"`（[`deploy/03` 第九節](../deploy/03-工作站.md#九投遞-job-時要注意的事)） |
| frame log 位置 | 混合 OS 要分別設定 log 根目錄（[`17` 場景 21](17-故障排查與常見疏失速查.md#場景-21混合作業系統農場中job-成功但-log-找不到)） |
| DCC 本身 | Linux 版的 DCC、外掛與授權要逐一確認 |

---

## 五、尚未驗證

- **在「DCC 裝在不同路徑」的第二台機器上使用**：本機只有一台 Windows 節點
- **實際的 Linux 算圖節點**：只在容器中驗證了 `ocrun` 本身，沒有 DCC
- `MAYA_DISABLE_CER` 對 Maya 本體當機的效果。授權模組的回報視窗它關不掉，見 [`28`](28-Maya結束時跳出錯誤回報.md)
