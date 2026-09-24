# 23 — Portainer 的 Git 模式

stack 不再貼 yml 內容，改成**直接指向 GitHub 上的檔案**，
repo 更新後由 Portainer 自動或手動重新部署。

環境：Portainer CE 2.39.1，repo `chordee/OpenCue`，分支 `studio/main`。

---

## 一、從 Web editor stack 切換到 Git stack

### 為什麼不能兩個並存

yml 裡明確指定了 `container_name`、network 名稱與 volume 名稱，
兩個 stack 用同一份 yml 一定會撞名。所以要先讓舊的 stack 讓出位置。

### 做法：停止舊 stack，而不是刪除

```
1. 備份 DB（見 notes/deploy/04 第二節）
2. 舊 stack → Stop
3. 新增 Git stack（名稱不能與舊的相同）
```

**Stop 的行為**（實測）：容器被移除，**volume 全部保留**，stack 定義也還在，
隨時可以重新 Start。比 Delete 安全，需要時可以退回。

新的 Git stack 因為 volume 名稱在 yml 裡寫死（`opencue-db-data`），
**會直接沿用同一個 DB**：

| | 切換前 | 切換後 |
|---|---|---|
| host | 2 | 2 |
| service | 13 | 13 |
| show | 3 | 3 |
| job_history | 41 | 41 |

兩個節點自動重新上線（UP / OPEN），CueWeb 回 200。

### 建立 Git stack

Portainer UI：Stacks → Add stack → Build method 選 **Repository**：

| 欄位 | 值 |
|---|---|
| Repository URL | `https://github.com/chordee/OpenCue` |
| Repository reference | `refs/heads/studio/main` |
| Compose path | `notes/deploy/server/opencue.portainer.yml` |
| Authentication | 關閉（公開 repo） |
| Environment variables | 與 Web editor 版相同 |

API（實測）：

```
POST /api/stacks/create/standalone/repository?endpointId=3
{
  "name": "opencue-git",
  "repositoryURL": "https://github.com/chordee/OpenCue",
  "repositoryReferenceName": "refs/heads/studio/main",
  "composeFile": "notes/deploy/server/opencue.portainer.yml",
  "repositoryAuthentication": false,
  "env": [ ... ]
}
→ 200，約 52 秒（image 已在本機）
```

Portainer 會記下部署時的 commit：

```
"ConfigHash": "80c571c1a633e4f595a7ef50ccc13379a50a0d4f"
```

---

## 二、三種更新方式

### 1. 手動 Pull and redeploy

UI：stack 頁面的 **Pull and redeploy**。API：`PUT /api/stacks/{id}/git/redeploy`。

實測：**repo 沒有任何變動，容器也全部重建**（Cuebot 重新啟動），耗時約 63 秒。
按一次就會有一次短暫中斷，不要隨手按。

### 2. 自動輪詢（Polling）

UI：stack 頁面 → **GitOps updates** → Mechanism 選 Polling，設定間隔。

```
"AutoUpdate": {"Interval": "1m", ...}
```

實測：**repo 沒有新 commit 時，不會重新部署**（等 90 秒，Cuebot 啟動時間未變）。

### 3. Webhook

UI：同上，Mechanism 選 Webhook，會產生一個網址：

```
POST https://<portainer>/api/stacks/webhooks/<uuid>
```

實測：

- CE 版可用
- **呼叫時不需要任何認證**（不用 API key），知道 UUID 就能觸發
- repo 沒有新 commit 時回 204，不重新部署

因為只會在 repo 有變動時才部署，被陌生人觸發的風險有限。
但 UUID 仍應視為機密，不要貼在公開的地方。

---

## 三、有新 commit 時（待測）

（測試中）
