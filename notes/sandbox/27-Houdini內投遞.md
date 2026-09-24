# 27 — 從 Houdini 直接投遞

正式做法整理在 [`notes/deploy/03-工作站.md` 第七節](../deploy/03-工作站.md#七從-houdini-直接投遞)，本篇是設計與實測紀錄。

環境：Houdini 22.0.429（Python 3.13），OpenCue venv（Python 3.11.9），2026-09-25。

---

## 一、做法

repo 沒有 Houdini 外掛。比照 [`25`](25-Maya內投遞.md) 的兩段式，另外加一支節點上執行的算圖腳本：

| 檔案 | 執行環境 | 內容 |
|---|---|---|
| [`opencue_houdini_launcher.py`](../deploy/client/houdini/opencue_houdini_launcher.py) | Houdini 內 | 只用 `hou`：hip、可算的節點、frame 範圍、是否為模擬、版本，寫成 JSON 後啟動投遞視窗 |
| [`opencue_houdini_submit.py`](../deploy/client/houdini/opencue_houdini_submit.py) | `C:\opencue\venv` | CueSubmit 視窗，Houdini 設定面板組出完整指令 |
| [`opencue_houdini_render.py`](../deploy/client/houdini/opencue_houdini_render.py) | 節點的 hython | 開 hip，算指定節點、這個 task 的 frame |

幾個決定：

- **資訊以 JSON 檔傳遞**：節點清單可能很長，不放在命令列上（Windows 命令列有長度上限）
- **不用 Houdini 內建的 `hrender.py`**：它在各台機器的安裝目錄裡，路徑不固定。
  `ocrun` 只找執行檔，所以算圖腳本放在網路空間的固定位置
- **CueSubmit 沒有 Houdini 類型**，借用 Shell 類型：Shell layer 送出的是 `commandTextBox` 的內容，
  自訂面板直接組好完整指令放進去。介面上的 job 類型因此顯示為 `Shell`
- **frame 用 `#FRAMESPEC#`**：Cuebot 會換成這個 task 的 frame，例如 `7`、`1-10`、`1-9x2`
  （`DispatchSupportService.java:687`）。frame 範圍帶 step 時也正確
- **service 以 tag 反查**：伺服器上 22.0.429 的 service 叫 `houdini2204`，無法從版本號推出；
  改為找 tags 含 `houdini_22_0_429` 的 service

### 節點的種類

以 hython 查 Houdini 22.0.429：

| 節點 | 類別 | 算圖方式 |
|---|---|---|
| ROP Geometry（SOP）、`/out` 的 geometry / usdrender / karma、USD Render ROP（LOP） | `hou.RopNode` | `render(frame_range=...)` |
| File Cache（SOP，`filecache::2.0`） | `hou.SopNode` | 設定 `trange`、`f` 後按 `execute` |
| Karma（LOP） | `hou.LopNode` | 同上 |

啟動器收入**所有 `hou.RopNode`**，加上白名單中的非 ROP 類型（`filecache::2.0`、`karma`），
而且要有 `trange` 與 `f1`（算圖腳本靠它們設定 frame 範圍）。鎖定的 HDA 內部不搜尋（例如 `/out/karma1` 裡的 `rop_usdrender`）。

第一版的判斷是「有 `execute`、`trange`、`f1` 就收」，太寬：任何帶有這三個參數的 HDA 都會被收進來。
改成現在的規則後在 hython 實測：

| 節點 | 舊規則 | 新規則 |
|---|---|---|
| 原本的四個（File Cache ×2、ROP Geometry、Karma LOP） | 收 | 收 |
| `/out` 的 Mantra ROP（`ifd`） | 收 | 收 |
| 一般的 null，加上 `execute`、`trange`、`f1` 參數 | **收** | 不收 |
| `/out` 的 merge ROP（沒有 `trange`） | 不收 | 不收 |

### 模擬的判斷

File Cache 的 **Cache Simulation**（`cachesim`）或 ROP 的 **Initialize Simulation OPs**（`initsim`）打開時，
預設「整段一個 task」。只轉換格式的快取可以每格拆開，所以不能只看節點類型。
這只是預設值：DOP、TOP 與第三方的快取節點都認不出來，最後由 artist 在投遞視窗確認。

---

## 二、實測

### 1. 測試場景

以 [`lab/make_houdini_submit_scene.py`](lab/make_houdini_submit_scene.py) 建立，存為 `C:\opencue\scenes\hou_submit_test.hip`：

| 節點 | 內容 | frame |
|---|---|---|
| `/obj/geo1/convert_cache` | File Cache，box 轉成 bgeo，`cachesim` 關 | 1-4 |
| `/obj/geo1/sim_cache` | File Cache，Solver SOP（每格 y +0.5），`cachesim` 開 | 1-10 |
| `/obj/geo1/rop_out` | ROP Geometry | 1-3 |
| `/stage/karma_render` | Karma LOP，160×90 | 1-3 |

### 2. 啟動器（hython）

```
nodes: convert_cache  1-4   simulation false
       sim_cache      1-10  simulation true
       rop_out        1-3   simulation false
       karma_render   1-3   simulation false
removed env: PYSIDE6_OPTION_PYTHON_ENUM, PYTHONHOME, PYTHONPATH, PYTHONUNBUFFERED
```

Houdini 會設定 `PYTHONHOME`，不清掉的話 venv 的 Python 會載入 Houdini 的標準函式庫。

hython 中 `hou.hipFile.hasUnsavedChanges()` **永遠是 True**，剛存完檔也一樣，
所以「有未儲存的變更」只在有 UI 時詢問。

### 3. 投遞視窗與算圖

以程式操作投遞視窗（offscreen），依序選四個節點送出：

```
convert_cache  services ['houdini2204']  range 1-4   chunk 1
sim_cache      services ['houdini2204']  range 1-10  chunk 10
rop_out        services ['houdini2204']  range 1-3   chunk 1
karma_render   services ['houdini2204']  range 1-3   chunk 1

built: ocrun houdini 22.0.429 hython .../opencue_houdini_render.py
       C:/opencue/scenes/hou_submit_test.hip /obj/geo1/sim_cache #FRAMESPEC#
```

| job | task | 結果 | 輸出 |
|---|---|---|---|
| `hou_convert_cache` | 4 | 全部 SUCCEEDED | `convert.0001`～`0004.bgeo.sc` |
| `hou_sim_cache` | **1** | SUCCEEDED | `sim.0001`～`0010.bgeo.sc` |
| `hou_rop_out` | 3 | 全部 SUCCEEDED | `rop.0001`～`0003.bgeo.sc` |
| `hou_karma_render` | 3 | 全部 SUCCEEDED | `karma.0001`～`0003.exr` |

模擬快取的 frame log：`[opencue] /obj/geo1/sim_cache frames 1-10 step 1`。
逐格讀回 y 中心：`0.5, 1.0, … 5.0`，依序累加，正確。

### 4. 模擬被拆開算會怎樣

在新的 hython 裡只算 `sim_cache` 的第 8 格：exit 0，y = 4.0（正確），只寫出 `sim.0008`。
Solver 在沒有前一格時會從起始格重算，所以**結果不會錯，但第 N 格要重算 N 格**，
每格拆開的總計算量約為 n²/2。這就是「整段一個 task」的理由。

### 5. 其他

| 項目 | 結果 |
|---|---|
| frame spec `1-5x2` | 只輸出第 1、3、5 格 |
| 節點不存在 | exit 1，log 寫 `RuntimeError: node not found: /obj/geo1/nope` |
| Houdini package（`PYTHONPATH` append） | hython 可 import 啟動器 |

測試時踩到一個與工具無關的坑：Git Bash 會把 `/obj/geo1/...` 這類參數自動轉成
`C:/Program Files/Git/obj/...`，直接從 Git Bash 執行時要設 `MSYS_NO_PATHCONV=1`。

---

### 6. 在 Houdini 介面中人工投遞

開啟測試場景，由 Python Shell 呼叫 `submit()`，依序送出四個節點：四個 job 全部成功，模擬快取是 1 個 task、chunk 10。

發現一個問題：換節點時 layer 名稱沒有跟著換，第二個以後的 job 都沿用第一次填的 `convert_cache`。
已改為選節點時自動帶入節點名稱，並加進 [`lab/check_submit_tools.py`](lab/check_submit_tools.py) 的檢查。

## 三、尚未驗證

- shelf 按鈕本身（人工測試由 Python Shell 呼叫，執行的是同一段程式）、未存檔時的詢問
- 其他 Houdini 版本、Python 2.7 的舊版 Houdini
- Redshift 等第三方算圖器的 ROP（本機沒有安裝）
- 真正的 DOP 模擬（Pyro、Vellum 等）；本次用 Solver SOP 代表
