# 13 — CueWeb 與 REST Gateway

## 重大發現：沒有預建 image，必須自行 build

原本打算直接拉官方 image，實測發現**根本沒有發布**：

```
opencue/cuebot        -> HTTP 200
opencue/rqd           -> HTTP 200
opencue/cueweb        -> HTTP 404
opencue/rest-gateway  -> HTTP 404
```

而 compose 裡明明寫著 `image: opencue/cueweb:latest`。
錯誤訊息還會誤導：

```
pull access denied for opencue/cueweb, repository does not exist
or may require 'docker login'
```

容易被誤判成自己帳號權限不足。

詳見 [`05`](05-可回饋上游的問題.md) 的第 13、14 項。**結論：自建 image + registry 是必要步驟，不是選項。**

### 自行 build 的好處（不只是沒得選）

| 好處 | 說明 |
|---|---|
| 版本一致 | 公開的 `opencue/cuebot` 最新 tag 是 `1.19.1`，而 master 建出來是 `1.34.4` |
| **認證必須 build** | `NEXT_PUBLIC_AUTH_PROVIDER`（github/okta/google/ldap）是 **build arg**。要啟用 CueWeb 登入，就一定得自行建置，改環境變數無效 |
| 客製化 | log 編輯器連結、預覽程式、CueProgBar 指令等都是 build arg |
| 供應鏈控管 | base image 更新、內部政策 |

Build 出來的大小：

```
opencue/cueweb:latest        2.52 GB
opencue/rest-gateway:latest   184 MB
```

CueWeb 是 Next.js，**build 時 Node 會吃掉數 GB 記憶體** ——
本次第一輪 build 就因為機器記憶體見底而被系統中止。建置機器要留足餘裕。

## Stack 設計

加進 `notes/deploy/server/opencue.portainer.yml` 的兩個服務，幾個刻意的決定：

### REST Gateway 不對外 publish

```yaml
rest-gateway:
  image: ${OPENCUE_REST_GATEWAY_IMAGE}
  environment:
    CUEBOT_ENDPOINT: cuebot:8443
    JWT_SECRET: ${JWT_SECRET}
  # 沒有 ports:
```

只有同一個 network 上的 CueWeb 需要它。部署後確認：

```
NAMES                  STATUS          PORTS
opencue-cueweb         Up (healthy)    0.0.0.0:3000->3000/tcp
opencue-rest-gateway   Up (healthy)    8448/tcp          <- 無對外映射
opencue-cuebot         Up (healthy)    0.0.0.0:8443->8443/tcp
opencue-db             Up (healthy)    5432/tcp          <- 無對外映射
```

若 pipeline 需要直接呼叫 REST API，再自行加上 `ports` 並置於反向代理後。

### NEXT_PUBLIC_* 的 build-time 問題其實已被官方繞過

[`03`](03-容器說明.md) 曾記錄這是個地雷：Next.js 把 `NEXT_PUBLIC_*` 烘進 image，
若烘的是 `localhost:8448`，換部署位置就 `ECONNREFUSED`。

實際看設定後發現官方的處理是對的：

```yaml
NEXT_PUBLIC_OPENCUE_ENDPOINT: http://rest-gateway:8448
NEXT_PUBLIC_URL: ""          # 空值 = 瀏覽器用同源相對路徑
```

- **瀏覽器**打 CueWeb 自己的 `/api/...`（同源相對路徑）
- **Next.js 伺服器端**再去呼叫 `rest-gateway:8448`

所以那個容器名稱只在伺服器端使用，瀏覽器不需要解析它，**換部署位置不必重建
image**。

**但若把 `NEXT_PUBLIC_URL` 設成絕對網址，就會重新引入這個問題。** 別設。

## REST Gateway 的 JWT 驗證

從同一個 network 的容器測試（因為沒有對外 publish）：

```bash
docker run --rm --network opencue curlimages/curl -s \
  -X POST http://rest-gateway:8448/show.ShowInterface/GetShows \
  -H "Authorization: Bearer $TOKEN" -d '{}'
```

| 情境 | 結果 |
|---|---|
| 無 token | **HTTP 401** |
| 有效 token | 回傳 show 資料 JSON |

**安全注意**：產生 token 時 PyJWT 警告

```
InsecureKeyLengthWarning: The HMAC key is 20 bytes long, which is below the
minimum recommended length of 32 bytes for SHA256.
```

官方預設的 `opencue-dev-jwt-secret-change-in-production` 也只有 44 bytes，
但字面就寫著要換掉。**正式環境的 `JWT_SECRET` 至少 32 bytes 的隨機值。**

## CueWeb 功能驗證

```
首頁                   HTTP 200
/api/job/getjobs       回傳完整 job 清單
```

實際取得先前跑過的三個 DCC job（Houdini / Maya / Nuke），欄位正確。

**尚未做視覺確認** —— 介面實際長相、表格、操作是否正常，需要人工開
`http://localhost:3000` 檢視。

## 跨平台 frame log：問題與解法

### 問題

`/api/job/getjobs` 回傳的 job 資料裡：

```json
"logDir": "C:/opencue/logs/testing/testshot/logs/..."
```

Cuebot 記錄的是「**render node 寫入時的路徑**」。我們的 render node 是
Windows，所以存的是 Windows 路徑。而 CueWeb 跑在 Linux 容器裡。

實測：

```
GET /api/getlog?path=C:/opencue/logs/...
-> HTTP 400 {"error":"Query parameter 'path' is required"}
```

**根因**（`cueweb/app/api/getlog/route.ts:66`）：

```javascript
if (!filePath || filePath.includes("\0") || !path.isAbsolute(filePath)) {
  return NextResponse.json({ error: "..." }, { status: 400 });
}
```

在 Linux 上 `C:/opencue/logs/...` **不是絕對路徑**（沒有以 `/` 開頭），
直接被擋下。CueWeb **沒有任何路徑對應（path mapping）功能**。

值得注意的是，log 檔其實**掛進容器了**：

```bash
docker exec opencue-cueweb ls /mnt/logs/
testing
```

檔案在，只是 CueWeb 照著 `C:/...` 去找。

### 解法：CUE_FRAME_LOG_DIR 用 UNC 路徑

關鍵觀察：**`//` 開頭的路徑在 Linux 上也是合法的絕對路徑。**

實測（同一個檔案，兩種寫法）：

```
GET /api/getlog?path=/mnt/logs/.../xxx.rqlog    -> HTTP 200
GET /api/getlog?path=//mnt/logs/.../xxx.rqlog   -> HTTP 200
```

所以把 `CUE_FRAME_LOG_DIR` 設成 UNC 路徑：

```
CUE_FRAME_LOG_DIR=//fileserver/opencue/logs
```

| 端點 | 解析結果 |
|---|---|
| Windows RQD | `\fileserver\opencue\logs\...` —— UNC，寫入共享儲存 ✅ |
| Linux CueWeb 容器 | 把同一個共享掛在 `/fileserver/opencue/logs`，而 `//fileserver/...` 解析得到 ✅ |

**同一個路徑字串在兩個平台都成立。**

這也再次佐證 [`11`](11-正式部署風險與待辦.md) 第 2 點「一律使用 UNC」的規範 ——
它不只是為了可靠性，**更是跨平台 frame log 能運作的必要條件**。

### 尚未驗證

> **注意**：本節寫於當時，部分項目後來已補測完成。
> **最新的驗證狀態以 [`19-驗證狀態總表.md`](19-驗證狀態總表.md) 為準。**


這個解法的 Linux 端已實測（`//` 前綴可行），但**完整鏈路需要真的有 SMB 共享
才能驗證**：Windows RQD 寫入 UNC、Linux 容器掛載同一個共享、CueWeb 讀取。
本機沒有檔案伺服器，留待正式環境。

## Docker Desktop 的路徑轉換陷阱

把 log 目錄掛進 CueWeb 時踩到的：

從 WSL 執行 `docker compose` 時，Docker Desktop 會把 `/mnt/c/...` 轉換成
Windows 路徑。**但 Portainer 是直接對 daemon 下指令，沒有這層轉換。**

所以 bind mount 的來源要用 daemon 看得到的路徑：

```
/run/desktop/mnt/host/c/opencue/logs      <- 可行
/mnt/c/opencue/logs                       <- 透過 Portainer 無效
```

**正式的 Linux 宿主沒有這一層**，直接填實際掛載點即可。
這純粹是 Docker Desktop 的測試環境限制，記下來避免日後誤判。

---

## 修正：兩個白名單變數負責不同端點

初版把 `CUEWEB_PREVIEW_ROOTS` 指向 log 目錄，是錯的。查證原始碼後釐清：

| 變數 | 使用的路由 | 未設定時的行為 | 用途 |
|---|---|---|---|
| `CUEWEB_LOG_ROOTS` | `api/getlog/route.ts:50`、`api/stuck-frames/lastline/route.ts:29` | **不限制** | frame 的文字 log（`.rqlog`）讀取與下載 |
| `CUEWEB_PREVIEW_ROOTS` | `api/frame/preview/route.ts:48` | **一律拒絕（403）** | 算圖成果的圖片縮圖預覽 |

`preview/route.ts:92-96` 的註解說明了為何 fail-closed：

```javascript
// Fail closed: serving an arbitrary absolute path (even an auth'd one) would
// expose any web-renderable image on the server filesystem. Require an
// explicit CUEWEB_PREVIEW_ROOTS allow-list; without it the route serves nothing.
```

而 `getlog/route.ts:44-47` 相反：

```javascript
// Optional per-site allow-list ... When set, only files under one of these
// roots are served; when unset, reads aren't restricted to a root (job log
// paths are site-specific).
```

### 安全影響：不設 CUEWEB_LOG_ROOTS 等於開放任意檔案讀取

因為 log 的白名單預設是**開放**的，未設定時任何能開啟 CueWeb 的人
都能透過 `/api/getlog?path=...` 讀取容器內的任意絕對路徑。

設定後實測：

```
/api/getlog?path=/mnt/logs/.../xxx.rqlog   -> HTTP 200
/api/getlog?path=/etc/passwd               -> HTTP 403
```

**正式環境務必設定 `CUEWEB_LOG_ROOTS`。**

### 為什麼官方 sandbox 把 PREVIEW_ROOTS 指向 log 目錄

不是筆誤 —— sandbox 的 Blender demo 刻意把算好的圖寫進 `/tmp/rqd/logs`
（[`sandbox/README.md`](../../sandbox/README.md) 有說明，因為容器版 RQD 沒有 Blender，改由宿主算圖
並寫進 CueWeb 唯讀掛載的那個目錄）。

**正式環境算圖輸出是獨立的共享**，兩者應分開掛載。

### 修正後的設定

```yaml
environment:
  CUEWEB_LOG_ROOTS: ${CUEWEB_LOG_ROOTS}          # -> /mnt/logs
  CUEWEB_PREVIEW_ROOTS: ${CUEWEB_PREVIEW_ROOTS}  # -> /mnt/render
volumes:
  - ${FRAME_LOG_MOUNT_SOURCE}:${FRAME_LOG_MOUNT_TARGET}:ro
  - ${RENDER_OUT_MOUNT_SOURCE}:${RENDER_OUT_MOUNT_TARGET}:ro
```

驗證（用先前 Nuke job 算出來的 PNG）：

```
/api/frame/preview?path=/mnt/render/nuke/nuke.0001.png
-> HTTP 200  content-type: image/png  74615 bytes
```

大小與 render node 上的輸出檔完全一致。

**注意**：預覽路由只服務網頁可顯示的格式（png / jpeg / webp / bmp / avif，
刻意排除 svg 以免同源執行腳本）。**EXR 不在其中** ——
Houdini/Karma 輸出 EXR 的話，網頁預覽需要另外產生代理圖（proxy / thumbnail）。

---

## EXR 預覽：為什麼看不到，以及三種解法

### 先釐清：這不是 CueWeb 的限制

**所有瀏覽器都沒有 EXR 解碼器。** `<img src="....exr">` 在任何網頁上都顯示不出來，
不只是 CueWeb。

CueWeb 的預覽路由（`cueweb/app/api/frame/preview/route.ts:35-45`）
明確列出它服務的格式：

```javascript
const MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  bmp: "image/bmp",
  avif: "image/avif",
  // SVG 刻意排除：同源提供 SVG 等於允許執行腳本
};
```

遇到不在清單內的副檔名會回 **HTTP 415**，訊息是
`Preview not supported in browser for this format`（`route.ts:125`），
前端據此顯示「無法預覽」的替代畫面。

**這是刻意設計，不是 bug。**

### 解法一：交給本機看圖程式（建議優先採用，不需改任何程式碼）

CueWeb 本來就內建這條路。Frame 選單的「Preview All」會使用兩個 build arg：

| 變數 | 用途 | 預設值 |
|---|---|---|
| `NEXT_PUBLIC_PREVIEW_COMMAND` | 對話框中**顯示並可複製**的指令 | `rv {paths}` |
| `NEXT_PUBLIC_PREVIEW_URL` | Launch 按鈕呼叫的 **URL scheme** | 空（不顯示按鈕） |

可用的佔位符：`{paths}` `{job}` `{layer}` `{frame}`。

實作位置：`cueweb/components/ui/frame-extra-dialogs.tsx:59-60`。

**為什麼建議優先做這個**：

- 完全不用改程式碼，只是 build arg
- artist 用的是 **RV / xSTUDIO 這類專業看圖程式**，功能遠勝網頁預覽
  （曝光調整、channel 切換、比對、色彩管理）
- 沒有傳輸大檔的問題

設定方式（build 時）：

```bash
docker compose build cueweb \
  --build-arg NEXT_PUBLIC_PREVIEW_COMMAND='rv {paths}' \
  --build-arg NEXT_PUBLIC_PREVIEW_URL='openrv://{paths}'
```

若要用 URL scheme 的 Launch 按鈕，需要在每台 artist 機器上
**註冊該 scheme 的處理程式**（Windows 的登錄檔設定）。
若嫌麻煩，只留 `PREVIEW_COMMAND` 讓使用者複製貼上也可行。

**注意這兩個是 build arg，改環境變數無效**（見本文件前段關於
`NEXT_PUBLIC_*` 的說明）。

### 解法二：伺服器端轉檔（要改 CueWeb，但改動很小）

在預覽路由裡把 EXR 解碼成 PNG 再回傳。
**前端完全不用動** —— 它只是一個 `<img src="/api/frame/preview?path=...">`。

#### 可行性實測

CueWeb 的 base image 是 **Alpine Linux**，實測裡面沒有任何轉檔工具：

```
無 oiiotool / 無 ffmpeg / 無 convert / 無 magick
```

`package.json` 也沒有 `sharp`、`three` 等影像套件。

但 Alpine 的 `ffmpeg` 套件可以解 EXR，實測用本次 husk 算出來的檔案：

```
輸入: husk.0001.exr  916 KB
      Stream: exr, gbrapf16le(linear), 1280x720

直接轉             plain.png   2,061,637 bytes
-apply_trc sRGB    trc.png     1,921,973 bytes
-vf eq=gamma=2.2   gamma.png     508,788 bytes
縮圖 320 寬        thumb.png     120,465 bytes
```

#### 重要細節：EXR 是線性 HDR，直接轉會太暗

必須做色彩轉換。而 **`-apply_trc` 是解碼器選項，一定要放在 `-i` 之前**：

```bash
# 正確
ffmpeg -apply_trc iec61966_2_1 -i in.exr -vf scale=320:-1 out.png

# 錯誤（會失敗：Error while filtering）
ffmpeg -i in.exr -vf scale=320:-1 -apply_trc iec61966_2_1 out.png
```

#### 要改的地方

1. `cueweb/Dockerfile` 加 `RUN apk add --no-cache ffmpeg`
2. `route.ts` 的 `MIME` 表加入 `exr`
3. 遇到 `exr` 時先轉成暫存 PNG，回傳 `image/png`

建議**只產小縮圖**（320 寬約 120 KB），不要回傳全尺寸 ——
預覽面板本來就只是確認「這格算對了沒」。

正式做的時候要考慮：轉檔的 CPU 成本、是否加快取、多層（multi-part）EXR
與 AOV 怎麼選。OpenImageIO 的 `oiiotool` 在這些方面比 ffmpeg 正確，
但不在 Alpine 主套件庫內，要自行編譯或換 base image。

### 解法三：瀏覽器端解碼（功能最好，工程量最大）

把原始 EXR 位元組送到瀏覽器，用 JS/WASM 解碼器
（例如 three.js 的 `EXRLoader`）畫到 `<canvas>`。

| 優點 | 缺點 |
|---|---|
| **保留 HDR 資料**，可做曝光／gamma 即時調整 | 要改前端，工程量大 |
| 可切換 channel（R/G/B/A/Z、各 AOV） | 增加 bundle 大小 |
| 伺服器沒有轉檔負擔 | **大檔整個傳到瀏覽器**，4K 多 AOV 可能上百 MB |

對 VFX 來說這是功能最完整的做法，但考量到 artist 手邊本來就有
RV / xSTUDIO，投資報酬率不高。

### 建議的優先順序

| 順位 | 做法 | 工程量 |
|---|---|---|
| 1 | 設定 `NEXT_PUBLIC_PREVIEW_COMMAND` / `_URL` 指向本機看圖程式 | 只是 build arg |
| 2 | 伺服器端轉小縮圖（若真的需要在網頁上快速確認） | Dockerfile 一行 + route 一小段 |
| 3 | 瀏覽器端 EXR 解碼 | 前端改動大，通常不划算 |

**先做第 1 項。** 多數情況它就夠了，而且今天就能做 —— 反正 CueWeb
本來就必須自行 build（見本文件開頭）。

---

## CueWeb 的投遞功能（CueSubmit 頁面）

CueWeb 內建投遞頁面（`app/cuesubmit/page.tsx`），**不需要安裝桌面版 CueSubmit
就能從瀏覽器投 job**。對 artist 來說門檻最低。

實測可用，但**有幾個對混合農場關鍵的限制**。

### 欄位說明

**Job Info**

| 欄位 | 說明 |
|---|---|
| Job Name / Show / Shot | 自訂 |
| Facility | 下拉選單，選 `local` |
| **Username** | 有啟用認證時自動帶入（email 的 `@` 前半段）。**未啟用認證時為空白且可編輯** |

**Username 要填什麼**：填**實際會在 render node 上被建立的使用者名稱**。

這個值會成為 job 的 `str_user`，而 **RQD 會拿它去建立同名使用者**
（見 [`04`](04-部署過程.md) 坑 #4）。填一個節點上沒處理過的名字，
在 Linux 節點會觸發 `useradd` 失敗導致 frame 被 abort。

**Layer Info**

| 欄位 | 說明 |
|---|---|
| **Layer Name**（必填） | **至少 3 個字元** —— 少於 3 個會被 Cuebot 拒絕：`The layer name must be at least 3 characters` |
| **Frame Spec**（必填） | 例如 `1-100` |
| Command | 執行指令 |
| Dependency Type | 多層時才需要 |
| Chunk Size | 一個 frame 處理幾格 |
| **Memory** | **預設 256m，一定要改**，見下 |
| Job Type / Services / Limits | 選填 |
| Override Cores | 選填 |

### 限制一：沒有 layer tag 欄位

這是對混合農場**最關鍵的限制**。

實測從 CueWeb 投出的 job，其 layer tags 是：

```
general | desktop
```

**沒有辦法指定 DCC 版本或平台的 tag。** 而 tag 是 regex 的「或」比對
（見 [`12`](12-真實DCC算圖.md)），所以任何帶 `general` 的節點都會收下。

實測後果：一個要跑 Windows 包裝腳本的 job，被派到了 Linux 容器節點：

```
/tmp/0002-houdini_render.sh: line 17:
C:/opencue/bin/hython-22.0.429.bat: No such file or directory
exitStatus 127
```

三個 frame 全部 DEAD。

**鎖住不該收工作的節點後重試**（`cueman -force -retry`），
三個 frame 立刻在 Windows 節點上成功完成 —— 證明 job 定義本身沒問題，
問題純粹是無法指定 tag。

### 限制二：沒有 OS 欄位

連帶影響 per-OS 的 frame log 路徑對應（見 [`12`](12-真實DCC算圖.md)）。

實測那批失敗的 frame，log 落在 Linux 節點的：

```
/app/C:/opencue/logs/testing/testshot/logs/...
```

因為 job 沒有 `os`，per-OS 的對應沒生效，退回 `default_os`
（Windows 路徑），Linux 節點把它當相對路徑處理。

### 限制三：Memory 預設 256 MB 太小

**這一項在單一平台的農場也會出事。**

實測 Houdini 的 frame：

| | 值 |
|---|---|
| `int_mem_min`（宣告需求） | **256 MB** |
| `int_mem_max_used`（實際用量） | **約 1,080 MB** |

**超出 4 倍，但 frame 沒有被砍。** 原因是
`opencue.properties:261`：

```properties
# How much can a frame exceed its reserved memory.
#  - -1.0 makes the feature inactive
dispatcher.oom_frame_overboard_allowed_threshold=-1.0
```

這個功能**預設關閉**（註解說明是為了改善重試邏輯而暫時停用）。

**但不代表可以隨便填。** 真正的風險是 Cuebot 的資源帳目失真：

| | Cuebot 以為 | 實際 |
|---|---|---|
| 每個 frame 佔用 | 256 MB | 1,080 MB |
| 節點還剩多少記憶體 | 很多 | 快用完了 |

Cuebot 會繼續往那台節點派工，直到**真的 OOM** ——
屆時觸發的是作業系統層級的 oom-killer 或 Windows 記憶體壓力，
那種失敗比「frame 被 Cuebot 砍掉」難查得多。

最後防線是這兩個設定，但它們是在節點**實際**用量超標時才介入：

```properties
dispatcher.oom_max_safe_used_physical_memory_threshold=0.9
dispatcher.oom_max_safe_used_swap_memory_threshold=0.05
```

**結論：Memory 欄位一定要填實際值。** Houdini 約 `2g`。

### 適用範圍的判斷

| 農場型態 | CueWeb 投遞 |
|---|---|
| 單一平台、單一 DCC 版本 | **可用**，只要記得填 Memory |
| 多版本 DCC 並存 | **不適用** —— 無法指定版本 tag |
| 混合作業系統 | **不適用** —— 無法指定 OS |

**本專案屬於「多版本 DCC」**，所以正式投遞應使用 pyoutline 腳本
（`notes/sandbox/lab/submit_dcc.py`）或 DCC 內嵌外掛，
CueWeb 的投遞頁面適合臨時測試或簡單工作。
