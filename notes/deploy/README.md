# OpenCue 正式部署

本目錄只寫**怎麼部署**。每個做法背後的測試過程、踩過的坑與原始碼依據，
放在 `notes/sandbox/`，各段落以「依據」標註出處。

---

## 環境前提

| 項目 | 內容 |
|---|---|
| OpenCue 伺服器 | 一台 Linux + Docker，入口是 Portainer，**不參與算圖**，主機上還有其他服務 |
| 算圖節點 | Windows。分為 **artist 工作站**（下班後借用）與**專職算圖機** |
| DCC | Houdini / Maya / Nuke，**每台安裝路徑不同、多版本並存**，專案指定版本 |
| 網路磁碟機 | 全公司代號一致，專案檔內部以磁碟機代號引用路徑 |

---

## 三種機器，各看哪一篇

| 機器 | 文件 | 設定檔 |
|---|---|---|
| OpenCue 伺服器 | [`01-伺服器.md`](01-伺服器.md) | [`server/`](server/) |
| 專職算圖機 | [`02-算圖節點.md`](02-算圖節點.md) | [`node/`](node/) |
| artist 工作站 | [`02-算圖節點.md`](02-算圖節點.md) ＋ [`03-工作站.md`](03-工作站.md) | [`node/`](node/) ＋ [`client/`](client/) |
| 部署完成後 | [`04-維運.md`](04-維運.md) | — |
| 出問題時 | [`notes/sandbox/17-故障排查與常見疏失速查.md`](../sandbox/17-故障排查與常見疏失速查.md) | — |

artist 工作站是**雙重身分**：白天是用戶端，下班後是算圖節點，兩篇都要做。

---

## 放在本機，還是放在網路空間

| 放在每台機器本機 `C:\opencue\` | 放在網路空間，全公司共用 |
|---|---|
| `venv\`：Python、RQD、`ocrun`、用戶端工具 | frame log（`CUE_FRAME_LOG_DIR`，UNC 共享） |
| `rqd.conf`：每台的主機名稱、tag 不同 | 場景檔、算圖輸出（專案空間） |
| `rqd-start.bat` | pipeline 工具：從 DCC 投遞的工具、算圖時呼叫的腳本 |
| `dcc.toml`：這台有哪些 DCC 版本、裝在哪 | |
| `tmp\`：算圖暫存與快取 | |

**放本機的理由**：RQD 開機就要啟動，那時網路磁碟機可能還沒就緒；從網路磁碟執行 Python
既慢又不穩；`dcc.toml` 與 `rqd.conf` 的內容本來就每台不同。

**放網路的理由**：所有機器要看到同一份。pipeline 工具放網路上，更新時只改一處，
所有工作站與節點立刻生效，不會有某台還在用舊版的情況。

pipeline 工具區的位置由工作室決定，本目錄的文件以 `P:\pipeline\opencue\` 為例：

| 位置 | 內容 |
|---|---|
| `P:\pipeline\opencue\client\maya\` | 從 Maya 投遞的工具，見 [`03` 第六節](03-工作站.md#六從-maya-直接投遞) |
| `P:\pipeline\opencue\scripts\` | 算圖時由 job 呼叫的腳本 |

注意事項：

- 路徑**不能有空白**（[`03` 第七節](03-工作站.md#七投遞-job-時要注意的事)）
- 網路上的東西只能在網路磁碟就緒後使用。投遞工具在 artist 登入後才用，沒有問題；
  算圖腳本在 frame 執行時才用，也沒有問題。RQD 本身不行，所以留在本機
- 專職算圖機若以 Windows 服務執行，**看不看得到磁碟機代號還未驗證**（[`02` 第八節](02-算圖節點.md#八專職算圖機與工作站的差異)）。
  看不到的話，job 呼叫的腳本路徑要改用 UNC

---

## 現成的 image

已經 build 好的 image 公開在 GHCR，**不需登入即可 pull**，部署時不必自己 build：

| 元件 | image |
|---|---|
| Cuebot | `ghcr.io/chordee/opencue/cuebot:1.34.4-1d73523b` |
| Flyway（DB migration） | `ghcr.io/chordee/opencue/flyway:1.34.4-1d73523b` |
| REST Gateway | `ghcr.io/chordee/opencue/rest-gateway:1.34.4-1d73523b` |
| CueWeb | `ghcr.io/chordee/opencue/cueweb:1.34.4-1d73523b` |
| init（建立 show / service） | `ghcr.io/chordee/opencue/init:1.34.4-1d73523b` |

- [`server/env.example`](server/env.example) 的預設值就是這一組
- 只有 **amd64**（Intel / AMD 的 x86-64 主機）
- CueWeb 是**不需要登入**的版本，連得到 3000 port 就能操作 job，要用防火牆限制來源
- 五個合計約 6 GB，第一次部署要預留下載時間
- 新版本由 GitHub Actions 的 **Sandbox images** workflow 產生，見 [`04-維運.md`](04-維運.md)

---

## 部署順序

1. **OpenCue 伺服器**（[`01-伺服器.md`](01-伺服器.md)）
   - 部署 stack → 確認 8443 可連、CueWeb 打得開
2. **一台專職算圖機**，先只做一台（[`02-算圖節點.md`](02-算圖節點.md)）
   - 安裝 Python + RQD + winps + ocrun
   - dcc.toml + rqd.conf
   - 【驗證】`cueadmin -lh` 看得到這台，alloc 前綴是 local
   - 【驗證】Cuebot 容器內能解析並連到本機 8444
   - 【驗證】投一個真實算圖 job 並成功
3. **其餘專職算圖機**
   - 複製第 2 步的設定，只改主機名稱與 `dcc.toml` 裡的安裝路徑
4. **artist 工作站**（[`03-工作站.md`](03-工作站.md) ＋ [`02-算圖節點.md`](02-算圖節點.md)）
   - 用戶端工具 + opencue.yaml
   - 【驗證】CueGUI 看得到農場、CueSubmit 投得出 job
   - 再加上 RQD + CueNIMBY（下班後兼任算圖節點）
5. **維運排程**（[`04-維運.md`](04-維運.md)）
   - DB 備份、歷史表清理、frame log 保留期

**第 2 步只做一台。** 在那一台把問題全部排除、驗證通過，再批次部署其他機器，
否則同一個問題會在所有機器上重演。

---

## 尚未在實機驗證的項目

以下項目在本機 sandbox 無法測試，第一次部署時要特別確認：

| 項目 | 影響 | 相關文件 |
|---|---|---|
| 跨機器的實際網路（防火牆 8444 入站） | 沒開的話 frame 永遠卡 RUNNING | [`02`](02-算圖節點.md) |
| 專職算圖機以 Windows 服務執行時，看不看得到網路磁碟機 | 看不到的話所有 frame 都讀不到檔案 | [`02`](02-算圖節點.md) |
| 開機 / 登入時自動啟動 | — | [`02`](02-算圖節點.md) |
| 容器是否沿用宿主的 DNS search 網域 | 解析不到節點名稱會卡 RUNNING | [`01`](01-伺服器.md) |
| 共享儲存以 UNC 路徑端到端寫入與讀取 | CueWeb 看不到 log | [`01`](01-伺服器.md) |
| Arnold / MtoA | 未測 | — |

完整的驗證狀態見 [`notes/sandbox/19-驗證狀態總表.md`](../sandbox/19-驗證狀態總表.md)。

---

## 檔案一覽

### 文件

| 檔案 | 內容 |
|---|---|
| [`README.md`](README.md) | 本檔 |
| [`01-伺服器.md`](01-伺服器.md) | OpenCue 伺服器 |
| [`02-算圖節點.md`](02-算圖節點.md) | Windows 算圖節點 |
| [`03-工作站.md`](03-工作站.md) | artist 工作站的用戶端工具 |
| [`04-維運.md`](04-維運.md) | 升級、備份、常用操作 |

### `server/`：伺服器

| 檔案 | 內容 |
|---|---|
| [`server/opencue.portainer.yml`](server/opencue.portainer.yml) | 主檔（Portainer 與 docker compose 共用） |
| [`server/env.example`](server/env.example) | 環境變數範本 |
| [`server/build.yml`](server/build.yml) | 自行 build 時疊加 |
| [`server/site.example.yml`](server/site.example.yml) | DNS / 多台 extra_hosts 等站點設定 |
| [`server/init/`](server/init/) | 初始化容器的原始碼 |
| [`server/registry.portainer.yml`](server/registry.portainer.yml) | 自建 registry（使用 GHCR 時不需要） |
| [`server/monitoring.portainer.yml`](server/monitoring.portainer.yml) | 選用的監控 stack（Prometheus + Grafana） |

### `node/`：算圖節點

全部是純 ASCII，原因見 [`02` 第二節](02-算圖節點.md#二重要設定檔與腳本一律使用純-ascii)。

| 檔案 | 放置位置 | 內容 |
|---|---|---|
| [`node/rqd-windows.conf`](node/rqd-windows.conf) | `C:\opencue\rqd.conf` | RQD 設定 |
| [`node/rqd-start.bat`](node/rqd-start.bat) | `C:\opencue\rqd-start.bat` | 啟動腳本 |
| [`node/rqd-start-hidden.vbs`](node/rqd-start-hidden.vbs) | 使用者的啟動資料夾 | 工作站登入時啟動用 |
| [`node/dcc-windows.toml`](node/dcc-windows.toml) | `C:\opencue\dcc.toml` | 本機的 DCC 版本與安裝路徑 |
| [`node/ocrun/`](node/ocrun/) | 以 pip 安裝進 venv | job 呼叫 DCC 的指令 `ocrun`（Windows / Linux 共用） |
| [`node/cuenimby-workstation.json`](node/cuenimby-workstation.json) | `%USERPROFILE%\.config\opencue\cuenimby.json` | CueNIMBY 排程 |

### `client/`：工作站

| 檔案 | 放置位置 | 內容 |
|---|---|---|
| [`client/opencue-client.yaml`](client/opencue-client.yaml) | `%APPDATA%\opencue\opencue.yaml` | 用戶端工具的連線設定 |
| [`client/maya/`](client/maya/) | `P:\pipeline\opencue\client\maya\`（網路空間） | 從 Maya 直接投遞的工具 |
