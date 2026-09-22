# 01 — 平台差異與 Portainer 注意事項

這份記錄官方 `docker-compose.yml`（repo 根目錄）裡**只適合 sandbox、搬到正式
Linux 宿主或 Portainer 會出問題**的地方。測試階段先照原樣跑通，但每一項都要知道
正式環境該怎麼改。

## 一、`build:` vs `image:`

現況：`cuebot`、`flyway`、`rqd` 三個服務都用 `build:` 從原始碼編譯。

```yaml
cuebot:
  build:
    context: ./
    dockerfile: ./cuebot/Dockerfile
  # image: opencue/cuebot   <- 官方註解掉的選項
```

**為什麼是問題**：Portainer 部署 stack 時，`build:` 需要宿主端有完整 build context
（整個 repo），而 Portainer 的 stack 通常只餵一份 compose 檔。即使用 Git repository
方式部署，build 也會拖慢部署、且在宿主上留下建置產物。

**正式環境做法**：CI 先把 image 建好推到 registry（Docker Hub 的 `opencue/cuebot`
或自架 registry），compose 只留 `image:` + 明確 tag（不要用 `latest`）。

## 二、`${HOME}` 環境變數

現況：

```yaml
rqd:
  volumes:
    - ${HOME}/.opencue/sessions:${HOME}/.opencue/sessions
```

**為什麼是問題**：`${HOME}` 是「執行 docker compose 的那個 shell」的變數。
Portainer 以 daemon 身分部署 stack，環境裡不見得有 `HOME`，會被代換成空字串，
變成 `/.opencue/sessions:/.opencue/sessions`。

**正式環境做法**：改用 stack 的 `.env` 明確定義，例如
`OPENCUE_SESSION_DIR=/opt/opencue/sessions`，compose 兩邊都用這個變數。
Portainer 的 stack 編輯畫面可以直接填環境變數。

## 三、`/var/folders` 是 macOS 專用

現況：

```yaml
rqd:
  volumes:
    - /var/folders:/var/folders:ro
```

`/var/folders` 是 macOS 放暫存檔的路徑（`$TMPDIR` 指向那裡）。Linux 宿主上根本
沒這個目錄，Docker 會自動建一個空的 root-owned 目錄掛進去 —— 不會報錯，但沒意義，
還會在宿主根目錄留垃圾。

**正式環境做法**：直接刪掉這行。

## 四、`/tmp` 底下的 bind mount

現況：`/tmp/rqd/logs`、`/tmp/rqd/shots`、`/tmp/opencue`。

**為什麼是問題**：`/tmp` 多數發行版會定期清理或掛 tmpfs（重開機即空）。
frame log 是事後除錯的唯一線索，放 `/tmp` 等於沒有 log 保存。

**正式環境做法**：換成固定路徑（如 `/opt/opencue/logs`）或 named volume；
若是多台 render node，這裡必須是**所有節點掛在相同路徑的共享儲存**（NFS 等），
否則 Cuebot 記錄的 log 路徑在別台機器上找不到。

## 五、密碼寫死在 compose 裡

現況：`POSTGRES_PASSWORD=cuebot_password`，且 cuebot 的 `command:` 裡又寫一次。

**正式環境做法**：移到 `.env` 或 Docker secrets。注意密碼在兩處出現，改一處會不同步。

## 六、所有 port 直接 expose

現況：5432（DB）、8443（Cuebot gRPC）、8444（RQD）全部 publish 到宿主。

sandbox 在本機沒差，但正式環境把 PostgreSQL 開到外網是明確的風險。
**正式環境做法**：只留真正需要外部存取的（Cuebot gRPC、CueWeb），其餘留在
internal network；Portainer 本身也建議掛在反向代理後面加認證。

## 七、session path 對齊（決定 client 裝在哪）

這是**為什麼測試要在 WSL 裡做、而不是 Windows 原生**的主因。

pyoutline 投 job 時會把 `outline.yaml` 寫進 session 目錄，並把**該路徑字串**
寫進 frame 的執行指令。RQD 拿到指令後要用**同一個路徑**讀到那個檔案。

- 若 client 跑在 Windows：路徑是 `C:\Users\chordee\.opencue\sessions\...`，
  Linux container 裡的 RQD 完全無法解析 → frame 必定失敗。
- 若 client 跑在 WSL Ubuntu：路徑是 `/home/chordee/.opencue/sessions/...`，
  compose 把它原樣 bind mount 進 container，兩邊路徑字串一致 → 可行。

**推論到正式環境**：這條規則對真農場同樣成立 —— 投 job 的機器與所有 render node
必須看到**相同路徑**的共享儲存。這正是 sandbox 用 bind mount 假裝、而真農場必須
用 NFS/SMB 真正解決的問題。

## 八、CueWeb 的 build-time 變數（之後開 cueweb profile 才會遇到）

compose 檔頭的註解已經寫明：CueWeb 是 Next.js，`NEXT_PUBLIC_*` 變數在**build 時**
就烘進 image。若 image 裡烘的是 `http://localhost:8448`，部署到別台機器就會
`ECONNREFUSED`。

**正式環境做法**：build image 時就要用正確的對外網址當 build arg，不能事後改
環境變數。這點在 Portainer 上特別容易踩到，因為 Portainer 習慣用環境變數調設定。
