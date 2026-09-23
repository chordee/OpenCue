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

詳見 `05` 的第 13、14 項。**結論：自建 image + registry 是必要步驟，不是選項。**

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

加進 `stack/opencue.portainer.yml` 的兩個服務，幾個刻意的決定：

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

`03` 曾記錄這是個地雷：Next.js 把 `NEXT_PUBLIC_*` 烘進 image，
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

這也再次佐證 `11` 第 2 點「一律使用 UNC」的規範 ——
它不只是為了可靠性，**更是跨平台 frame log 能運作的必要條件**。

### 尚未驗證

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
（`sandbox/README.md` 有說明，因為容器版 RQD 沒有 Blender，改由宿主算圖
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
