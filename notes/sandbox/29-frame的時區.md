# 29 — frame 的時區被寫死為美西時間

正式做法整理在 [`notes/deploy/02-算圖節點.md` 第四節](../deploy/02-算圖節點.md#四設定-rqdconf)，本篇是查證紀錄。

環境：本機 Windows RQD，2026-09-25。

---

## 一、發現經過

查 [`28`](28-Maya結束時跳出錯誤回報.md) 的當機紀錄時，發現 frame 裡的 CER 紀錄時間比本地時間慢 15 小時，
直接在命令列執行的則是本地時間。

原因在 RQD（`rqd/rqd/rqcore.py` 的 `__createEnvVariables()`）：

```python
self.frameEnv["TZ"] = self.rqCore.machine.getTimezone()
```

```python
# rqd/rqd/rqmachine.py
def getTimezone(self):
    if time.tzname[0] == 'IST':
        return 'IST'
    return 'PST8PDT'
```

除了主機時區名稱是 `IST` 的情況，**所有 frame 都拿到 `TZ=PST8PDT`**，不看主機的時區設定。

---

## 二、實測

在 frame 裡用 hython 印出 `TZ` 與本地時間（`C:\opencue\tmp\tzcheck.py`）：

| | `TZ` | frame 裡的本地時間 | 主機時間 |
|---|---|---|---|
| 修正前 | `'PST8PDT'` | **2026-09-24 10:22** | 2026-09-25 01:22 |
| 修正後 | `''` | 2026-09-25 01:22 | 2026-09-25 01:22 |

修正前連日期都錯。影響範圍：

- 算圖腳本用本地時間產生的檔名、資料夾名稱（例如以日期分類的輸出）
- DCC 與外掛寫進 log 的時間，與主機、Cuebot 的時間對不起來
- 檔案本身的修改時間不受影響（Windows 以 UTC 記錄）

---

## 三、修正

`rqd.conf` 的 `[UseHostEnvVar]` 區段列入 `TZ`：

```ini
[UseHostEnvVar]
ALLUSERSPROFILE
TZ
```

`rqcore.py` 先寫入 `PST8PDT`，之後複製 `[UseHostEnvVar]` 的變數時會蓋掉它。
Windows 主機通常沒有 `TZ` 變數，RQD 以空字串帶入（`os.environ.get(variable, '')`）；
空的 `TZ` 會讓程式改用 Windows 的時區設定。

修正後再跑一格 Maya（`-r sw`），13 秒完成，沒有其他影響。

---

## 四、尚未驗證

- Maya、Nuke 內部自己的時間顯示（本篇以 hython 的 Python 驗證）
- 以 Windows 服務執行 RQD 時（服務帳號的環境）是否同樣沒有 `TZ`
- Linux 節點：Linux 上空的 `TZ` 代表 UTC，不是系統時區，**不能照搬**這個做法，
  要改為在 RQD 的啟動環境設定正確的 `TZ`（例如 `Asia/Taipei`）再列入 `[UseHostEnvVar]`
