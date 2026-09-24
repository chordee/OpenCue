# 16 — Portainer 與 SSH 的分工

**Portainer 負責部署，維運工作多數仍需宿主權限。**
這份把兩者的界線列清楚，作為與 IT 討論存取權限時的依據。

標記說明：

- ✅ **本次已實測驗證**
- ◻ 未實測，但屬 Portainer/Docker 的既有功能
- ⚠ 有替代做法可迴避，見下方「緩解方案」

## Portainer 做得到的

| 工作 | 狀態 |
|---|---|
| 從 compose 內容建立 stack | ✅ `POST /api/stacks/create/standalone/string` |
| 更新 stack（含環境變數） | ✅ `PUT /api/stacks/{id}` |
| 從 registry 拉取 image 並重建容器 | ✅ `pullImage: true`，已用「先刪本機 tag」的方式證明確實有 pull |
| 查看容器狀態與 port 映射 | ✅ |
| 版本升級與回滾 | ✅ 只需改 stack 的 image tag 變數 |
| 查看容器 log | ◻ |
| 進入容器執行指令（exec） | ◻ |
| 重啟 / 停止個別容器 | ◻ |
| 建立 volume 與 network | ◻ |

**部署這一段，Portainer 是夠用的**，本次已完整走過一輪。

## 需要宿主權限（SSH）的

### 1. 建置 image —— 這是 registry 存在的唯一原因

Portainer 沒有 build context，compose 裡的 `build:` 用不了。

而 OpenCue 的 CueWeb 與 REST Gateway **沒有發布公開 image**（見 [`13`](13-CueWeb與RESTGateway.md)），
所以自建是必要的。這導致整條 registry 鏈被迫出現：

- 一台建置機器（記憶體要夠，CueWeb 的 Next.js build 吃數 GB）
- 一個 registry（TLS 憑證、認證）
- 約 6 GB/版本的儲存
- garbage-collect 與備份

**若有 SSH，這些全部可以不要** —— 直接在宿主
`git pull && docker compose up -d --build` 即可。

（但 registry 仍有獨立價值：`<版本>-<commit SHA>` 的 tag 能追溯與回滾。
有 SSH 之後它從「必需」變成「值得保留」。）

### 2. 排程工作 —— 本次盤點出的維運項目大多屬於此類

| 工作 | 來源 | Portainer |
|---|---|---|
| PostgreSQL 歷史表定期清理 | [`11`](11-正式部署風險與待辦.md) 第 6 點 | ❌ ⚠ |
| `pg_dump` 定期備份 | [`11`](11-正式部署風險與待辦.md) 第 6 點 | ❌ ⚠ |
| registry garbage-collect | [`14`](14-Registry流程.md) | ❌ ⚠ |
| frame log 保留期清理 | [`15`](15-空間規劃.md) | ❌ ⚠ |
| build cache 清理（建置機器） | [`15`](15-空間規劃.md) | ❌ |
| 磁碟用量監控與告警 | [`15`](15-空間規劃.md) | ❌ |

**歷史表永遠不會自動清除、DB 沒有備份**，這兩項若沒人處理，
是實際會出事的風險，不是理論問題。

### 3. Docker daemon 設定

`/etc/docker/daemon.json` 只能在宿主上改，且改完要重啟 daemon：

| 設定 | 用途 |
|---|---|
| `insecure-registries` | registry 若沒有 TLS 憑證就必須設 |
| 預設 log driver 與輪替 | 避免容器 log 無上限成長（見 [`15`](15-空間規劃.md)） |
| `data-root` | 把 Docker 的資料移到較大的磁碟 |

**注意這是個循環**：registry 沒有 TLS → 需要 `insecure-registries` →
需要改 daemon.json → 需要 SSH。所以若堅持只用 Portainer，
**registry 就必須有有效的 TLS 憑證**。

### 4. 作業系統層

| 工作 | 說明 |
|---|---|
| Docker 開機自啟（systemd） | 宿主重開機後 stack 要自己回來 |
| 防火牆規則 | 8443 對 Windows 節點開放（見 [`11`](11-正式部署風險與待辦.md) 第 3 點） |
| 掛載共享儲存 | CueWeb 要讀 frame log ⚠（可用 CIFS volume 迴避 mount，但宿主仍須具備 cifs-utils） |
| TLS 憑證安裝 | registry、反向代理 |
| OS 更新與疑難排解 | |

## 緩解方案：把維運工作容器化

標記 ⚠ 的項目其實有解 —— **做成 stack 裡的一個維運容器**，
由 Portainer 一併部署：

```yaml
  maintenance:
    image: ${OPENCUE_MAINTENANCE_IMAGE}
    container_name: opencue-maintenance
    depends_on:
      db:
        condition: service_healthy
    environment:
      PGHOST: db
      PGUSER: ${POSTGRES_USER}
      PGPASSWORD: ${POSTGRES_PASSWORD}
      PGDATABASE: ${POSTGRES_DB}
      HISTORY_RETENTION_DAYS: "90"
      LOG_RETENTION_DAYS: "30"
    volumes:
      - ${FRAME_LOG_MOUNT_SOURCE}:${FRAME_LOG_MOUNT_TARGET}
      - backup-data:/backup
    networks:
      - opencue
    restart: unless-stopped
```

容器內跑 cron（或 supercronic / ofelia 這類容器排程器），負責：

- 執行歷史表清理 SQL（記得加 `int_ts_stopped > 0` 的防護，見 [`11`](11-正式部署風險與待辦.md)）
- `pg_dump` 到掛載的備份目錄
- 依保留期刪除 frame log

**這樣連排程都能透過 Portainer 部署。** 但仍有前提：

- 備份**寫到哪裡** —— 寫進 volume 只是換個地方放在同一台機器上，
  真正的異地備份仍需要有人把它搬走
- registry 的 GC 要能連到 registry 容器
- 這個 image 也要自己 build 並推到 registry

**本次未實作此方案**，僅列為可行方向。

### 共享儲存的掛載也有容器化解法

CueWeb 需要讀 frame log，本次是用 bind mount。
若宿主上無法掛載 SMB 共享，Docker 的 local volume driver 支援 CIFS：

```yaml
volumes:
  frame-logs:
    driver: local
    driver_opts:
      type: cifs
      device: "//fileserver/opencue/logs"
      o: "username=...,password=...,ro"
```

這樣不需要在宿主上做 `mount`，Portainer 就能部署。

**但這個方案有兩個前提，其中一個會讓它退回需要 SSH：**

#### 前提一：宿主核心必須支援 CIFS

**Docker 自己不帶 CIFS 用戶端。** `type: cifs` 最終是呼叫宿主核心的
`cifs.ko` 與 `mount.cifs`（來自 `cifs-utils` 套件）。精簡的 Linux 發行版
可能兩者都沒有。

若缺少，建立 volume 時**不會報錯**（建立階段不實際掛載），
要到第一次使用時才失敗。

**驗證方法 —— 看錯誤訊息的類型即可分辨：**

```bash
docker volume create --driver local   --opt type=cifs   --opt device=//fileserver/share   --opt o=guest,ro cifstest

docker run --rm -v cifstest:/mnt alpine ls /mnt
docker volume rm cifstest
```

| 錯誤訊息 | 含意 | 是否需要 SSH |
|---|---|---|
| `permission denied` | **核心支援 CIFS**，只是憑證不對 | 否，改憑證即可 |
| `cifs filesystem not supported` | 核心模組或 `cifs-utils` 缺失 | **是**，要裝套件 |

本次在 Docker Desktop 的 VM 上實測，得到的是：

```
failed to mount local volume: mount //192.168.0.107/chordee:...
flags: 0x1, data: guest: permission denied
```

→ **該環境的核心支援 CIFS**（掛載走到認證階段才失敗）。

註：不要用容器內的 `/proc/filesystems` 判斷 —— 掛載是由**宿主上的 daemon**
執行的，不在容器的命名空間裡。本次容器內查不到 cifs，但實際掛載是支援的。
**唯一可靠的檢查方式就是實際嘗試掛載。**

#### 前提二：憑證管理

憑證會出現在 stack 定義裡，需要用 Portainer 的環境變數或 secret 管理，
IT 可能有政策限制。

#### 結論

這個方案**避免了「在宿主上執行 mount」，但沒有避免「宿主要具備 CIFS 能力」**。
若目標宿主缺少 `cifs-utils`，安裝套件仍需宿主權限 ——
所以它只是**部分**緩解，不能作為「完全不需要 SSH」的依據。

部署前請先用上面的指令在目標宿主上確認。

## 無論如何都需要 SSH 的

扣掉所有緩解方案之後，剩下這些：

| 工作 | 為什麼無法迴避 |
|---|---|
| 建置 image | 除非有另一台建置機器 + registry |
| `/etc/docker/daemon.json` | 檔案在宿主上，改完要重啟 daemon |
| Docker 開機自啟 | systemd 設定 |
| 防火牆規則 | OS 層 |
| 宿主磁碟監控與清理 | `docker system prune`、`builder prune` |
| 異地備份的搬運 | 備份若只留在同一台機器上沒有意義 |
| 疑難排解 | daemon 本身的問題、資源耗盡、網路 |

## 建議的討論方式

**不要問「能不能給我 SSH」** —— 那容易被理解成要 root 權限。
改成說明具體需求：

1. **部署與更新完全走 Portainer** —— 已驗證可行，IT 保有可視性與控制權
2. **需要在宿主上執行排程工作**（DB 清理、備份、log 清理）——
   這是營運必需項，不是便利性需求
3. **若排程工作無法取得宿主權限**，請 IT 代為設定，
   或接受「資料庫無限成長、沒有備份」的風險並書面確認

### 三種情境的落差

| 情境 | 可行性 | 代價 |
|---|---|---|
| 完整 SSH | 最單純 | 不需要 registry；可直接 build、設排程、調 daemon |
| Portainer + 有限 SSH（可設 cron） | 良好 | 需要 registry，但維運無虞 |
| 只有 Portainer | 可部署，但維運有缺口 | registry 必須有 TLS；排程需容器化；異地備份無解 |

**最後一種不是不能跑，而是要明確知道缺了什麼，並由誰承擔。**
