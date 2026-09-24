# 28 — Maya 算完圖後跳出 Autodesk 錯誤回報

正式做法整理在 [`notes/deploy/02-算圖節點.md` 第四節](../deploy/02-算圖節點.md#四設定-rqdconf)，本篇是查證紀錄。

環境：Maya 2027、本機 RQD，2026-09-25。

---

## 一、現象

跑 [`lab/check_submit_tools.py`](lab/check_submit_tools.py) `--submit` 時，桌面跳出 Autodesk Error Report 視窗。
但 Maya 的兩個 frame 都是 SUCCEEDED、exit 0，圖也都有輸出。

frame log 的時間：

```
01:00:03  frame 開始
01:00:08  Scene C:/opencue/scenes/test.ma completed.
01:00:09  （CER 啟動，見下）
01:00:25  frame 結束，exitStatus 0
```

算完之後才當掉，CER 收集資料多花了約 15 秒。

---

## 二、查證

### 1. 不是只有這一次

`%LOCALAPPDATA%\Autodesk\CER\` 底下同一個產品的當機報告，時間對應當天每一次 Maya 算圖：

| 時間 | 報告數 | job |
|---|---|---|
| 00:08 | 1 | `maya_render_2027`（[`26`](26-ocrun取代wrapper.md) 的實測） |
| 00:10 | 2 | 從投遞視窗送出的 2 格 |
| 01:00 | 2 | `check_maya` 的 2 格 |

**每一格 Maya 都會跳一次。** Windows 事件紀錄沒有任何紀錄，因為例外由 CER 自己攔下。

### 2. 當掉的不是 Maya 本體

`cer.log` 與報告內容：

```
cer.dll 來源      C:\Program Files (x86)\Common Files\Autodesk Shared\AdskLicensing\...\AdskLicensingAgent\cer.dll
UPI_PRODUCT       CLIC（Autodesk 授權模組，CLMV2 6.33.1.911）
exception code    0xE06D7363（未處理的 C++ 例外）
module            KERNELBASE.dll
暫存目錄          C:\opencue\tmp（frame 的 TMP）
```

是 Maya 程序裡載入的**授權模組**當掉，用的是它自己帶的 CER。

### 3. `MAYA_DISABLE_CER` 為什麼無效

- `ocrun` 確實有把 `MAYA_DISABLE_CER=1` 傳進 Maya（以 `ocrun maya 2027 mayapy` 印出確認）
- Maya 2027 的 `bin` 中，讀取這個變數的是 `ExtensionLayer.dll` 與 ATF 相關 DLL，也就是 Maya 本體的 CER
- 授權模組的 CER 在另一個安裝目錄，不讀這個變數

### 4. 找出缺少的環境變數

RQD 給 frame 的環境很少（`rqcore.py` 的 `__createEnvVariables()`，Windows 上只有
`SYSTEMROOT`、`APPDATA`、`TMP`、`COMMONPROGRAMFILES`、`SYSTEMDRIVE`，另加 PATH）。
直接執行 `ocrun maya 2027 Render -r sw -s 1 -e 1 ...`，只改環境變數：

| 環境 | 新的當機報告 |
|---|---|
| 完整的使用者環境 | 0 |
| 模擬 RQD 的環境 | **1** |
| RQD ＋ 16 個常見系統變數 | 0 |
| RQD ＋ `LOCALAPPDATA`、`USERPROFILE`、`PROGRAMDATA` | 1 |
| RQD ＋ `USERNAME` | 1 |
| RQD ＋ `COMPUTERNAME` | 1 |
| RQD ＋ `USERDOMAIN` | 1 |
| RQD ＋ `PROGRAMFILES`、`ProgramFiles(x86)` | 1 |
| RQD ＋ **`ALLUSERSPROFILE`** | **0** |

**只缺 `ALLUSERSPROFILE`。** 值相同的 `PROGRAMDATA` 沒有用，授權模組讀的是 `ALLUSERSPROFILE`。

---

## 三、修正

RQD 可以用 `rqd.conf` 的 `[UseHostEnvVar]` 區段，把 RQD 程序的指定變數帶給 frame
（`rqconstants.py` 讀成 `RQD_HOST_ENV_VARS`，`rqcore.py` 在建立 frame 環境時複製）：

```ini
[UseHostEnvVar]
ALLUSERSPROFILE
```

範本 [`node/rqd-windows.conf`](../deploy/node/rqd-windows.conf) 已加入。選擇在 RQD 層處理而不是在 `ocrun` 裡補，
原因是它對所有 frame 都有效，而且值直接取自主機，不必猜路徑。

刻意**不**加入 `USERPROFILE`、`LOCALAPPDATA`：它們指向登入中的使用者，
frame 會讀到 artist 的 Maya 偏好設定與外掛，算圖結果可能因人而異。

### 驗證

重啟 RQD 後送出 3 格 Maya（[`lab/submit_dcc.py`](lab/submit_dcc.py) `maya --frames 1-3`）：

| 項目 | 修正前 | 修正後 |
|---|---|---|
| 每格時間 | 約 22 秒 | 14～15 秒 |
| CER 啟動 | 每格一次 | **0 次**（`cer.log` 在 RQD 重啟後沒有新的啟動紀錄） |
| 錯誤回報視窗 | 每格一個 | 沒有 |

---

## 四、與 [`25`](25-Maya內投遞.md) 的關係

[`25` 第五節](25-Maya內投遞.md#五人工測試中發現的問題)的回報視窗當時歸因於記憶體耗盡。
那次的事件紀錄有 `mayabatch.exe` 的 `0xc0000005`，與本篇的 `0xE06D7363` 不同，記憶體耗盡確實存在。
但授權模組的 `cer.log` 顯示，那兩次人工測試也都有本篇的當機：

| 測試（本地時間） | 授權模組送出的 dump |
|---|---|
| 22:00 前後（記憶體耗盡那次） | 17 |
| 22:31（事件紀錄完全沒有當機） | 8 |

兩種原因疊在一起。`cer.log` 裡 frame 的時間是 PDT（RQD 替 frame 設定了 `TZ`），比本地時間慢 15 小時，
對照時要換算；直接在命令列執行的測試則是本地時間。

---

## 五、尚未驗證

- `ALLUSERSPROFILE` 以外，授權模組在其他情況（例如網路授權、授權伺服器斷線）還需要什麼
- Maya 本體真的當掉時，`MAYA_DISABLE_CER` 是否能關掉 Maya 本體的回報視窗
- 其他 Autodesk 產品（Arnold 獨立版等）與其他 Maya 版本
