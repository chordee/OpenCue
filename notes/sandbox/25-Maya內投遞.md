# 25 — 從 Maya 直接投遞

正式做法整理在 [`notes/deploy/03-工作站.md` 第六節](../deploy/03-工作站.md#六從-maya-直接投遞)，本篇是評估與實測紀錄。

---

## 一、repo 裡現有的外掛

| DCC | 位置 | 運作方式 |
|---|---|---|
| Maya | `cuesubmit/plugins/maya/` | shelf 按鈕，把 CueSubmit 的介面**跑在 Maya 自己的 Python 裡** |
| Nuke | `cuesubmit/plugins/nuke/` | Nuke 只收集檔名與 Write 節點，另外以 `CUE_PYTHON_BIN` 開一個外部 Python 顯示介面 |
| Houdini / Blender | 無 | — |

Nuke 外掛採外部 Python 的原因寫在 `CueNukeSubmitLauncher.py` 的註解：
Nuke 內建的 gRPC 版本與 OpenCue 衝突。

### 算圖指令的組成（`cuesubmit/Submission.py`）

```
Maya：{MAYA_RENDER_CMD} -r file -s #FRAME_START# -e #FRAME_END# [-cam 相機] 場景
Nuke：{NUKE_RENDER_CMD} -F #IFRAME# [-X Write節點] -x 場景
```

`MAYA_RENDER_CMD` 預設是 `Render`，可以在 `cuesubmit.yaml` 設定（`CUESUBMIT_CONFIG_FILE`
或 `%APPDATA%\opencue\cuesubmit.yaml`）。一個設定檔只能指定一個值。

指令先組成字串，再以 `command.split()` 切成串列，**路徑含空白時加引號也無效**（[`17` 場景 24](17-故障排查與常見疏失速查.md#場景-24路徑含空白時-frame-失敗)）。

---

## 二、與現有設計的落差

### 1. DCC 內建的 Python 版本

| DCC | 內建 Python（實測） |
|---|---|
| Maya 2027 | **3.13.9** |
| Houdini 22.0.429 | **3.13.10** |
| Nuke 17.0v1 | 3.11.11 |
| OpenCue venv | 3.11.9（grpcio 1.84.0） |

repo 的 Maya 外掛要求 opencue 套件（含需編譯的 grpcio）能在 Maya 的 Python 裡 import。
Maya 2027 與 venv 版本不同，**要另外安裝一份**；有多個 Maya 版本並存時，每個版本都要各裝一份，
越舊的版本越可能找不到相容的 grpcio。

### 2. 指令格式與現有 wrapper 不同

`maya-render-2027.bat` 吃的是 `場景 輸出目錄 算圖器`，frame 取自 `CUE_IFRAME`；
CueSubmit 送的是 `Render.exe` 原生的參數。所以另外做了轉接用的 `Render-2027.bat`，
把參數原封不動轉給 `Render.exe`。

### 3. Cuebot 內建的 `maya` service

```
maya          tags=general | desktop
maya2027      tags=maya_2027
```

artist 若在介面上選了內建的 `maya`，版本綁定就失效（tag 比對是「或」，`general` 什麼節點都對得上）。

---

## 三、做法：兩段式

比照 Nuke 外掛，把「收集資訊」和「投遞介面」拆開：

| 檔案 | 執行環境 | 內容 |
|---|---|---|
| `opencue_maya_launcher.py` | Maya 內，任何版本 | 只用 `maya.cmds` 與 `subprocess`：場景、相機、frame 範圍、`about -version` |
| `opencue_maya_submit.py` | `C:\opencue\venv` | CueSubmit 介面，依版本設定 `Render-<版本>.bat` 與 service `maya<版本>` |

幾個細節：

- CueSubmit 的 `InMayaSettings`（在 Maya 內顯示的設定面板）**完全沒有用到 Maya API**，
  只是接收檔名與相機清單的 Qt 元件，所以可以在 Maya 之外使用
- `Constants.MAYA_RENDER_CMD` 是在投遞時才被讀取，啟動後改寫它即可指定版本
- 從 Maya 啟動子程序會繼承 Maya 的環境變數。實測 mayapy 會帶 `PYTHONPATH` 與 `QT_PLUGIN_PATH`，
  指向 Maya 自己的 Python 3.13 與 Qt，venv 讀到會出錯，所以啟動前清掉
  `PYTHON*`、`QT_*`、`QTDIR`、`PYSIDE*` 開頭的變數
- 用 `Popen` 啟動後**不等待**，避免像 Nuke 外掛那樣讓 DCC 卡住
- 啟動器的語法相容 Python 2.7（不用 f-string），讓舊版 Maya 也能用

---

## 四、實測

### 1. Maya 端不依賴 opencue 套件

在 mayapy 2027 中開啟 `C:\opencue\scenes\test.ma`：

```
opencue importable in mayapy: NO
version: 2027
range: 1-10
command: [...pythonw.exe, ...opencue_maya_submit.py, --file, C:/opencue/scenes/test.ma,
          --version, 2027, --range, 1-10, --cameras, front, persp, renderCam1, side, top]
env removed: ['PYTHONPATH', 'QT_PLUGIN_PATH']
```

mayapy 裡**無法 import opencue**，啟動器照常運作。

### 2. 從 Maya 的環境啟動投遞介面並送出

由 mayapy 以清理過的環境啟動 venv 的 Python，Qt 使用 offscreen 模式，
以程式填入 job 名稱、shot、layer 名稱與相機後按下送出（模擬 artist 操作）：

```
show     : testing                     ← 取自環境變數 PROJECT
services : ['maya2027']                ← 依版本自動選好
range    : 1-10
built    : C:/opencue/bin/Render-2027.bat -r file -s #FRAME_START# -e #FRAME_END#
           -cam renderCam1 C:/opencue/scenes/test.ma
submitted
```

### 3. 算圖結果

| 項目 | 結果 |
|---|---|
| frame | 10 / 10 SUCCEEDED |
| 節點 | 全部在 LAPTOP（layer tag `maya_2027` 來自 service） |
| 每格耗時 | 平均 34.5 秒 |
| frame 編號 | 正確替換，例如第 5 格 `-s 5 -e 5` |

### 4. 輸出位置

```
Finished Rendering C:/Users/chordee/Documents/maya/projects/default/images/test.0005.png.
```

指令沒有 `-rd`，輸出位置由場景所屬的 Maya project 決定。測試場景不在任何 project 裡，
圖檔落在**算圖節點本機**的預設 project。正式環境的場景必須放在有 `workspace.mel` 的 project 中。

---

## 五、人工測試中發現的問題

### 1. 沒選相機時送出 `-cam [None]`

在 Maya 介面實際操作、沒有選相機就送出，10 個 frame 全部失敗：

```
Render-2027.bat -r file -s #FRAME_START# -e #FRAME_END# -cam [None] scene_luffy_test.ma

Error: makeCameraRenderable.mel line 34: Camera [None] does not exist.
// Maya exited with status 210
```

CueSubmit 的相機選單沒有選擇時，按鈕上顯示 `[None]`，而 `InMayaSettings.getCommandData()`
直接把按鈕文字當成相機名稱。選了多台時則會送出 `-cam a, b`，同樣無法解析。
先前以程式測試時有選相機，所以沒有發現。見 [`05` 第 22 項](05-可回饋上游的問題.md#22-cuesubmit-的-maya-相機選擇會送出錯誤的--cam)。

**修正**（`opencue_maya_submit.py` 的 `MayaSettings`）：

| 操作 | 送出的指令 |
|---|---|
| 場景只有一台 renderable 相機 | 開啟時預先選好，`-cam <該相機>` |
| 沒有選相機 | 不帶 `-cam`，由 Maya 算場景中所有 renderable 的相機 |
| 選了多台 | 改為單選，只保留最後點的一台 |

三種情況都已測試。

### 2. 工作站同時開 Maya 又接算圖工作，記憶體耗盡

本機同時是 artist 工作站與算圖節點。開著 Maya 送出 job 後，frame 派回同一台，
好幾個 `Render.exe`（每個約 1 GB，外加 Arnold）同時執行：

```
MemTotal 40 GB、MemFree 約 4 GB、分頁檔已用約 14 GB
PowerShell 無法啟動：The paging file is too small for this operation to complete
```

有兩個 frame 以 exit 304 在 1 秒內失敗、沒有任何輸出，推測是記憶體不足無法啟動程序。

**使用者看到的「crash」**：一個錯誤回報視窗。Windows 事件紀錄（Application，22:00 前後）：

| 時間 | 當掉的程式 | 例外 |
|---|---|---|
| 22:00:04、22:00:13 | `mayabatch.exe`（`Render.exe` 啟動的算圖程序） | 0xc0000005 |
| 22:00:01～22:00:48 | `cer_dialog.exe`（Autodesk Customer Error Reporting） | 0xc0000005、0xc0000409、0xc00000fd |

錯誤回報視窗是**算圖中的 Maya 當掉後，Autodesk 的回報程式跳出來的**，
不是投遞視窗（`pythonw.exe` 沒有任何當機紀錄），Maya 主視窗也沒有受影響。
第二次測試（22:31）沒有任何當機紀錄。

這在正式環境是個問題：節點上的 Maya 算圖當掉時，回報視窗會出現在桌面上，
工作站上會跳到 artist 面前，專職算圖機上則沒人關閉。
Maya 2027 的執行檔中有 `MAYA_DISABLE_CER` 這個環境變數，已加進兩支 Maya wrapper。
加入後 wrapper 照常算圖；**關閉回報視窗的效果未實測**（需要讓 Maya 當掉才能驗證）。

正式環境的工作站在上班時段由 CueNIMBY 鎖定，不會在 artist 使用中接工作，
所以不會發生同樣的情況。本機測試時可以在投遞介面把 Cores 設大一點（例如 4），
減少同時執行的 frame 數。

### 3. 修正後重新人工測試

在 Maya 2027 中開啟 `scene_luffy_test.ma`（Arnold），由 Script Editor 呼叫
`opencue_maya_launcher.submit()`，投遞視窗正常開啟，送出 frame 1-3：

```
Render-2027.bat -r file -s #FRAME_START# -e #FRAME_END# -cam persp .../scene_luffy_test.ma
tags=maya_2027

0001  SUCCEEDED  98 秒  1164 MB
0002  SUCCEEDED  98 秒  1164 MB
0003  SUCCEEDED  98 秒  1150 MB
```

3 個 frame 同時在本機執行，可用記憶體最低約 3.3 GB，沒有再出問題。

### 4. CueWeb 看不到 job

CueWeb 的「Autoload Mine」以登入帳號判斷「我的」job（`cueweb/app/page.tsx`：
`getServerSession()` 取 email 或 name）。不需要登入的版本中使用者一律是 `unknown`，
所以自動載入是空的。要在搜尋框輸入 show 或 job 名稱後按 Load。

## 六、尚未驗證

| 項目 | 說明 |
|---|---|
| 舊版 Maya | 本機只有 2027；語法相容 Python 2.7，但未實際執行 |
| Nuke 外掛 | 未安裝 |
| Houdini | 沒有現成外掛，未製作 |
