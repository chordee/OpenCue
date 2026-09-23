# 12 — 真實 DCC 算圖測試（Houdini / Maya / Nuke）

先前的測試都是 `/bin/sleep` 或簡單的 Python 腳本。這一份用**真正的算圖軟體**
跑完整流程，一次驗證多項先前只能紙上談兵的事。

## 本機的 DCC 環境

偵測時注意：**預設位置找不到，實際裝在 D 槽**。
`houdini-locator` 的偵測腳本只掃 `C:\Program Files\Side Effects Software\`，
而 `HFS` 環境變數未設定，所以自動偵測失敗。

| 軟體 | 路徑 | 可用執行檔 |
|---|---|---|
| Houdini 22.0.429（另有 21.0.700 / 21.0.729 / 22.0.368） | `D:\programs\Side Effects Software\` | `hython.exe` `husk.exe` `hbatch.exe` |
| Maya 2027 | `D:\programs\Autodesk\Maya2027\bin\` | `Render.exe` |
| Nuke 17.0v1（另有 16.0v8） | `D:\programs\Nuke17.0v1\` | `Nuke17.0.exe` |
| Blender 4.4 / 4.5 / 5.0 | `D:\programs\Blender Foundation\` | **找不到 `blender.exe`**，只有版本資料夾 |

Houdini 授權：`licenseCategoryType.Commercial`，Python 3.13.10。

## 算圖器測試：哪些能用

| 算圖器 | 結果 | 說明 |
|---|---|---|
| **Karma**（`karma` ROP） | ✅ 5.8 秒 / 215 KB EXR | 行程內執行，log 顯示內部委派給 `rop_usdrender` |
| **husk**（獨立 USD 算圖） | ✅ exit 0 / 916 KB EXR | 需先以 `usd_rop` 匯出 USD |
| **OpenGL ROP** | ✅ 5.6 KB PNG | 視埠算圖，最快，適合做連線測試 |
| **Mantra**（`ifd` ROP） | ❌ **授權失敗** | `No licenses could be found to run this application` |

**Mantra 需要獨立的 render 授權**（它會另起 `mantra` 行程索取 render token），
Houdini 的 Commercial 授權不涵蓋。Karma 則是在 hython 行程內執行，
沿用已持有的授權，所以可用。

**結論**：這個環境的算圖主力是 Karma / husk。

## 設計：多版本 DCC 與不同安裝路徑

正式環境的兩個前提：

- 各台機器的 DCC 安裝位置**不一定相同**
- 同一台機器上**可能並存多個版本**（Houdini 21 / 22、Maya 2026 / 2027…）
- 不同專案會**指定不同版本**算圖

所以 **job 指令絕不能寫死安裝路徑**。做法是三層：

### 第 1 層：每台節點放相同路徑的包裝腳本

```
C:\opencue\bin\hython-22.0.429.bat
C:\opencue\bin\hython-21.0.729.bat
C:\opencue\bin\Render-2027.bat        (Maya，尚未建立)
```

路徑固定，但**內容各自指向本機的實際安裝位置**：

```bat
set HFS=D:\programs\Side Effects Software\Houdini 22.0.429
set HB=%HFS%\bin
if not exist "%HB%\hython.exe" (
    echo [wrapper] hython not found at "%HB%\hython.exe" 1>&2
    exit /b 127
)
"%HB%\hython.exe" %*
exit /b %ERRORLEVEL%
```

範本見 `stack/hython-22.0.429.bat`。**必須是純 ASCII**（見 `09` 坑 #13）。

一台節點只會有它真正裝了的版本的包裝腳本。找不到執行檔時明確回傳 127，
而不是靜默失敗。

### 第 2 層：節點廣告自己有哪些版本

`rqd.conf`：

```ini
RQD_TAGS = general houdini22 houdini_22_0_429
```

以空白分隔（`rqmachine.py:599` 是 `.split()`）。

命名慣例建議給兩種粒度，讓專案自行選擇鬆綁定或嚴格綁定：

| 形式 | 用途 |
|---|---|
| `houdini22` | 專案只要求大版本相容 |
| `houdini_22_0_429` | 專案鎖定確切建置版本 |

實測註冊結果：

```
str_tag          | str_tag_type
general          | HARDWARE
houdini22        | HARDWARE
houdini_22_0_429 | HARDWARE
desktop          | ALLOC
windows          | HARDWARE
```

### 第 3 層：job 用 layer tag 要求版本

```python
layer = Shell(
    "houdini_render",
    command=[wrapper, script],          # 串列，不是字串
    range="1-4",
    tags=["general", "houdini_22_0_429"],
    env={"OPENCUE_RENDER_OUT": out, "OPENCUE_RENDERER": "karma"},
)
```

Cuebot 只會把工作派給同時帶有 `general` 與 `houdini_22_0_429` 標籤的節點。
沒裝該版本的機器不會拿到這個 job。

### 為什麼指令要用「串列」

`pyoutline/outline/io.py:53` 的 `prep_shell_command()`：

```python
if not isinstance(cmd, (tuple, list, set)):
    cmd = shlex.split(str(cmd))
```

字串會經過 `shlex.split()`，而 POSIX 模式下反斜線被當成跳脫字元吃掉 ——
Windows 路徑會被破壞。傳串列就完全繞過。

投遞腳本見 `stack/submit_houdini.py`。

## 算圖腳本

`stack/houdini_render_frame.py`，重點設計：

- **frame 編號取自環境變數 `CUE_IFRAME`**，不依賴指令字串代換。
  RQD 會為每個 frame 注入這個變數，比 `%{FRAME}` 代換更穩。
- 算圖器由 `OPENCUE_RENDERER` 選擇（`karma` / `opengl`）
- 輸出目錄由 `OPENCUE_RENDER_OUT` 指定
- 結束時檢查輸出檔是否存在，不存在就 `sys.exit(1)` ——
  **讓 Cuebot 知道 frame 失敗**，而不是回報成功卻沒有產出

## 實測結果

```bash
python submit_houdini.py --frames 1-4
```

```
job      : houdini_render_22_0_429
frames   : 1-4
tags     : ['general', 'houdini_22_0_429']
command  : ['C:/opencue/bin/hython-22.0.429.bat',
            'C:/opencue/scripts/houdini_render_frame.py']
renderer : karma
```

Cuebot 端：

```
                       job                        |      str_name       | str_state | exit
--------------------------------------------------+---------------------+-----------+------
 testing-testshot-chordee_houdini_render_22_0_429 | 0001-houdini_render | SUCCEEDED |  0
 testing-testshot-chordee_houdini_render_22_0_429 | 0002-houdini_render | SUCCEEDED |  0
 testing-testshot-chordee_houdini_render_22_0_429 | 0003-houdini_render | SUCCEEDED |  0
 testing-testshot-chordee_houdini_render_22_0_429 | 0004-houdini_render | SUCCEEDED |  0
```

實際產出（檔案大小遞增，因為 torus 隨 frame 旋轉，入鏡幾何量不同）：

```
test.0001.exr  250342
test.0002.exr  313549
test.0003.exr  370631
test.0004.exr  419045
```

frame log 確認環境正確傳遞：

```
Houdini      : 22.0.429
License      : licenseCategoryType.Commercial
Frame        : 1
CUE_JOB      : testing-testshot-chordee_houdini_render_22_0_429
Renderer     : karma
```

**完整鏈路打通**：Linux 容器內的 Cuebot → 依 tag 選中 Windows 節點 →
包裝腳本解析本機 Houdini 路徑 → Karma 算圖 → 寫出 EXR → 回報成功。

## 測試過程的插曲：CueNIMBY 會擋住測試

投 job 時是 11:47，落在 `09:00-18:00 disabled` 的排程內，主機被鎖定，
job 不會被派工 —— 這正是先前驗證過的正確行為。

測試時需暫停 CueNIMBY 並解鎖：

```powershell
Stop-Process -Name cuenimby -Force
```
```bash
cueadmin -force -unlock -host <節點名稱>
```

測完記得重新啟動 CueNIMBY 恢復排程。

**正式環境的意涵**：白天要測農場時，得先確認測試用的節點不在封鎖時段內，
或另外準備不受排程管制的專職算圖機。

## 尚未驗證

| 項目 | 說明 |
|---|---|
| Maya `Render.exe` | 已確認執行檔存在，未做算圖測試 |
| Nuke | 同上，且需確認授權型態 |
| Blender | 找不到執行檔，無法測試 |
| 多版本並存的實際派工 | 目前只註冊了一個版本的 tag。需要第二個版本才能驗證「job 只去到對的節點」 |
| 共享儲存 | 輸出寫在本機 `C:\opencue\render`，未測 UNC 路徑 |
| 大量 frame 的穩定性 | 只跑了 4 個 frame |
| husk 走農場 | husk 單獨測過，但未包成 OpenCue job |

---

# 續篇：Maya 與 Nuke

## 測試結果

三套 DCC 都能在農場上無頭算圖。

| 軟體 | 執行方式 | 結果 |
|---|---|---|
| Houdini 22.0.429 | `hython.exe` + Karma ROP | ✅ 4/4 frame，記憶體約 1.1 GB |
| Maya 2027 | `Render.exe -r sw` | ✅ 3/3 frame，記憶體約 530 MB |
| Nuke 17.0v1 | `Nuke17.0.exe -t` | ✅ 3/3 frame（修正環境後） |

**記憶體回報在真實負載下正確**（先前只用 sleep 測，數值都是 0）：

```
 job                           | frame               | state     | exit | mem_kb
-------------------------------+---------------------+-----------+------+---------
 ..._houdini_render_22_0_429   | 0001-houdini_render | SUCCEEDED |    0 | 1145644
 ..._maya_render_2027          | 0001-maya_render    | SUCCEEDED |    0 |  530644
 ..._nuke_render_17_0v1        | 0001-nuke_render    | SUCCEEDED |    0 |       0
```

Nuke 是 0，因為每個 frame 只跑 0.05 秒，在 10 秒的採樣間隔之間就結束了
（見 `08` 的說明）。**不是故障。**

## Maya

場景以 `mayapy.exe` 產生（`stack/make_maya_scene.py` 的做法，本次直接寫在
`C:\opencue\scripts\`），算圖用 `Render.exe`：

```bat
Render.exe -r sw -s %CUE_IFRAME% -e %CUE_IFRAME% -rd "%OUTDIR%" "%SCENE%"
```

包裝腳本 `stack/maya-render-2027.bat` 的關鍵設計：**frame 由 `CUE_IFRAME`
環境變數傳入**，所以 job 指令本身與 frame 無關，不需要字串代換。

`-r sw`（Maya Software）不需要額外授權。Arnold 需要 MtoA 授權，未測試。

單 frame 約 18.5 秒，其中大部分是 Maya 啟動開銷 —— 這對短 frame 的工作
是很大的比例，正式環境可考慮用 `mayabatch` 或一次算多個 frame 來攤平。

## Nuke

```bat
Nuke17.0.exe -t <python_script.py>
```

`-t` 是 terminal（Python）模式。腳本同樣讀 `CUE_IFRAME` 決定算哪一格。

### 坑 #14：DCC 依賴的環境變數，RQD 不一定會提供

Nuke 在農場上**全部失敗**，但同一個包裝腳本手動執行卻成功：

```
ERROR: Unable to create disk cache at C:/temp/nuke.
Please modify the value of DiskCachePath in the preferences17.0.nk file
```

**根因**：RQD 傳給 frame 的環境變數裡**有 `TMP` 但沒有 `TEMP`**。

實際傳下去的變數（從 frame log 的 env 區塊取得）：

```
APPDATA COMMONPROGRAMFILES CUE3 CUE_CHUNK CUE_FRAME CUE_FRAME_ID CUE_GPUS
CUE_GPU_MEMORY CUE_IFRAME CUE_JOB CUE_JOB_ID CUE_LAYER CUE_LAYER_ID
CUE_LOG_PATH CUE_MEMORY CUE_RANGE CUE_SHOT CUE_SHOW CUE_THREADABLE CUE_THREADS
CUE_USER LOGNAME PATH SP_NOMYCSHRC SYSTEMDRIVE SYSTEMROOT TERM TMP TZ USER
frame jobhost jobid logfile maxframetime mcp minspace shot show zframe
```

Windows 應用程式普遍讀 `TEMP`，Nuke 找不到就退回寫死的 `C:/temp`，
而 render node 上不存在該目錄 → 每個 frame 都失敗。

**這個模式會反覆出現**：DCC 需要的環境（暫存目錄、快取路徑、授權伺服器、
模組搜尋路徑）不會自動出現在 frame 環境裡。
**每個包裝腳本都應該明確設定它需要的環境**，不要假設繼承得到。

修法（`stack/nuke-17.0v1.bat`）：

```bat
if "%NUKE_DISK_CACHE%"=="" set NUKE_DISK_CACHE=C:\opencue\tmp\nuke
if not exist "%NUKE_DISK_CACHE%" mkdir "%NUKE_DISK_CACHE%"
```

修正後重試（`cueman -force -retry <job>`）：3/3 SUCCEEDED。

### 坑 #15：PATH 污染其實一直沒解決

追查 Nuke 問題時順便檢查了 frame 的 `PATH`，發現：

```
PATH=C:\Program Files\Git\mingw64\bin;C:\Program Files\Git\usr\bin;...
```

**坑 #8 根本沒被修掉。** 先前確認的是「**持久** PATH 乾淨」，
但實際啟動 RQD 的那個工作階段本身就帶著污染的 PATH，
而包裝腳本沒有重設它 —— RQD 照單全收並傳給每個 frame。

這是個容易自我欺騙的檢查：看環境變數設定是乾淨的，不代表**執行中的行程**
拿到的是乾淨的。**要驗證就去看 frame log 裡實際的 `env PATH=`。**

修法（`stack/rqd-start.bat`）—— 不繼承，直接指定：

```bat
set PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem
set PATH=%PATH%;%SystemRoot%\System32\WindowsPowerShell\v1.0

if not exist "%OPENCUE_HOME%\tmp" mkdir "%OPENCUE_HOME%\tmp"
set TEMP=%OPENCUE_HOME%\tmp
set TMP=%OPENCUE_HOME%\tmp
```

修正後 frame log 確認：

```
PATH=C:\WINDOWS\system32;C:\WINDOWS;C:\WINDOWS\System32\Wbem;C:\WINDOWS\System32\WindowsPowerShell\...
```

**正式環境的原則**：render node 的環境要由啟動腳本**明確定義**，
而不是繼承自「剛好是誰啟動了它」。否則同一個 job 在不同機器、
甚至同一台機器的不同次啟動，行為都可能不同。

## 完整的 DCC 包裝腳本清單

每台節點放在相同路徑 `C:\opencue\bin\`，內容各自指向本機安裝位置：

| 檔案 | 對應版本 | 用法 |
|---|---|---|
| `hython-22.0.429.bat` | Houdini 22.0.429 | `hython-22.0.429.bat <script.py>` |
| `maya-render-2027.bat` | Maya 2027 | `maya-render-2027.bat <scene.ma> <outdir> [renderer]` |
| `nuke-17.0v1.bat` | Nuke 17.0v1 | `nuke-17.0v1.bat <script.py>` |

節點的 `RQD_TAGS`：

```ini
RQD_TAGS = general houdini22 houdini_22_0_429 maya2027 maya_2027 nuke17 nuke_17_0v1
```

投遞腳本 `stack/submit_dcc.py` 內含三者的 preset，用法：

```bash
python submit_dcc.py houdini --frames 1-4
python submit_dcc.py maya    --frames 1-3
python submit_dcc.py nuke    --frames 1-3
```

---

# 補充：授權伺服器與 husk 兩階段派工

## DCC 授權環境變數要寫進包裝腳本

本次測試用的都是不需要浮動授權的組合：

- Maya Software（`-r sw`）—— 隨 Maya 本體，不需額外授權
- Houdini Commercial —— 本機已安裝的節點授權

**切換到需要浮動授權的算圖器時（Arnold / MtoA / Nuke 批次）會踩到坑 #14
的同一個問題**：RQD 不繼承使用者的環境，授權伺服器設定不會自動出現。

因此三個包裝腳本都預留了授權區塊（預設註解）：

```bat
REM --- DCC license servers ---------------------------------------------------
REM set ADSKFLEX_LICENSE_FILE=@license-server.studio.local
REM set foundry_LICENSE=4101@license-server.studio.local
REM set solidangle_LICENSE=5053@license-server.studio.local
REM ---------------------------------------------------------------------------
```

| 變數 | 對應軟體 |
|---|---|
| `ADSKFLEX_LICENSE_FILE` | Autodesk（Maya、Arnold 的 Autodesk 授權形式） |
| `foundry_LICENSE` | Foundry（Nuke） |
| `solidangle_LICENSE` | Solid Angle（Arnold 獨立授權形式） |

正式部署時取消註解並填入實際的授權伺服器。

（加入授權區塊後重新驗證 Houdini 包裝腳本仍正常：frame 9 算出
472 KB EXR，exit 0。）

## Solaris / USD：husk 兩階段派工

場景規模大時，Houdini 實務上常拆成兩階段：

```
階段 1（cache）：hython 或 Houdini 產生 .usd
階段 2（render）：husk.exe -o out.exr scene.usd
```

**與目前的包裝腳本架構完全相容** —— 只要再加一個
`C:\opencue\bin\husk-22.0.429.bat`，用同樣的方式解析本機安裝路徑，
並以 layer tag 綁定版本即可。

在 OpenCue 上可以做成兩個 layer，第二層相依於第一層完成
（pyoutline 的 depend 機制），或拆成兩個 job。

本次已單獨驗證過 husk 可用：

```
husk.exe --make-output-path -f 1 -o "C:/opencue/render/husk.$F4.exr" scene.usda
-> exit 0, husk.0001.exr 916 KB
```

**授權特性待確認**：husk 通常被認為不佔用 Houdini 核心授權、啟動也比完整
hython 快，這對農場的授權池有明顯好處。但本次無法觀測授權 token 的實際消耗，
**這一點要用你們自己的授權設定實測確認**，不要直接採信。

從實測可見的部分是啟動成本：
- `hython` + Karma ROP：約 5.4–6.7 秒（含 Houdini 啟動與建場景）
- `husk` 單獨算圖：整體 exit 0，未個別計時

若採兩階段，階段 2 可以派給不需要完整 Houdini 的節點，
`RQD_TAGS` 可另外標示（例如 `husk22`），與 `houdini22` 分開管理。
