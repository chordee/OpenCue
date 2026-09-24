# 12 — 真實 DCC 算圖測試（Houdini / Maya / Nuke）

先前的測試都是 `/bin/sleep` 或簡單的 Python 腳本。這一份用**真正的算圖軟體**
跑完整流程，一次驗證多項先前只能紙上談兵的事。

> 本篇使用的 DCC wrapper（`.bat`）後來已由 `ocrun` 取代，見 [`26`](26-ocrun取代wrapper.md)。
> 下文的 wrapper 連結指向刪除前的版本。

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

範本見 [`notes/deploy/node/hython-22.0.429.bat`](https://github.com/chordee/OpenCue/blob/9229923c/notes/deploy/node/hython-22.0.429.bat)。**必須是純 ASCII**（見 [`09` 坑 #13](09-NIMBY與混合機隊.md#坑-13bat-檔必須是純-ascii)）。

一台節點只會有它真正裝了的版本的包裝腳本。找不到執行檔時明確回傳 127，
而不是靜默失敗。

#### 跨作業系統時：指令路徑沒有自動對應機制

log 根目錄有 per-OS 的設定（見本文件後段），**但指令沒有**。
兩者的處理方式不對稱，實作前要先理解：

| 項目 | 儲存位置 | 是否有 per-OS 機制 |
|---|---|---|
| frame log 根目錄 | Cuebot 設定 | **有** —— `log.frame-log-root.<OS>` |
| **layer 的執行指令** | `layer.str_cmd`（**單一欄位**） | **沒有** |
| job 的目標 OS | `job.str_os`（**job 層級，不是 layer**） | —— |

`layer` 表只有一個 `str_cmd`，而 `os` 是記在 `job` 上。
所以 **一個 job 只能對應一種作業系統，指令也只有一種寫法**。

這其實是合理的設計，用法是：

> **一個 job = 一種 OS = 一種指令形式。**
> 跨平台的工作要拆成不同的 job（或不同的 layer 搭配不同的 job），
> 各自用 `os` 參數釘住平台，指令也各自寫成該平台的形式。

因此包裝腳本的「固定路徑」慣例要**依平台各自定義**：

| 平台 | 建議的包裝腳本路徑 |
|---|---|
| Windows | `C:\opencue\bin\hython-22.0.429.bat` |
| Linux | `/opt/opencue/bin/hython-22.0.429.sh` |

**同一平台內**，所有節點的路徑必須完全一致（這是第 1 層的重點）；
**跨平台之間**則不需要一致，因為指令本來就是分開寫的。

本專案的算圖節點全部是 Windows，所以只需要 Windows 那一套。
但若未來加入 Linux 節點跑輔助工作（轉檔、代理圖），
記得它需要自己的一套包裝腳本與 job 送法。

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
    tags=["houdini_22_0_429"],          # 只放版本 tag，見下方說明
    env={"OPENCUE_RENDER_OUT": out, "OPENCUE_RENDERER": "karma"},
)
```

#### 【重要】tag 的比對是 regex 的「或」，不是「且」

初版這裡寫成 `tags=["general", "houdini_22_0_429"]` 並說明
「只會派給同時帶有兩個標籤的節點」。**那是錯的**，實測推翻了。

Cuebot 的派工 SQL（`cuebot/.../dao/postgres/DispatchQuery.java:296, 363`）：

```sql
AND host.str_tags ~* ('(?x)' || layer.str_tags || '\y')
```

`~*` 是 PostgreSQL 的**正規表示式比對**，而 layer 的 tag 字串
（多個 tag 以 ` | ` 串接，例如 `general | util`）**直接被當成 regex pattern** ——
其中的 `|` 就是 regex 的「或」。

所以只要 host 擁有**其中任一個** tag 就會被派工。
加上 `general` 等於「任何在派工池裡的節點都符合」，**版本綁定完全失效**。

#### 實測證據

兩個節點，tag 刻意區隔：

```
LAPTOP-ULJICLO8   general houdini22 houdini_22_0_429 maya2027 nuke17 ...
render02          general houdini21 houdini_21_0_729
```

**第一輪（錯誤寫法，tags 含 general）**：

| layer tags | 預期 | 實際 |
|---|---|---|
| `general \| houdini_21_0_729` | render02 | **LAPTOP-ULJICLO8** |
| `general \| houdini_22_0_429` | LAPTOP | LAPTOP-ULJICLO8 |
| `general \| houdini_99_nonexistent` | 無人可派，應 WAITING | **LAPTOP-ULJICLO8** |

三個全跑到同一台，連「沒有任何機器擁有該版本」的那個都被派出去了。

**第二輪（正確寫法，只放版本 tag）**：

| layer tags | 結果 | 執行主機 |
|---|---|---|
| `houdini_21_0_729` | SUCCEEDED | **render02** |
| `houdini_22_0_429` | SUCCEEDED | **LAPTOP-ULJICLO8** |
| `houdini_99_nonexistent` | **WAITING** | —— |

版本綁定正確運作。

#### 【更好的做法】改用 Service 管理 tag 與資源

本節的結論是「投遞時只放版本 tag」。那可行，但**有更好的做法** ——
把 tag 與資源需求定義在 **Service** 上，投遞時只指定 service。

layer 的 tags 預設就是從 service 繼承的（這也解釋了為什麼 pyoutline 的
`Shell` 預設得到 `general | util`）。自建 service 後：

```python
Shell("svc_render", command=[...], range="1-2", service="houdini2204")
# 不需要寫 tags，也不需要寫 memory
```

好處是資源需求集中管理、投遞端不必懂 tag 規則，
而且 **CueWeb 的投遞表單有 Services 下拉選單**，選對 service 即可。

**完整說明與實測見 [`21-Service與資源模型.md`](21-Service與資源模型.md)。**
以下仍保留手寫 tag 的規則，因為理解它才能理解 service 在做什麼。

#### 推論與實務建議

- **要綁版本就只放版本 tag。** 不要混入 `general`
- **若要允許多個版本擇一**，正好可以利用這個 OR 特性：
  `tags=["houdini_22_0_429", "houdini_22_0_368"]` 表示兩個版本都可以
- **注意 regex 的副作用**：tag 內容會被當成 pattern，
  含有 `.` `*` `+` `(` 等字元的 tag 會有非預期的比對結果。
  命名時只用英數與底線
- 部分查詢有加 `\y`（單字邊界）而 `DispatchQuery.java:296` 沒有，
  理論上可能發生**子字串誤配**（例如 `houdini2` 配到 `houdini22`）。
  命名時避免讓某個 tag 成為另一個的前綴

### 為什麼指令要用「串列」

`pyoutline/outline/io.py:53` 的 `prep_shell_command()`：

```python
if not isinstance(cmd, (tuple, list, set)):
    cmd = shlex.split(str(cmd))
```

字串會經過 `shlex.split()`，而 POSIX 模式下反斜線被當成跳脫字元吃掉 ——
Windows 路徑會被破壞。傳串列就完全繞過。

投遞腳本見 [`notes/sandbox/lab/submit_houdini.py`](lab/submit_houdini.py)。

## 算圖腳本

[`notes/sandbox/lab/houdini_render_frame.py`](lab/houdini_render_frame.py)，重點設計：

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

> **注意**：本節寫於當時，部分項目後來已補測完成。
> **最新的驗證狀態以 [`19-驗證狀態總表.md`](19-驗證狀態總表.md) 為準。**


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
（見 [`08`](08-Windows節點實錄.md) 的說明）。**不是故障。**

## Maya

場景以 `mayapy.exe` 產生（`stack/make_maya_scene.py` 的做法，本次直接寫在
`C:\opencue\scripts\`），算圖用 `Render.exe`：

```bat
Render.exe -r sw -s %CUE_IFRAME% -e %CUE_IFRAME% -rd "%OUTDIR%" "%SCENE%"
```

包裝腳本 [`notes/deploy/node/maya-render-2027.bat`](https://github.com/chordee/OpenCue/blob/9229923c/notes/deploy/node/maya-render-2027.bat) 的關鍵設計：**frame 由 `CUE_IFRAME`
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

修法（[`notes/deploy/node/nuke-17.0v1.bat`](https://github.com/chordee/OpenCue/blob/9229923c/notes/deploy/node/nuke-17.0v1.bat)）：

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

修法（[`notes/deploy/node/rqd-start.bat`](../deploy/node/rqd-start.bat)）—— 不繼承，直接指定：

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

投遞腳本 [`notes/sandbox/lab/submit_dcc.py`](lab/submit_dcc.py) 內含三者的 preset，用法：

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
**這一點要用實際的授權設定實測確認**，不要直接採信。

從實測可見的部分是啟動成本：
- `hython` + Karma ROP：約 5.4–6.7 秒（含 Houdini 啟動與建場景）
- `husk` 單獨算圖：整體 exit 0，未個別計時

若採兩階段，階段 2 可以派給不需要完整 Houdini 的節點，
`RQD_TAGS` 可另外標示（例如 `husk22`），與 `houdini22` 分開管理。

---

# 補充：用 Docker 容器模擬多節點

沒有第二台實體機器時，**可以用額外的 RQD 容器當成其他節點**，
驗證跨節點的派工行為。這不能取代真實的跨機器測試，但能涵蓋：

| 可驗證 | 不可驗證 |
|---|---|
| 多節點同時註冊 | 真實網路與防火牆 |
| **tag 派工是否正確落點** | Windows 特有行為（容器是 Linux） |
| facility / allocation 的影響 | 實體機器的資源競爭 |
| Cuebot 面對多節點的負載 | 共享儲存的真實延遲 |

本次就是靠這個方法抓到兩個錯誤（tag 是 OR、facility 不匹配）。

## 啟動第二個節點

Rust RQD 容器需要三項處理（皆在前面的筆記中說明過）：

```bash
docker run -d --name render02 --hostname render02 --network opencue \
  -e OPENCUE_RQD_CONFIG=/etc/rqd/render02.yaml \
  -v /mnt/c/opencue/nodes:/etc/rqd:ro \
  --entrypoint /bin/sh \
  opencue-rqd:latest \
  -c 'id -u <投job的使用者> >/dev/null 2>&1 || useradd --uid 2000 --gid 1000 -M <投job的使用者>; exec /app/openrqd'
```

設定檔 `render02.yaml`：

```yaml
grpc:
  cuebot_endpoints: ["cuebot:8443"]

machine:
  use_ip_as_hostname: false
  custom_tags:
    - houdini21
    - houdini_21_0_729
```

## 坑 #16：Rust RQD 的 tag 無法用環境變數設定

直覺上會想用環境變數，但會失敗：

```bash
-e "OPENRQD__MACHINE__CUSTOM_TAGS=general,houdini21"
```
```
thread 'main' panicked:
invalid type: string "general,houdini21", expected a sequence
```

`rust/crates/rqd/src/config/mod.rs:637-639` 雖然設了
`.list_separator(",")`，但**沒有指定哪些 key 要當清單解析**，
所以清單型欄位無法從環境變數讀入。

**必須改用設定檔**，並以 `OPENCUE_RQD_CONFIG` 指向它
（`config/mod.rs:622`）。

## 坑 #17：facility 不匹配會靜默地不派工

第二個節點起來、tag 也正確，但 job 仍停在 WAITING。

原因是 **job 綁定 facility，跨 facility 不會派工**：

```
LAPTOP-ULJICLO8   alloc = local.desktop    <- facility local
render02          alloc = cloud.general    <- facility cloud
```

而 job 的 facility 來自 pycue 的 `cuebot.facility_default: local`。

**兩種 RQD 的預設 facility 都是 `cloud`**：

| 實作 | 預設值 | 位置 |
|---|---|---|
| Rust RQD | `cloud` | `rust/crates/rqd/src/config/mod.rs:162` |
| Python RQD | `cloud` | `rqd/rqd/rqconstants.py:44`（`DEFAULT_FACILITY`） |

所以**新節點預設都會落在 `cloud.general`**，而用戶端投出來的 job 預設是
`local` —— 兩邊對不上，永遠不會派工。

先前 Windows 節點之所以正常，是因為稍早手動執行過
`cueadmin -force -move local.desktop -host LAPTOP-ULJICLO8`。

### 症狀與診斷

**症狀與「tag 不匹配」完全相同**：host 顯示 `UP` / `OPEN`，
job 顯示 `PENDING`，frame 停在 `WAITING`，沒有任何錯誤訊息。

診斷時要同時看兩件事：

```bash
# 1. host 在哪個 allocation（前綴就是 facility）
cueadmin -lh

# 2. job 在哪個 facility
cueadmin -lji <job>        # 或看 CueGUI 的 Attributes
```

### 解法

把節點移到 job 所在 facility 的 allocation：

```bash
cueadmin -force -move local.general -host render02
```

移動後先前卡住的 job **會自動被撿走**，不需要重投。

或在節點的設定檔指定 facility：

```yaml
machine:
  facility: local
```

**正式部署時建議統一規劃 facility**，並在每個節點的設定檔明確指定，
不要依賴預設值。

---

# 混合作業系統的農場

用容器模擬多節點時，順帶驗證了一件原本沒預期會測到的事：
**同一個 OpenCue 農場可以同時包含 Windows 與 Linux 節點**，
而且有專門的機制控制工作要跑在哪種系統上。

## 實測環境

```
LAPTOP-ULJICLO8   Windows   （實體機，裝了 Houdini / Maya / Nuke）
render02          debian    （容器，無 DCC）
```

兩台都註冊在同一個 Cuebot、同一個 allocation（`local.general` / `local.desktop`），
彼此並存無衝突。

## OS 過濾：比 tag 更適合區分平台

Cuebot 的派工 SQL 有獨立的 OS 條件
（`DispatchQuery.java:284-287`，另見 350、431、457 行）：

```sql
AND (
      job.str_os IS NULL OR job.str_os = ''
   OR job.str_os IN ?
)
```

語意是：

- **job 沒指定 OS** → 不限制，任何平台的節點都可以收
- **job 指定了 OS** → 只派給該平台的節點

### 怎麼指定

`outline.cuerun.launch()` 的 `os` 參數（`backend/cue.py:277`）：

```python
outline.cuerun.launch(ol, use_pycuerun=False, os="Windows")
```

節點回報的 OS 字串來自各自的 RQD：

| 節點 | 回報值 |
|---|---|
| Windows 實體機 | `Windows` |
| Debian 容器 | `debian` |

（Python RQD 用 `platform.system()`，見 `rqd/rqd/rqconstants.py:177` 的 `SP_OS`。）

### 實測

兩個 job **完全相同**（同樣的 `/bin/sleep 8`、都不指定 tag），
唯一差別是 `os` 參數：

| job 要求的 os | 狀態 | 執行主機 |
|---|---|---|
| `debian` | SUCCEEDED | **render02** |
| `Windows` | **DEAD** | **LAPTOP-ULJICLO8** |

Windows 那個 DEAD 是**預期內的**：`/bin/sleep` 在 Windows 上不存在。
**失敗本身正好證明它確實被派到了 Windows 節點** ——
如果 OS 過濾沒生效，它會跑到 render02 上並成功。

## 實務建議：OS 用 `os` 參數，版本用 tag

兩種機制各有適合的用途，不要混用：

| 要區分的事 | 用什麼 | 原因 |
|---|---|---|
| **平台**（Windows / Linux / macOS） | `os` 參數 | 專用欄位，語意明確，且是「等於」比對 |
| **DCC 版本、硬體特性** | layer tag | tag 可自由命名，但要注意是 **regex 的「或」** |

**為什麼不要用 tag 表示平台**：tag 是 OR 比對，
一旦 layer 有多個 tag，平台條件就可能被其他 tag 繞過
（見前面「tag 比對是 regex 的或」那一節的實測）。
`os` 是獨立的 AND 條件，不會被 tag 影響。

## 對本專案的意義

目標環境是「Linux 主機跑 Cuebot、Windows 機器算圖」，
**理論上不需要混合節點**。但這個特性在兩種情況下有用：

1. **過渡期** —— 若未來要引入 Linux 算圖節點，兩者可以共存，
   不需要分成兩座農場
2. **輔助工作** —— 有些非算圖的工作（檔案轉換、代理圖產生、清理作業）
   放在 Linux 容器上跑更輕量，可以與 Windows 算圖節點共用同一個 Cuebot

## 但要清楚容器模擬「沒有」驗證到什麼

容器節點是 Linux，所以以下 Windows 專屬的多機議題**完全沒有涵蓋**：

| 項目 | 為什麼測不到 |
|---|---|
| 第二台 Windows 的短主機名稱能否被 Cuebot 解析 | 容器用 Docker 內建 DNS，非公司 DNS |
| Windows 防火牆的入站 8444 | 容器在同一個 Docker network，沒經過防火牆 |
| 多台機器的磁碟機代號是否真的一致 | 容器沒有磁碟機代號 |
| Windows 服務模式（session 0）能否看到網路磁碟機 | 容器不是 Windows |
| **包裝腳本在「DCC 裝在不同路徑」的機器上是否有效** | render02 沒裝 DCC |
| 真實網路延遲對共享儲存的影響 | 同一台機器內部通訊 |

**最後兩項特別重要** —— 包裝腳本的整個設計目的就是處理
「每台機器 DCC 裝在不同位置」，但目前只在一台機器上驗證過。

**這些應列為正式部署第一台 Windows 節點的驗收項目**
（見 [`18`](18-三種角色的準備清單.md) 的部署順序）。只要找到任何一台閒置的實體 Windows 機器，
即使不裝 DCC，也能驗證前四項最容易出事的部分。

## 跨平台的 log 路徑對應（per-OS frame log root）

混合作業系統的農場必須處理一件事：**`CUE_FRAME_LOG_DIR` 是設在 Cuebot 上的，
全農場共用一個值**。Windows 路徑給 Linux 節點用會出事。

### 不設定會怎樣（實測）

Cuebot 設 `CUE_FRAME_LOG_DIR=C:/opencue/logs`，Linux 容器節點收到工作後：

```
/app/C:/opencue/logs/testing/testshot/logs/.../xxx.rqlog
     ↑ 建立了一個字面上叫 "C:" 的目錄
```

因為 `C:/opencue/logs` 在 Linux 上是**相對路徑**，
於是在行程的工作目錄 `/app` 底下建了一個名為 `C:` 的資料夾。
**沒有任何錯誤訊息**，job 也回報成功 —— 只是 log 在誰也想不到的地方。

### OpenCue 內建的解法

`cuebot/src/main/java/com/imageworks/spcue/util/JobLogUtil.java:59-66`：

```java
public String getJobLogRootDir(String os) {
    try {
        return env.getRequiredProperty(String.format("log.frame-log-root.%s", os), String.class);
    } catch (IllegalStateException e) {
        return env.getRequiredProperty("log.frame-log-root.default_os", String.class);
    }
}
```

**依 job 的 `os` 挑選對應的根目錄**，找不到才退回 `default_os`。
`opencue.properties:83-92` 有說明與範例。

**關鍵：key 是 job 的 `str_os`，不是執行節點的 OS。**
所以要讓它生效，**job 必須指定 `os`**（就是前一節用來控制派工的同一個參數）。
兩者是同一套機制的兩面：指定 OS 既決定派到哪種節點，也決定 log 路徑。

### 設定方式

加在 Cuebot 的啟動參數：

```yaml
command: >-
  --datasource...
  --log.frame-log-root.Windows=${FRAME_LOG_ROOT_WINDOWS}
  --log.frame-log-root.debian=${FRAME_LOG_ROOT_LINUX}
```

```
FRAME_LOG_ROOT_WINDOWS=C:/opencue/logs
FRAME_LOG_ROOT_LINUX=/tmp/rqd/logs
```

屬性名稱的 OS 部分要**對應 RQD 回報的平台名稱**
（Python RQD 用 `platform.system()`，見 `rqconstants.py:177` 的 `SP_OS`）：

| 節點 | 回報值 | 對應屬性 |
|---|---|---|
| Windows | `Windows` | `log.frame-log-root.Windows` |
| Debian 容器 | `debian` | `log.frame-log-root.debian` |

### 實測結果

設定後重投兩個 job：

| job 的 os | 執行主機 | DB 記錄的 log 路徑 | 實際檔案位置 |
|---|---|---|---|
| `debian` | render02 | `/tmp/rqd/logs/...` | ✅ Linux 節點的 `/tmp/rqd/logs/` |
| `Windows` | LAPTOP-ULJICLO8 | `C:/opencue/logs/...` | ✅ Windows 的 `C:\opencue\logs\` |

**兩邊各自落在正確的位置，DB 記錄的路徑也與實體檔案一致。**

### 這個機制的範圍與限制

| 涵蓋 | 不涵蓋 |
|---|---|
| **frame log 的根目錄** | 場景檔、貼圖、算圖輸出的路徑 |

**job 指令裡的路徑完全不經過這個機制** —— 那是投 job 端的責任。
若要在混合平台上共用同一份場景，仍須靠：

- 投 job 時依目標平台組出對應的路徑，或
- 使用兩邊都成立的路徑形式（UNC 正斜線，但 Linux 端仍須把共享掛在相符位置）

### 對本專案的意義

目標環境的算圖節點**全部是 Windows**，所以只要設
`log.frame-log-root.Windows` 一項即可，或直接用 `CUE_FRAME_LOG_DIR`
（`default_os`）也行。

**但如果未來引入 Linux 節點，這一項一定要先設好** ——
否則症狀是「job 成功、log 卻找不到」，而且不會有任何錯誤訊息。
