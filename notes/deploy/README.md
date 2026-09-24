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
| OpenCue 伺服器 | `01-伺服器.md` | `server/` |
| 專職算圖機 | `02-算圖節點.md` | `node/` |
| artist 工作站 | `02-算圖節點.md` ＋ `03-工作站.md` | `node/` ＋ `client/` |
| 部署完成後 | `04-維運.md` | — |
| 出問題時 | `notes/sandbox/17-故障排查與常見疏失速查.md` | — |

artist 工作站是**雙重身分**：白天是用戶端，下班後是算圖節點，兩篇都要做。

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

- `server/env.example` 的預設值就是這一組
- 只有 **amd64**（Intel / AMD 的 x86-64 主機）
- CueWeb 是**不需要登入**的版本，連得到 3000 port 就能操作 job，要用防火牆限制來源
- 五個合計約 6 GB，第一次部署要預留下載時間
- 新版本由 GitHub Actions 的 **Sandbox images** workflow 產生，見 `04-維運.md`

---

## 部署順序

```
1. OpenCue 伺服器                           01-伺服器.md
   └─ 部署 stack → 確認 8443 可連、CueWeb 打得開
        │
2. 一台專職算圖機（先只做一台）               02-算圖節點.md
   ├─ 安裝 Python + RQD + winps
   ├─ wrapper + rqd.conf
   ├─【驗證】cueadmin -lh 看得到這台，alloc 前綴是 local
   ├─【驗證】Cuebot 容器內能解析並連到本機 8444
   └─【驗證】投一個真實算圖 job 並成功
        │
3. 其餘專職算圖機
   └─ 複製第 2 步的設定，只改主機名稱與 wrapper 裡的安裝路徑
        │
4. artist 工作站                             03-工作站.md ＋ 02-算圖節點.md
   ├─ 用戶端工具 + opencue.yaml
   ├─【驗證】CueGUI 看得到農場、CueSubmit 投得出 job
   └─ 再加上 RQD + CueNIMBY（下班後兼任算圖節點）
        │
5. 維運排程                                  04-維運.md
   └─ DB 備份、歷史表清理、frame log 保留期
```

**第 2 步只做一台。** 在那一台把問題全部排除、驗證通過，再批次部署其他機器，
否則同一個問題會在所有機器上重演。

---

## 尚未在實機驗證的項目

以下項目在本機 sandbox 無法測試，第一次部署時要特別確認：

| 項目 | 影響 | 相關文件 |
|---|---|---|
| 跨機器的實際網路（防火牆 8444 入站） | 沒開的話 frame 永遠卡 RUNNING | `02` |
| 專職算圖機以 Windows 服務執行時，看不看得到網路磁碟機 | 看不到的話所有 frame 都讀不到檔案 | `02` |
| 開機 / 登入時自動啟動 | — | `02` |
| `DEFAULT_FACILITY` 在 Windows RQD 上是否生效 | 不生效的話節點收不到 job | `02` |
| 容器是否沿用宿主的 DNS search 網域 | 解析不到節點名稱會卡 RUNNING | `01` |
| 共享儲存以 UNC 路徑端到端寫入與讀取 | CueWeb 看不到 log | `01` |
| Arnold / MtoA | 未測 | — |

完整的驗證狀態見 `notes/sandbox/19-驗證狀態總表.md`。

---

## 檔案一覽

```
notes/deploy/
  README.md                     本檔
  01-伺服器.md
  02-算圖節點.md
  03-工作站.md
  04-維運.md

  server/
    opencue.portainer.yml       主檔（Portainer 與 docker compose 共用）
    env.example                 環境變數範本
    build.yml                   自行 build 時疊加
    site.example.yml            DNS / 多台 extra_hosts 等站點設定
    init/                       初始化容器的原始碼
    registry.portainer.yml      自建 registry（使用 GHCR 時不需要）

  node/                         全部是純 ASCII（原因見 02）
    rqd-windows.conf            → C:\opencue\rqd.conf
    rqd-start.bat               → C:\opencue\rqd-start.bat
    rqd-start-hidden.vbs        工作站登入時啟動用
    hython-22.0.429.bat 等      → C:\opencue\bin\，DCC wrapper
    cuenimby-workstation.json   → %USERPROFILE%\.config\opencue\cuenimby.json

  client/
    opencue-client.yaml         → %APPDATA%\opencue\opencue.yaml
```
