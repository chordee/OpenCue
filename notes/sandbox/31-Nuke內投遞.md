# 31 — 從 Nuke 直接投遞

正式做法整理在 [`notes/deploy/03-工作站.md` 第八節](../deploy/03-工作站.md#八從-nuke-直接投遞)，本篇是設計與實測紀錄。

環境：Nuke 17.0v1（Python 3.11.11），OpenCue venv（Python 3.11.9），2026-09-25。

---

## 一、repo 裡現有的東西

| 項目 | 問題 |
|---|---|
| 外掛 `cuesubmit/plugins/nuke/` | 已經是兩段式，但以 `communicate()` **等投遞視窗關閉**，期間 Nuke 無法操作；要求 `CUE_PYTHON_BIN` 或 `python` 在 PATH 上 |
| CueSubmit 的 Nuke 類型 | 沒選 Write 節點送出 `-X [All]`，選多個送出 `-X a, b`（與 [`05` 第 22 項](05-可回饋上游的問題.md#22-cuesubmit-的-maya-相機選擇會送出錯誤的--cam)的 Maya 相機同一類問題） |
| 同上 | 固定使用 `-F #IFRAME#`，chunk 大於 1 時只算每個 task 的第一格 |

最後一項的實測（`-F #IFRAME#`，range `1-4`，chunk 2）：

```
frames  1 SUCCEEDED、3 SUCCEEDED
輸出    a.0001.png、a.0003.png          ← 第 2、4 格沒有算，卻被標成完成
```

見 [`05` 第 25 項](05-可回饋上游的問題.md#25-cuesubmit-的-nuke-類型會送出錯誤的--xchunk-大於-1-時漏算)。

---

## 二、做法

比照 [`27`](27-Houdini內投遞.md)：Nuke 內的啟動器只用 `nuke` 收集資訊、寫成 JSON，
venv 的投遞視窗借用 Shell 類型、自己組完整指令：

```
ocrun nuke <版本> Nuke<主.次版本> -F #FRAMESPEC# [-X Write1,Write2] -x <script.nk>
```

- 執行檔名稱由版本推出：`17.0v1` → `Nuke17.0`
- Write 節點預設全選；全選時不帶 `-X`，由 Nuke 算所有啟用中的 Write
- service 以版本 tag `nuke_17_0v1` 反查，得到 `nuke17`
- `menu.py` 在選單列加上 OpenCue > Submit to OpenCue；把工具目錄加進 `NUKE_PATH` 即可
- Nuke 的 job 算圖時只讀 `.nk` 與 `ocrun`，工具檔案可以直接覆蓋更新，不需要版本目錄

---

## 三、實測

### 1. Nuke 的命令列行為

以 [`lab/make_nuke_submit_scene.py`](lab/make_nuke_submit_scene.py) 建立 `C:\opencue\scenes\nuke_submit_test.nk`：
CheckerBoard 接兩個 Write，`WriteA` 在最上層，`WriteB` 在 Group `Comp` 裡。

從農場送出（`-X WriteA,Comp.WriteB`）：

| layer | range / chunk | 指令中的 `-F` | 結果 |
|---|---|---|---|
| step | `1-5x2` / 3 | `1-5x2` | 1 個 task，算第 1、3、5 格 |
| chunk | `1-4` / 2 | `1-2`、`3-4` | 2 個 task，各算兩格 |

- Nuke 的 `-F` 接受 Cuebot `#FRAMESPEC#` 的格式（`1-2`、`1-5x2`）
- `-X` 以逗號接多個節點可用，Group 內的節點用 `Comp.WriteB`
- 在 frame 的環境裡，Nuke 的算圖授權沒有問題

失敗時的 exit code（直接執行）：

| 情況 | exit code | 訊息 |
|---|---|---|
| `-X Nope`（不存在的節點） | 1 | `Nothing is named "Nope"` |
| 輸出目錄不存在 | 1 | `WriteA: Can't write, no such directory` |

Nuke 失敗時會回傳非 0，不像 Maya（[`30`](30-Arnold授權與假成功.md)），`ocrun` 不需要檢查輸出。

### 2. 啟動器（Nuke terminal 模式）

```
GUI False, modified after open False
info: script C:/opencue/scenes/nuke_submit_test.nk, version 17.0v1,
      writes [WriteA, Comp.WriteB], range 1-5
removed env: PYSIDE63_OPTION_PYTHON_ENUM, PYTHONPATH
```

Nuke 的 `nuke.modified()` 在開啟後是 False，沒有 hython 那種「永遠未儲存」的問題。

### 3. 投遞視窗與算圖

[`lab/check_submit_tools.py`](lab/check_submit_tools.py) 加入 Nuke：

```
PASS  service: ['nuke17']
PASS  range: '1-5'
PASS  command, all writes: ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -x C:/opencue/scenes/nuke_submit_test.nk
PASS  command, one write:  ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -X WriteA -x C:/opencue/scenes/nuke_submit_test.nk
```

`--submit` 實際送出，兩個 job 各 5 格全部成功，`a.0001`～`0005`、`b.0001`～`0005` 都有輸出。

---

## 四、尚未驗證

- **在 Nuke 介面中人工操作**：選單、存檔詢問、Write 節點選單
- 停用的 Write 節點不列入（程式有處理，未實測）
- 其他 Nuke 版本、Python 2.7 的舊版 Nuke
- NukeX、Nuke Studio 的授權與執行檔名稱
