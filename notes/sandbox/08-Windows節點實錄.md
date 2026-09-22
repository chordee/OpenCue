# 08 — Windows render node 實錄

驗證目標：**Docker 裡的 Cuebot 當 server，Windows 機器當 render node ＋ workstation。**
這正是最終要部署的架構。

結論：**可行，frame 確實在 Windows 上執行完成。**
但過程踩到五個坑，其中兩個在正式環境一定會再遇到。

## 架構

```
Docker（Portainer stack「opencue」）        Windows 主機
  ├── opencue-db      (5432 不對外)          ├── RQD（原生，Python 版）
  ├── opencue-flyway  (one-shot)             │    監聽 8444
  └── opencue-cuebot  (8443 對外)  ←─gRPC──→ └── 工作站用戶端（venv）
```

## 安裝

用 Windows 原生 Python 3.11.9 建 venv（**不是 WSL**）：

```bash
python -m venv C:\Users\<user>\opencue-win-venv
C:\Users\<user>\opencue-win-venv\Scripts\python.exe -m pip install ./proto ./rqd
```

裝的是 **Python 版 RQD**（`rqd/`），不是 Rust 版。理由：
- `sandbox/rqd_windows.conf` 用的是 Python RQD 的 `[Override]` INI 格式
- Rust RQD 的 `run_as_user` 明確標示 Windows 尚未支援
  （`rust/crates/rqd/src/frame/running_frame.rs:942`）

### 坑 #5：Windows 相依套件沒有宣告

第一次啟動直接 crash：

```
File "rqd/rqmachine.py", line 762, in __updateProcsMappingsFromWindows
    import wmi
ModuleNotFoundError: No module named 'wmi'
```

`rqd/pyproject.toml` 的 `dependencies` 只有 `opencue_proto / psutil / pynput / future`，
**沒有任何 Windows 專用相依**。但 `rqmachine.py` 在 Windows 路徑上會 `import wmi`。

手動補上即可：

```bash
pip install wmi pywin32
```

**這是可回饋上游的項目**：應加上條件式相依

```toml
dependencies = [
    ...,
    "wmi; sys_platform == 'win32'",
    "pywin32; sys_platform == 'win32'",
]
```

## 設定

設定檔位置（`rqconstants.py:145`）：`%LOCALAPPDATA%\OpenCue\rqd.conf`，
也可用 `RQD_CONFIG_FILE` 環境變數或 `-c` 參數指定。

範本見 `notes/sandbox/stack/rqd-windows.conf`。關鍵三項：

| 設定 | 值 | 說明 |
|---|---|---|
| `OVERRIDE_CUEBOT` | `localhost` | Cuebot 位置。正式環境填那台 Linux 主機的名稱或 IP |
| `OVERRIDE_HOSTNAME` | `LAPTOP-ULJICLO8` | **回報給 Cuebot 的名稱，見下方坑 #6** |
| `RQD_BECOME_JOB_USER` | `False` | Windows 上不做 user 切換 |

### 坑 #6：Cuebot 把主機名稱截成第一段，且必須在容器內解析得到

一開始把 `OVERRIDE_HOSTNAME` 設成 `host.docker.internal`（容器連回宿主的標準名稱）。

`rqd/rqd/rqutil.py:207` 的 `getHostname()` 是**原樣回傳** `OVERRIDE_HOSTNAME`，
不做處理。但 `cueadmin -lh` 顯示的主機名稱變成 **`host`** ——
**是 Cuebot 那端把 FQDN 截成第一個 label**。

而 Cuebot 會用「它存起來的那個短名稱」回連 8444：

```
docker exec opencue-cuebot getent hosts host
  → NO-RESOLVE
docker exec opencue-cuebot getent hosts host.docker.internal
  → 192.168.65.254
```

所以 frame 派不出去（症狀與 `04` 的坑 #3 相同）。

**修法**：改用**單段**的實際主機名稱，並在 cuebot 服務加 `extra_hosts`：

```yaml
cuebot:
  extra_hosts:
    - "${RENDER_NODE_NAME}:${RENDER_NODE_ADDR}"
```

（本次測試 render node 就是 Docker 宿主本身，所以 `RENDER_NODE_ADDR=host-gateway`。）

**對正式環境的意義（重要）**：
每一台 Windows 節點回報的**短主機名稱**，都必須在 **Cuebot 容器內**解析得到。
容器不一定會繼承宿主的 DNS search domain，所以即使公司 DNS 正常，
容器內用短名稱查詢仍可能失敗。

部署前要驗證的一行指令：

```bash
docker exec opencue-cuebot getent hosts <windows節點短名稱>
```

若查不到，解法是設定容器的 DNS search domain，或在 compose 逐一列 `extra_hosts`。

驗證回連是否真的通：

```bash
docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/<節點名稱>/8444" && echo OK || echo FAIL'
```

### 坑 #7：Linux 風格的 log 路徑在 Windows 上落到「當前磁碟機」

Cuebot 設定 `CUE_FRAME_LOG_DIR=/tmp/rqd/logs`。Windows RQD 收到這個路徑後，
Python 把它解析成**相對於當前磁碟機的絕對路徑**。

本次 RQD 從 `D:\dev\OpenCue` 啟動，結果 log 落在：

```
D:\tmp\rqd\logs\testing\testshot\logs\<job>--<id>\<job>.<frame>.rqlog
```

**不會報錯，就是安靜地寫到別的地方。** 換個工作目錄啟動，或改以服務方式啟動，
log 就跑到另一個磁碟機。而 Cuebot 與 CueWeb 記錄的仍是 `/tmp/rqd/logs/...`，
兩邊對不上，之後就是「log 開不起來」。

log 檔內也看得到這個混合路徑：

```
logDestination  /tmp/rqd/logs/testing/testshot/logs/<job>--<id>\<job>.<frame>.rqlog
```

前半是 Linux 斜線、後半是 Windows 反斜線。

**正式環境必須**：把 `CUE_FRAME_LOG_DIR` 設成所有節點都寫得到的共享儲存路徑
（UNC 或每台一致的磁碟機代號），而不是留著預設的 `/tmp/rqd/logs`。

### 坑 #8：PATH 污染（自己造成的，但值得記）

第一次的測試指令 `cmd /c timeout /t 3 /nobreak` 失敗：

```
D:\dev\OpenCue>cmd /c timeout /t 3 /nobreak
timeout: invalid time interval '/t'
```

這是 **GNU coreutils 的 `timeout`**，不是 Windows 的 `timeout.exe` ——
因為 RQD 是從 Git Bash 啟動的，繼承了含 `C:\Program Files\Git\usr\bin` 的 PATH，
而 `RQD_USE_PATH_ENV_VAR=1` 把這個污染直接傳給 frame。

**教訓**：Windows 節點的 RQD 應該以**乾淨的環境**啟動（Windows 服務或排程工作），
不要從開發者的 shell 啟動。否則每台機器的 frame 執行環境都不一樣。

### 坑 #9：`--command` 的引號會被 shlex 吃掉

`load_test_jobs.py --command` 用 `shlex` 切分，所以

```bash
--command "python.exe -c import time;time.sleep(3)"
```

會被切成獨立的 token，python 收到 `import` 當腳本 → `SyntaxError`。

測試用的指令改成呼叫腳本檔最單純：

```bash
--command "C:/Users/chordee/opencue-win-venv/Scripts/python.exe C:/tmp/rqd/testframe.py"
```

## 成功結果

frame log（`D:\tmp\rqd\logs\...\0001-test_layer.rqlog`）：

```
=== OpenCue test frame ===
system : Windows 10
node   : LAPTOP-ULJICLO8
python : 3.11.9
cwd    : D:\dev\OpenCue
frame  : 0001-test_layer
show   : testing
=== frame done ===

RenderQ Job Complete
exitStatus          0
renderhost          LAPTOP-ULJICLO8
```

3 個 frame 全部 SUCCEEDED。**整條鏈路打通**：
Linux 容器內的 Cuebot 排程 → 派給 Windows 原生 RQD → 在 Windows 上執行 Python →
寫 log → 回報完成。

## 待確認的觀察：cwd 似乎沒有生效

frame log 的 JobSpec 宣告：

```
cwd  C:\Users\chordee\AppData\Local\Temp/testing-testshot-.../0001-test_layer
```

但 frame 內 `os.getcwd()` 實際印出 `D:\dev\OpenCue`（也就是 RQD 行程自己的
工作目錄）。看起來 Windows 上 RQD 沒有實際切換 frame 的工作目錄。

**影響**：依賴相對路徑的算圖工作會找不到檔案。

**尚未確認**是 RQD 的問題、還是我們啟動方式造成的，需要再測一次
（以乾淨環境啟動 RQD 後重驗）。在確認之前不列入上游回報清單。

## 仍未驗證

| 項目 | 說明 |
|---|---|
| 真正的跨機器 | 本次 Windows 就是 Docker 宿主本身，靠 `host-gateway`。真實環境是不同實體機器走區網 |
| NIMBY | 設定裡先關掉了。工作站行為（有人在用就讓出資源）尚未驗證 |
| CueNIMBY | 給使用者的系統列工具，未安裝測試 |
| 服務化 | RQD 以 Windows 服務常駐啟動的方式未測（但坑 #7、#8 都指向這是必要的） |
| 真實算圖軟體 | 本次 frame 只跑 Python 腳本，未測 Blender/Maya/Nuke |
