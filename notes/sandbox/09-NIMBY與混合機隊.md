# 09 — NIMBY 與混合機隊

前提（依實際情況確認）：

- render node **有兩種**：部分是 artist 工作站，部分是專職算圖機
- 工作站的使用策略是「**下班後才借用**」，不在上班時間徵用

## NIMBY 是什麼

**N**ot **I**n **M**y **B**ack **Y**ard —— 名字是從使用者角度取的：
「我在用電腦的時候，算圖請去別的地方跑。」

用途是讓公司把 artist 工作站也納入算圖資源，同時保證不影響 artist 工作。

分成兩個**各自獨立**的元件：

### RQD NIMBY（自動，即時偵測）

內建於 RQD，用 `pynput` 監控鍵鼠：

- 偵測到輸入 → 立刻鎖定主機
- 閒置超過 `MINIMUM_IDLE` → 自動解鎖
- **偵測到輸入時會直接砍掉正在跑的 frame**

第三點是代價：artist 一碰滑鼠，跑到一半的 frame 就被終止並重新排給別台，
**已算的部分白費**。

### CueNIMBY（手動控制 + 排程 + 通知）

獨立的 Qt 系統列程式，不透過 RQD，直接呼叫 Cuebot API：

- 圖示顯示目前是否可被派工
- 使用者可手動切換（「我等下要跑模擬，先關掉」）
- 桌面通知
- **時段排程**

## 為什麼「下班後才借用」要用 CueNIMBY 而不是 RQD NIMBY

RQD NIMBY 是**即時反應**：白天 artist 在用，frame 會被不斷派上去又被砍掉，
浪費算力也可能干擾工作站。

CueNIMBY 的排程是**時段封鎖**：上班時間整段不開放，白天完全不碰工作站，
artist 無感；下班後才整台加入農場。

設定檔位置：`~/.config/opencue/cuenimby.json`
（Windows 上是 `C:\Users\<user>\.config\opencue\cuenimby.json`）

範本見 `notes/sandbox/stack/cuenimby-workstation.json`：

```json
{
  "cuebot_host": "localhost",
  "cuebot_port": 8443,
  "hostname": "LAPTOP-ULJICLO8",
  "poll_interval": 5,
  "scheduler_enabled": true,
  "schedule": {
    "monday":    { "start": "09:00", "end": "18:00", "state": "disabled" },
    ...
  }
}
```

### 排程的判定邏輯（`cuenimby/scheduler.py:66-87`）

```python
if start_time <= current_time <= end_time:
    return desired_state
# Outside scheduled period - return opposite state
return "available" if desired_state == "disabled" else "disabled"
```

重點三項：

1. **時段內套用設定值，時段外自動變成相反狀態。**
   所以 `09:00-18:00 disabled` 就等於「上班不借、其餘時間開放」，
   不需要另外寫開放時段。
2. **當天若沒有設定，回傳 None，不做任何動作。**
   範例設定只列週一到週五，所以週末排程器完全不介入 ——
   星期五晚上變成 available 之後，會一路維持到星期一早上。
   對「下班後借用」來說這正是想要的。
3. **跨午夜的時段會完全失效** —— 見下方「坑 #11」。
   所以務必用不跨午夜的「封鎖時段」來表達，例如 `09:00-18:00 disabled`，
   **不要**寫成 `18:00-09:00 available`。

## 實測

測試時間：星期三 10:06（在 09:00-18:00 範圍內）。

### 1. 上班時間 → 自動鎖定

啟動 CueNIMBY：

```
cuenimby.scheduler - INFO - Scheduler changing state to: disabled
cuenimby.monitor   - INFO - State changed: Available -> 🔒 Host locked
cuenimby.monitor   - INFO - Host locked
```

Cuebot 端：

```
Host             ... State  Locked    Alloc
LAPTOP-ULJICLO8  ... UP     LOCKED    local.desktop
```

投一個 job → **3 個 frame 停在 WAITING，完全沒有派上去**。正確。

### 2. 下班時間 → 自動解鎖

把星期三的時段改成 `01:00-09:00`，現在的 10:06 就落在時段外：

```
cuenimby.scheduler - INFO - Scheduler changing state to: available
cuenimby.monitor   - INFO - State changed: 🔒 Host locked -> Available
cuenimby.monitor   - INFO - Host unlocked
```

Cuebot 端 `Locked` 欄位變回 `OPEN`。

## 坑 #10：移進 desktop allocation 後就收不到一般 job

解鎖後 frame **仍然停在 WAITING**。排查後發現與 NIMBY 無關，是 **tag 不匹配**。

Cuebot 依「layer 的 tags」與「host 的 tags」做匹配：

```sql
-- layer
str_name   | str_tags
test_layer | general | util      ← pyoutline 的預設

-- host（移進 local.desktop 之後）
str_tag     | str_tag_type
desktop     | ALLOC
rqdv-dev    | HARDWARE
desktop     | HARDWARE
windows     | HARDWARE
```

host 沒有 `general` 也沒有 `util` → 永遠不會被派工。

**這是混合機隊最關鍵的一個機制，而且失敗時毫無提示** ——
host 顯示 UP / OPEN、job 顯示 PENDING，兩邊看起來都正常，就是不動。

### 修法

在 RQD 設定檔加上標籤：

```ini
RQD_TAGS = general
```

重啟 RQD 後：

```
str_tag     | str_tag_type
general     | HARDWARE      ← 新增
desktop     | ALLOC
...
```

先前卡住的 3 個 frame 立刻轉為 RUNNING，隨後全部 SUCCEEDED。

### 兩種設計取向

| 取向 | 做法 | 適用 |
|---|---|---|
| **工作站加入一般派工池** | 工作站 `RQD_TAGS = general`，可用性完全交給 CueNIMBY 排程控制 | 「下班後借用」—— 同樣的 job，晚上多出一批機器 |
| **工作站只跑特定工作** | 工作站不加 general；投 job 時明確指定 `desktop` 標籤 | 想把「可能被中斷」的風險限制在特定工作上 |

**本次採用第一種**，因為「下班後才借用」的前提是白天完全不開放，
晚上開放時就不需要再區分工作類型。

## 兩種機器的設定對照

| 設定 | artist 工作站 | 專職算圖機 |
|---|---|---|
| `OVERRIDE_NIMBY` | `False`（改用 CueNIMBY 排程） | `False` |
| `OVERRIDE_IS_DESKTOP` | `True` | `False` |
| `RQD_TAGS` | `general` | `general` |
| Allocation | `local.desktop` | `local.general` |
| CueNIMBY | **要裝**，負責時段排程與使用者控制 | 不需要 |
| 啟動方式 | 登入時觸發，**必須跑在使用者 session** | **Windows 服務**（無人登入也要跑） |
| `OVERRIDE_CORES` | 可保留幾核給 artist | 全開 |

**關於 `OVERRIDE_NIMBY`**：既然採用「下班後才借用」，RQD 內建的即時 NIMBY
其實可以關掉 —— 開放時段本來就沒人在用。若擔心有人加班，可以兩者併用
（CueNIMBY 管時段、RQD NIMBY 當即時保險），但要接受 frame 被砍的代價。

**專職算圖機反而單純**：沒有 NIMBY 的 session 限制，可以正大光明用
Windows 服務，開機自啟的問題自然解決。

## 尚未驗證

> **注意**：本節寫於當時，部分項目後來已補測完成。
> **最新的驗證狀態以 `19-驗證狀態總表.md` 為準。**


| 項目 | 說明 |
|---|---|
| 系統列 UI | CueNIMBY 以隱藏視窗啟動，圖示、選單、通知的實際外觀未確認 |
| 手動切換 | 只測了排程自動切換，沒測使用者從選單手動開關 |
| RQD NIMBY 即時偵測 | `OVERRIDE_NIMBY = True` 的鍵鼠偵測與砍 frame 行為未測 |
| 專職算圖機角色 | 目前只有一台機器，扮演工作站。雙角色並存的派工行為未測 |
（跨午夜的時段已驗證，結果見下方坑 #11。）


## 坑 #11：跨午夜的排程時段完全失效

**排程設定務必寫成不跨午夜的形式。** 這是實測出來的限制。

`scheduler.py:83` 用的是單純的區間比較：

```python
if start_time <= current_time <= end_time:
    return desired_state
return "available" if desired_state == "disabled" else "disabled"
```

時段跨午夜時 `start > end`，這個條件**永遠不成立**，於是一律回傳相反狀態，
24 小時皆然。

實測（以 mock 注入時間，直接呼叫真實的 `_check_schedule()`）：

| 寫法 | 時間 | 預期 | 實際 |
|---|---|---|---|
| `09:00-18:00 disabled` | 10:00 | disabled | disabled |
| `09:00-18:00 disabled` | 20:00 | available | available |
| `18:00-09:00 available` | 20:00 | available | **disabled** |
| `18:00-09:00 available` | 02:00 | available | **disabled** |
| `22:00-06:00 disabled` | 23:00 | disabled | **available** |
| `22:00-06:00 disabled` | 03:00 | disabled | **available** |

兩種錯法的後果相反，都很嚴重：

- `18:00-09:00 available` → 機器**永遠不被借用**，農場靜默地少了一批算力
- `22:00-06:00 disabled` → 在**明確要求不要借用的時段反而開放機器**

### 正確寫法

利用「時段外自動取相反狀態」的特性，用**不跨午夜的封鎖時段**表達需求：

| 需求 | 正確寫法 | 錯誤寫法 |
|---|---|---|
| 下班後才借用 | `09:00-18:00 disabled` | `18:00-09:00 available` |
| 夜間不借用 | 無法用單一時段表達（見下） |  `22:00-06:00 disabled` |

「夜間不借用、白天借用」這種需求無法用單一不跨午夜的時段表達，
在修正上游程式碼之前，只能拆成兩段或改用其他方式。
幸好我們的情境是「下班後才借用」，剛好可以用 `09:00-18:00 disabled` 表達。

詳細根因與建議修法見 `05-可回饋上游的問題.md` 第 12 項。


## 工作站的啟動腳本必須同時帶起 RQD 與 CueNIMBY

`stack/rqd-start.bat` 一開始只啟動 `rqd.exe`，這對工作站是不完整的 ——
沒有 CueNIMBY 就沒有時段排程，工作站會 24 小時開放。

腳本已更新，用 `NODE_ROLE` 區分兩種角色：

```bat
set NODE_ROLE=workstation    REM 或 render

start "OpenCue RQD" /B "%OPENCUE_VENV%\Scripts\rqd.exe" >> ... 2>&1

if /I "%NODE_ROLE%"=="workstation" (
    ping -n 21 127.0.0.1 > nul
    start "CueNIMBY" /B "%OPENCUE_VENV%\Scripts\cuenimby.exe" >> ... 2>&1
)
```

實作過程踩到兩個坑，都值得記。

### 坑 #12：啟動順序 —— RQD 必須先就緒

第一版把 CueNIMBY 放在 RQD 前面，結果：

```
failed to lock host: LAPTOP-ULJICLO8
RqdClientException: failed to lock host
```

**原因**：「鎖定主機」不是 Cuebot 自己改個旗標就好，
它是 **Cuebot 回呼該節點的 RQD（8444）** 來執行的。
RQD 還沒開始聽的時候，CueNIMBY 的排程套用必定失敗。

所以順序是：先起 RQD → 等它註冊完成 → 再起 CueNIMBY。

腳本用 `ping -n 21 127.0.0.1` 做延遲，而不是 `timeout` ——
`timeout` 在 stdin 被重導向時會失敗，而排程工作正是這種情況。

### 坑 #13：.bat 檔必須是純 ASCII

原本的腳本寫了中文註解（UTF-8）。**cmd.exe 是用 OEM 代碼頁解析 .bat**
（這台機器是 CP950），UTF-8 的中文被當成 Big5 解讀成亂碼，破壞了語法：

```
'tlocal' is not recognized as an internal or external command,
'workstation" (' is not recognized as an internal or external command,
```

結果是兩個行程都沒起來。加了 `setlocal` 與 `if (...)` 區塊之後特別容易炸，
因為亂碼會破壞區塊的括號配對。

**規範**：部署到 Windows 節點的 .bat 一律使用純 ASCII，
中文說明放在筆記裡。可用 `file <檔案>` 確認輸出為 `ASCII text`。

修正後實測：兩個行程都正常啟動，CueNIMBY 成功套用排程並鎖定主機，無錯誤。
