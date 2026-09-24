# 07 — Portainer 部署實錄

驗證目標：**在只有 Portainer、沒有 SSH 的前提下，能不能把 OpenCue 部署起來。**

結論：**可以。** 而且不需要 registry（若 image 已存在於該 Docker daemon）。

## 環境

- Portainer CE **2.39.1**，`https://localhost:9443`
- Endpoint：`Id=3`、名稱 `local`、`unix:///var/run/docker.sock`
- 該 endpoint 的 Docker 29.6.2 / 16 CPU / 19.2 GiB

## 使用的 stack 檔

[`notes/deploy/server/opencue.portainer.yml`](../deploy/server/opencue.portainer.yml)，與上游 compose 的差異：

1. **完全不用 `build:`**，只用 `image:`
2. **不含 `rqd`** —— 宿主不算圖
3. **PostgreSQL 不 publish 5432**
4. 所有可變參數走環境變數（見 [`notes/deploy/server/env.example`](../deploy/server/env.example)）
5. 明確命名 network（`opencue`）與 volume（`opencue-db-data`）
6. 加上記憶體上限

## 部署步驟（API 方式）

### 1. 取得 API token

Portainer UI → 右上角頭像 → My account → Access tokens → Add access token。
Token 只顯示一次。

### 2. 確認 endpoint ID

```bash
curl -sk -H "X-API-Key: $TOKEN" https://localhost:9443/api/endpoints
```

回傳的 `Id` 就是後續要用的 `endpointId`。

### 3. 組出 payload

Portainer 的 API 吃 JSON，欄位：

```json
{
  "name": "opencue",
  "stackFileContent": "<整份 yml 的字串>",
  "env": [{"name": "POSTGRES_USER", "value": "cuebot"}, ...]
}
```

註：`env` 是**陣列**，每個元素是 `{name, value}`，不是一般的物件對應。

### 4. 建立 stack

```bash
curl -sk -X POST \
  -H "X-API-Key: $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @payload.json \
  "https://localhost:9443/api/stacks/create/standalone/string?endpointId=3"
```

成功會回傳 stack 物件，`Status: 1` 表示已啟動。

## 驗證結果

```
NAMES            STATUS                      PORTS
opencue-cuebot   Up (healthy)                0.0.0.0:8443->8443/tcp
opencue-flyway   Exited (0)
opencue-db       Up (healthy)                5432/tcp
```

三項設計意圖都達成：

| 意圖 | 驗證 |
|---|---|
| Cuebot 對外服務 | `8443` 有 publish，`cueadmin -lh`、`cueadmin -ls` 皆可正常回應 |
| DB 不對外 | PORTS 欄只有 `5432/tcp`，**沒有 `0.0.0.0:` 映射** |
| flyway 為 one-shot | `Exited (0)`，且 cuebot 在其之後才啟動 |
| 自訂 network / volume | `opencue`、`opencue-db-data` 依定義建立 |

**沒有用到任何 registry。** Portainer 與本機 docker 共用同一個 daemon，
直接引用本機 build 好的 `opencue-cuebot:latest`、`opencue-flyway:latest`。

（正式環境仍應改用 registry 上的明確 tag，因為那台宿主不會有 build 好的 image。）

## 關鍵測試：外部 render node

stack 裡刻意不含 rqd。為了驗證「Cuebot 在 Docker、render node 在外部」這個
目標架構，另外起一個**不屬於該 stack** 的 RQD 容器：

```bash
docker run -d --name render01 --hostname render01 --network opencue \
  -e OPENRQD__GRPC__CUEBOT_ENDPOINTS=cuebot:8443 \
  -e OPENRQD__MACHINE__USE_IP_AS_HOSTNAME=false \
  -v /tmp/rqd/logs:/tmp/rqd/logs \
  -v /tmp/rqd/shots:/tmp/rqd/shots \
  --entrypoint /bin/sh \
  opencue-rqd:latest \
  -c 'id -u chordee >/dev/null 2>&1 || useradd --uid 2000 --gid 1000 -M chordee; exec /app/openrqd'
```

結果：

```
Host       Cores  Mem     State  Alloc          Thread
render01   8.0    18.5G   UP     local.general  AUTO
```

投 2 個 job（共 6 frame）→ **全部 SUCCEEDED**。

**這驗證了目標架構可行**：Portainer 部署的 Cuebot stack（不含 rqd）
＋ 外部獨立生命週期的 render node ＝ 完整可運作的農場。

## 尚未驗證的部分

> **注意**：本節寫於當時，部分項目後來已補測完成。
> **最新的驗證狀態以 [`19-驗證狀態總表.md`](19-驗證狀態總表.md) 為準。**


| 項目 | 說明 |
|---|---|
| 真正的跨機器連線 | 本次 render01 與 cuebot 在同一個 Docker network，靠內建 DNS 解析。真實的 Windows 節點要走實體網路與真實 DNS/IP |
| Windows 上的 RQD | 本次 render node 仍是 Linux 容器。Windows 原生 RQD 需另外驗證，且已知 `run_as_user` 在 Windows 尚未支援 |
| Registry 流程 | 本次直接用本機 image。正式環境需驗證「build → push → Portainer pull」整條流程 |
| Portainer UI 操作 | 本次全程走 API。若 IT 只給 UI，需確認貼上 compose 的流程與環境變數填法 |
| stack 更新流程 | 只測了建立，沒測 `PUT /api/stacks/{id}` 更新與回滾 |

## 附記：NAS 不適合當演練平台

原本考慮用 Synology NAS 上的 Portainer 演練（它是真正的 Linux + Docker 主機），
但 NAS 的 CPU 是 **Realtek RTD1296（ARM）**，與最終的 x86 Linux 宿主架構不同。
本機 build 的 x86 image 無法在其上執行，需另外處理 multi-arch build。
考量最終環境是 x86，這條路的投資報酬率不高，暫不進行。
