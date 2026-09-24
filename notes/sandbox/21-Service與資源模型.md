# 21 — Service 與 OpenCue 的資源模型

投遞表單上的 Layer、Username、Facility、Service、Dependency Type
是同一套資源模型的不同層面。這一份把它們的關係與實際用途說清楚，
並提出一個比「每次投遞都手寫 tag」更好的做法。

---

## 一、結構：Job → Layer → Frame

```
Job    testing-testshot-chordee_houdini_render        一次提交的工作
 ├─ Layer  export_usd     range 1-1    指令 A         同一組指令與資源需求
 └─ Layer  husk_render    range 1-3    指令 B
     ├─ Frame 0001   <- 實際派給某台機器執行的最小單位
     ├─ Frame 0002
     └─ Frame 0003
```

**Layer 是「同一個指令 ＋ 同一組資源需求」的一批 frame。**

- 兩階段派工（產 USD → 算圖）= 兩個 layer
- 同時算主畫面與 AOV = 不同 layer
- 相依關係建立在 layer 之間

**Layer Name** 只是名稱，但會出現在 log 路徑與 CueGUI 的 frame 清單裡，
取有意義的名字之後排查會輕鬆很多。**至少 3 個字元**，
少於 3 個會被 Cuebot 拒絕：

```
The layer name must be at least 3 characters
```

## 二、Username

存在 `job.str_user`，有三個實際用途：

1. **RQD 會拿它建立同名使用者**來執行 frame（見 [`04`](04-部署過程.md) 坑 #4 的 uid 衝突）
2. **CueGUI 的 `selectMine`** 靠它過濾「我的 job」
3. 歸屬與稽核

**填一個 render node 上沒處理過的名字，在 Linux 節點會觸發
`useradd` 失敗導致 frame 被 abort。**

## 三、Facility

**實體站點的分組**，例如 `local`（公司機房）、`cloud`、`dev`。
Allocation 的名稱前綴就是 facility：`local.general`、`cloud.general`。

**它會硬性限制派工**，而且失敗時完全沒有錯誤訊息 —— 見 [`12`](12-真實DCC算圖.md) 的坑 #17
與 [`17`](17-故障排查與常見疏失速查.md) 的場景 20。

## 四、Service —— 資源需求與 tag 的範本

這是最容易被忽略、但實務上最有用的一層。

**Service 定義「某類工作」的預設資源需求與 tag。** seed data 內建 10 個：

```
 service     | cores_min | mem_mb |      str_tags
-------------+-----------+--------+--------------------------
 arnold      |       100 |   3276 | general | desktop
 default     |       100 |   3276 | general | desktop
 houdini     |       100 |   3276 | general | desktop
 katana      |       100 |   2048 | general | desktop | util
 maya        |       100 |   2048 | general | desktop
 nuke        |       100 |   2048 | general | desktop
 postprocess |        10 |    512 | util
 preprocess  |        10 |    384 | util
 prman       |       100 |   3276 | general | desktop
 shell       |       100 |   3276 | general | util
```

（`cores_min = 100` 是百分比表示法，100 = 1 核。）

### 這解開了先前的一個謎題

`layer.str_tags` 的預設值是**從 service 繼承的**：

| 投遞方式 | 使用的 service | 得到的 tags |
|---|---|---|
| pyoutline 的 `Shell` | `shell` | `general \| util` |
| CueWeb 表單 | `default` | `general \| desktop` |

先前一直不明白 CueWeb 投出的 job 為什麼是 `general | desktop`，
答案就在這裡。

在投遞時明確寫 `tags=[...]` 則是**覆寫** service 的值。

## 五、自建 Service：比每次手寫 tag 更好的做法

### 為什麼

先前的建議是「投遞時明確指定版本 tag」（見 [`12`](12-真實DCC算圖.md)）。那可行，但有缺點：

- 資源需求（記憶體、核心數）散落在各個投遞腳本裡
- artist 必須懂 tag 的命名規則
- **CueWeb 的投遞表單沒有 tag 欄位**，所以從網頁投的 job 無法綁定版本

改用 service 可以一次解決三個問題。

### 建立方式

```python
import opencue
from opencue_proto import service_pb2

opencue.api.createService(service_pb2.Service(
    name="houdini2204",
    threadable=False,
    min_cores=100,                     # 100 = 1 核
    max_cores=0,                       # 0 = 不限
    min_memory=4 * 1024 * 1024,        # 單位是 KB，這裡是 4 GB
    min_gpu_memory=0,
    tags=["houdini_22_0_429"],
    timeout=0, timeout_llu=0,
    min_memory_increase=2 * 1024 * 1024,   # 【必填且必須 > 0】
))
```

也可以在 CueGUI 或 CueWeb 的 **Services** 頁面用介面管理。

### 兩個 API 陷阱

1. **`min_memory_increase` 必填且必須大於 0**，否則：

   ```
   ValueError: Minimum memory increase must be > 0
   ```

   這個值是 OpenCue 自動調高 layer 記憶體時的級距。

2. **`opencue.api.getService(name)` 對不存在的名稱回傳 `None`，不會丟例外。**
   判斷是否已存在要寫：

   ```python
   if opencue.api.getService(name) is not None:   # 正確
   ```

   用 `try/except` 包起來是無效的。

### 實測：layer 確實會繼承

建立三個 service：

| Service | tags | mem |
|---|---|---|
| `houdini2204` | `houdini_22_0_429` | 4096 MB |
| `maya2027` | `maya_2027` | 2048 MB |
| `nuke17` | `nuke_17_0v1` | 2048 MB |

投遞時**只指定 service，不指定 tags 也不指定 memory**：

```python
Shell("svc_render",
      command=[...],
      range="1-2",
      service="houdini2204")
```

結果：

```
   service   |  繼承的 tags     | 繼承的 mem_mb
-------------+------------------+--------------
 houdini2204 | houdini_22_0_429 |         4096
```

**兩個 frame 都正確派到 Windows 節點並成功完成**
（render02 沒有 `houdini_22_0_429` 這個 tag，所以不會收到）。

### 建議的 service 規劃

| Service | tags | mem | 用途 |
|---|---|---|---|
| `houdini2204` | `houdini_22_0_429` | 4 GB | Houdini 22.0.429 |
| `houdini2107` | `houdini_21_0_729` | 4 GB | Houdini 21.0.729 |
| `maya2027` | `maya_2027` | 2 GB | Maya 2027 |
| `nuke17` | `nuke_17_0v1` | 2 GB | Nuke 17 |
| `husk2204` | `houdini_22_0_429` | 3 GB | husk 算圖（記憶體可較低） |

**好處**：

- **資源需求集中管理** —— 發現 Houdini 實際要 6 GB 時只改一個地方
- **投遞端變簡單** —— artist 選 service 即可，不必懂 tag
- **CueWeb 的投遞表單可用了** —— 它有 Services 下拉選單，
  選對 service 就等於選對 tag 與記憶體，補上了該表單三項限制中的兩項

## 六、Dependency Type

`pyoutline/outline/depend.py:44-48`：

| 型態 | 意義 | 適用 |
|---|---|---|
| `LayerOnLayer` | 整層等整層 | 兩階段派工（見 [`20`](20-相依性與維運操作.md)） |
| `FrameByFrame` | 第 N 格等第 N 格 | 長序列，可及早開始 |
| `PreviousFrame` | 等前一格 | 有時序相依的模擬 |
| `LayerOnAny` | 該層任一格完成即可 | |
| `LayerOnSimFrame` | 模擬專用 | |

## 七、一張圖看完關係

```
Facility  ──限制──> 只有同 facility 的節點會被考慮
   │
Service   ──提供──> 預設的 tags / cores / memory
   │                        │
   │                   （可被投遞時的參數覆寫）
   ▼                        ▼
  Job ── os ──限制──> 只有該平台的節點會被考慮
   └─ Layer ── tags ──比對──> host.str_tags（regex 的「或」）
        └─ Frame ──派工──> 符合上述全部條件的節點
```

**派工要同時滿足**：facility 相符、os 相符（或未指定）、
tag 有任一相符、核心與記憶體足夠、節點未鎖定。

**任何一項不符都是靜默的**，不會有錯誤訊息 ——
這就是為什麼「frame 卡 WAITING」是本專案最常見的症狀，
而 [`17`](17-故障排查與常見疏失速查.md) 的場景 1、19、20 分別對應其中三種原因。
