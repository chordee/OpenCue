# 34 — Houdini PDG 的 OpenCue scheduler（設計）

讓 TOP 網路的 work item 在 OpenCue 農場上執行。設計、實作與本機驗證。2026-09-25。

---

## 一、目標與範圍

**使用方式**：TOP 網路放一個 OpenCue scheduler，artist **一次 cook 一個節點**。
上游已經 cook 完時，這個節點的所有 work item 同時變成可執行，打包成**一個 OpenCue job**，
一個 work item 一格 frame。跑完再 cook 下一個節點。

work item 的結果（輸出檔、屬性）照常回報給 PDG，下游看得到，與本機 cook 相同。

**第一版不做**：

| 項目 | 理由 |
|---|---|
| Submit Graph As Job（送出後可以關掉 Houdini） | 使用者同意 Houdini 開著直到 cook 結束 |
| PDG MQ | 回報先直接連回送出端的 Houdini，見第四節 |
| 靜態 cook（`onScheduleStatic`） | 內建的農場 scheduler 都沒有實作，見第二節 |
| 跨節點合併成一個 job | 一次 cook 一個節點就不需要 |

---

## 二、參考：Houdini 內建的 scheduler

原始碼在 `$HFS/houdini/pdg/types/schedulers/`：`tbdeadline.py`（Deadline）、`prtractor.py`（Tractor）、
`local.py`（Local）、`pythonscheduler.py`（Python Scheduler），HQueue 在 `$HFS/houdini/pdg/types/houdini/hqueue.py`。

| | Deadline | Tractor | OpenCue 的限制 |
|---|---|---|---|
| work item 對應 | 一個 root job，之後的 work item **追加成 frame**，每格讀自己的 task 檔 | 一個 job，work item **動態加成 task** | job 送出後**不能追加** frame 或 layer（`proto/src/job.proto` 沒有這類 API），只能一批一個 job |
| 回報 | 農場上跑 PDG MQ（`pdgmq.py`），送出端主動連過去 | 同左 | 第一版直接回報 |
| `onScheduleStatic` | 空的 `pass` | 空的 `pass` | 不做 |

所以即使 work item 是靜態產生的，一般的 cook 也是上游完成後才逐一呼叫 `onSchedule`。

---

## 三、架構

三個程式，沿用投遞工具「DCC 內只用 DCC 的 API，OpenCue 的部分在 venv 執行」的原則：
Houdini 22 的 Python 是 3.13，venv 是 3.11，而且 `opencue` 需要 grpc。

| 程式 | 在哪執行 | 做什麼 |
|---|---|---|
| `opencuescheduler.py` | 送出端的 Houdini | `PyScheduler` 子類別，登錄為 PDG 的 scheduler 型別 |
| `opencue_pdg_helper.py` | 送出端的 venv（子程序，交換 JSON） | 送出 job、查詢 frame 狀態、砍 job 或 frame |
| `opencue_pdg_task.py` | 農場上，`ocrun houdini <版本> hython` | 讀自己那一格的 task 檔，設定環境變數，執行 work item 的指令 |

放在 Houdini 工具的版本目錄（`releases\<工具版本>\client\houdini\`），`opencuescheduler.py` 放在
其下的 `pdg/types/`，由 package 加進 `HOUDINI_PATH`。

### 流程

1. **`onSchedule(work_item)`**：代換指令中的 token、產生這個 work item 的環境變數、序列化 work item
   （`createJobDirsAndSerializeWorkItems`），把指令與環境變數寫成 task 檔，放進待送出清單
2. **`onTick()`**：
   - 待送出清單在一段時間內（例如 3 秒）沒有新增，就寫出 job 規格，交給 helper 送出一個 job：
     frame `1..N` 對應清單中的 work item
   - 每隔一段時間（例如 10 秒）請 helper 查詢 frame 狀態。frame 變成 DEAD、但 work item 沒有回報結果的
     （例如程式當掉），回報為失敗
3. **成功與失敗的回報**：由 work item 自己透過 PDG 的 `pdgcmd` 連回送出端的 callback server
4. **`onStopCook(cancel)`、`onCancelWorkItems`**：砍掉對應的 job 或 frame

frame 的指令固定為：

```
ocrun houdini <版本> hython <版本目錄>/opencue_pdg_task.py <task 目錄> #IFRAME#
```

---

## 四、決定與理由

| 決定 | 理由 |
|---|---|
| **每格 frame 讀自己的 task 檔** | OpenCue 的環境變數以 layer 為單位，PDG 的環境變數以 work item 為單位（`PDG_ITEM_NAME`、`PDG_ITEM_ID` 等），同一個 layer 放不下。Deadline 也是這個做法 |
| **待送出清單等一段時間沒有新增才送出** | 同一個節點的 work item 可能分散在幾次 tick 裡交出來，立刻送出會拆成好幾個 job |
| **回報直接連回送出端的 Houdini**（`CallbackServerMixin`） | 最簡單。前提是節點連得到工作站：callback server 的 port 限定在固定範圍（`custom_port_range`），防火牆開放這個範圍；工作站的名稱要能從節點解析 |
| **工作目錄放在共用空間**（預設 `$HIP` 底下） | task 檔、序列化的 work item、PDG 的腳本都要讓節點讀得到。磁碟機代號各機一致、全部是 Windows，所以本機與農場的路徑相同，不需要 path mapping |
| **不複製送出端的環境** | Local scheduler 會複製整個 Houdini 的環境，農場不這麼做：只帶 PDG 的變數與 work item 自己的變數，與投遞工具的原則相同（[`02` 第四節](../deploy/02-算圖節點.md#傳給-frame-的主機環境變數)） |
| **service 以版本 tag 反查**，找不到就拒絕 cook | 與投遞工具相同 |
| **job 名稱含 hip 名稱、TOP 節點名稱、序號** | 一次 cook 可能不只一個 job，在 CueGUI 裡要看得出來源 |

---

## 五、實作時確認的事

| 問題 | 結果 |
|---|---|
| 自訂 scheduler 要不要做 HDA | 不用。`pdg/types/` 下的 Python 檔註冊後，TOP 網路自動出現 `pdg_opencuescheduler` 節點，並帶有 `pdg_workingdir`、RPC 等通用參數 |
| `__PDG_HYTHON__` 等 token | ROP 類節點的指令是 `"__PDG_HYTHON__" "__PDG_SCRIPTDIR__/rop.py" json`：token 外面有引號，不能換成含空白的 `ocrun ...`。改為保留 `__PDG_HYTHON__`、`__PDG_PYTHON__`、`__PDG_HFS__`，由 `opencue_pdg_task.py` 查節點的 `dcc.toml` 換成實際路徑，並套用 `dcc.toml` 的 `[env]` |
| PDG 的腳本（`pdgcmd.py` 等） | `onStartCook` 呼叫 `_copyJobSupportFiles()`，複製到工作目錄下的 `scripts/`，農場直接讀 |
| 成功怎麼判定 | 以 frame 狀態為準：`SUCCEEDED` 回報成功，`DEAD`、`EATEN` 回報失敗（Local scheduler 也是看 exit code）。輸出檔與屬性由 work item 在結束前經 callback server 送回 |
| OpenCue 的自動重跑 | **關掉**（`maxretries=0`）。pyoutline 預設重跑 2 次，重跑會讓輸出檔被加兩次，失敗也要等重跑完才回報 |
| callback server 的位址 | 綁定所有介面，對外公布本機的完整主機名稱；port 可以限定範圍（scheduler 的 Callback Port 參數） |
| 查詢 frame | pycue 的 frame 搜尋預設只回傳 500 格，helper 依 job 的總格數指定上限 |

## 六、驗證結果

測試場景由 [`lab/make_pdg_test_scene.py`](lab/make_pdg_test_scene.py) 產生：Generic Generator → `work`（Python Script，外部程序，Hython）→ `collect`（Python Script，外部程序，PDG Python）。
以 [`lab/cook_pdg_node.py`](lab/cook_pdg_node.py)、[`lab/cancel_pdg_cook.py`](lab/cancel_pdg_cook.py) 在 hython 中 cook。Houdini 22.0.429，本機單一節點（8 核）。

| 情況 | 結果 |
|---|---|
| cook 第一個節點（5 個） | 一個 5 格的 job，全部成功；輸出檔路徑與屬性（`square`）回到 PDG |
| cook 下游節點 | `collect` 讀到上游的屬性與輸出檔；`__PDG_PYTHON__` 換成節點的 `python313\python.exe` |
| 部分 work item 失敗（exit 1） | 只有那兩個失敗，其他成功 |
| frame 在回報前被砍 | 該 work item 判定失敗，不必等它原本的 90 秒 |
| cook 途中取消 | PDG 顯示取消，OpenCue 的 job 被砍，節點上沒有殘留程序 |
| **300 個 work item** | **一個 300 格的 job**，全部成功，820 秒。每格約 22 秒，大部分是 hython 的啟動時間 |
| Houdini 21.0.729，從版本目錄 `2026.09.25.3` 以 package 載入 | 5 個全部成功，service 自動用 `houdini2107` |

新的 hython 工作階段 cook 下游時，上游會先重新 cook 一次（多一個 job）。在介面中同一個工作階段依序 cook 則不會。

### 尚未驗證

- 在 Houdini 介面中操作（包括 `getLogURI` 開啟 frame log）
- 節點與工作站是不同機器時，callback server 的連線與防火牆
- ROP Fetch、ROP Geometry 等實際的算圖節點
