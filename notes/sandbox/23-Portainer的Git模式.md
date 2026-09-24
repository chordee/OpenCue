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

1. 備份 DB（見 [`notes/deploy/04` 第二節](../deploy/04-維運.md#二db-備份與還原)）
2. 舊 stack → Stop
3. 新增 Git stack（名稱不能與舊的相同）

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
| Compose path | [`notes/deploy/server/opencue.portainer.yml`](../deploy/server/opencue.portainer.yml) |
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

## 三、有新 commit 時

### 實測：只改文件的 commit

push 一個只新增本篇筆記、沒有動 yml 的 commit（`637f02ef`），輪詢間隔 1 分鐘：

```
05:51:54  push
05:53     Portainer 偵測到新 commit，ConfigHash 更新為 637f02ef
          執行部署 → "Stack deployment successful"
```

各容器的啟動時間：

| 容器 | 啟動時間 | 結果 |
|---|---|---|
| db | 05:40:49 | **沒有重啟** |
| cuebot | 05:41:03 | **沒有重啟** |
| rest-gateway | 05:41:14 | **沒有重啟** |
| cueweb | 05:41:20 | **沒有重啟** |
| flyway | 05:52:59 → 結束 | 重新跑了一次 |
| init | 05:53:03 → 結束 | 重新跑了一次 |

**Portainer 的自動部署等同 `docker compose up -d`**：只重建設定有變動的服務。
長期運作的服務沒有中斷；一次性的 flyway 與 init 會再跑一次，
但 schema 沒變、init 不覆寫既有項目，所以不會造成影響。

**結論：筆記和部署設定放在同一個 repo 沒有問題。**
改文件的 commit 會觸發一次部署，但不會中斷農場。

### 與手動 Pull and redeploy 的差別

| 觸發方式 | repo 沒變 | repo 有變但服務設定沒變 |
|---|---|---|
| 自動（輪詢 / webhook） | 不部署 | 部署，**只重跑一次性容器** |
| 手動 Pull and redeploy | **全部容器重建** | 全部容器重建 |

手動重新部署會強制重建，自動的不會。**日常更新靠自動機制，
手動按鈕留給需要強制重建的時候。**

### 升級 image 仍然要手動

image 的 tag 放在 Portainer 的環境變數裡，不在 git 裡。
所以 **push 不會升級 image**，要升級還是到 Portainer 改環境變數再 Update。

這樣的分工是刻意的：

| 變更 | 放在哪 | 怎麼上線 |
|---|---|---|
| stack 結構（新增服務、改 healthcheck、改資源上限） | git | push 後自動 |
| image 版本 | Portainer 環境變數 | **人工**改 tag |
| 密碼、路徑等站點設定 | Portainer 環境變數 | 人工 |

image 升級可能帶來 DB migration（只能往前），升級前要先備份，
所以保留人工確認的步驟。若要連 image 也全自動，可以把 tag 寫成 yml 的預設值
（`${OPENCUE_CUEBOT_IMAGE:-ghcr.io/...:1.34.4-xxxx}`）並從 Portainer 移除該變數，
但不建議。

---

## 四、正式環境追蹤專用分支 `studio/release`

### 問題

1 分鐘的輪詢本身開銷很小（沒有變動就什麼都不做），但**追蹤 `studio/main` 時，
任何 push 都會上線**。筆記、測試腳本、正式設定都在同一個分支，
寫錯的 yml 被 push 上去，幾分鐘內正式環境就會用它重新部署。

### 做法

```
studio/main       日常工作，push 不影響正式環境
    │  確認後 merge --ff-only
    ▼
studio/release    Portainer 只追蹤這個分支
```

把 stack 的 reference 改成 `refs/heads/studio/release`
（`POST /api/stacks/{id}/git`，更新 `repositoryReferenceName`）。
切換 reference 本身不會重啟服務（實測 Cuebot 啟動時間未變）。

### 實測

| 步驟 | Portainer 記錄的 commit | init | Cuebot |
|---|---|---|---|
| 切換 reference 到 `studio/release` | `ed47b2d4` | 未重跑 | 未重啟 |
| 只 push `studio/main`（`004f267d`），等 3 分鐘 | **仍是 `ed47b2d4`** | **未重跑** | 未重啟 |
| `studio/release` fast-forward 到 `004f267d` 並 push | 約 1 分鐘內更新為 `004f267d` | 重跑 | 未重啟 |

**正式環境只在推進 `studio/release` 時才會更新。**

測試完成後輪詢間隔改為 5 分鐘。1 分鐘只是為了縮短測試時間；
改為追蹤專用分支後，推進分支的頻率很低，5～15 分鐘的延遲可以接受。

### 修改 yml 的情況

已補測：只修改 Cuebot 的啟動參數時，只有 Cuebot 被重建。見 [`24` 第三節](24-派工行為與監控.md#三portainer-git-模式修改-yml-只重建該服務)。
