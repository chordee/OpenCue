# OpenCue Sandbox 建置筆記

記錄在本機把 OpenCue sandbox 環境架起來的完整過程、踩到的坑、以及
「之後要在正式 Linux 宿主 + Portainer 上架設」時需要改掉的地方。

## 背景與目標

- 本機是 Windows 11，但**最終的 Docker 宿主預期是 Linux**，入口可能掛 Portainer。
- 因此測試刻意**全程在 WSL2 Ubuntu 內操作**，而不是 Windows 原生路徑。
  理由：路徑、權限、bind mount 行為跟正式 Linux 宿主一致，筆記可直接搬過去；
  若遷就 Windows，會養出一堆正式環境用不到的 workaround。
- Repo 是 fork：`chordee/OpenCue`，工作分支 `studio/main`（原名 `demo/sandbox-test`，同時是 GitHub 上的預設分支）。

## 本目錄與 `notes/deploy/` 的分工

| 目錄 | 內容 |
|---|---|
| **`notes/deploy/`** | **正式部署**：只寫怎麼做，設定檔都在那裡，現成的 GHCR image 也列在那裡 |
| `notes/sandbox/`（本目錄） | **測試紀錄**：過程、踩過的坑、原始碼依據與實測數據 |

**要部署的話，從 `notes/deploy/README.md` 開始。** 本目錄是那些做法的證據，
遇到問題或想知道「為什麼要這樣做」時再回來查。

## 筆記索引

| 檔案 | 內容 |
|---|---|
| `00-環境與前置.md` | 本機環境盤點、版本、必要目錄 |
| `01-平台差異與Portainer.md` | 官方 compose 對 Linux 宿主 / Portainer 不友善之處 |
| `02-目標架構.md` | 依 IT 描述推導的正式環境架構與注意事項 |
| `03-容器說明.md` | stack 裡每個容器的角色、設定與正式環境注意事項 |
| `04-部署過程.md` | 實際啟動步驟、踩到的坑與結果 |
| `05-可回饋上游的問題.md` | 本次發現的 OpenCue 專案本身問題與建議修法 |
| `06-資源用量實測.md` | 實測的 CPU/記憶體用量，用於判斷主機規格 |
| `07-Portainer部署實錄.md` | 用 Portainer API 部署與驗證的完整流程 |
| `08-Windows節點實錄.md` | Windows 原生 RQD 的安裝、設定與五個坑 |
| `09-NIMBY與混合機隊.md` | 工作站與專職算圖機的分工、CueNIMBY 時段排程實測 |
| `10-Windows用戶端工具.md` | CueGUI / CueSubmit 在 Windows 的安裝與設定路徑 |
| `11-正式部署風險與待辦.md` | 規模化後才會遇到的問題：DNS、UNC、防火牆、初始化、EDR、備份 |
| `12-真實DCC算圖.md` | Houdini / Maya / Nuke 實際算圖、多版本共存與環境變數的坑 |
| `13-CueWeb與RESTGateway.md` | 網頁 UI 部署、JWT 驗證、跨平台 frame log 的解法 |
| `14-Registry流程.md` | build → push → Portainer pull 完整驗證與正式環境要求 |
| `15-空間規劃.md` | 各項目的實測用量、成長特性與清理策略 |
| `16-Portainer與SSH的分工.md` | 哪些工作 Portainer 做得到、哪些需要宿主權限 |
| `17-故障排查與常見疏失速查.md` | **遇到問題先看這篇**：報錯現象 ➔ 疏失對準 ➔ 解法對照手冊 |
| `18-三種角色的準備清單.md` | 依機器角色展開的準備清單（**已由 `notes/deploy/` 取代**） |
| `19-驗證狀態總表.md` | **哪些驗過、哪些沒驗**。各篇的「尚未驗證」段落可能過時，以此為準 |
| `20-相依性與維運操作.md` | DEPEND 狀態、chain/diamond/fan-in 實測、常用維運指令 |
| `21-Service與資源模型.md` | Layer / Username / Facility / Service / Dependency 的關係與用途 |
| `22-兩種部署路線.md` | **同一份 stack 兩種部署法**：Portainer（image 走 registry）或 docker compose（在宿主 build）；初始化容器 |
| `lab/` | 測試用的腳本（投遞、算圖、磁碟機測試）與本機 sandbox 的環境變數紀錄 |

## 閱讀建議（依工作角色導讀）

- **想快速掌握架構與運作原理**：
  先讀 `02-目標架構.md`（含 Frame 端到端生命週期圖解）與 `03-容器說明.md`。
- **負責部署伺服器與算圖節點**：
  依 `notes/deploy/` 的步驟進行；背景細節見 `07-Portainer部署實錄.md`、`08-Windows節點實錄.md`、`14-Registry流程.md`。
- **負責藝術家工作站與 DCC Pipeline**：
  詳讀 `09-NIMBY與混合機隊.md`、`10-Windows用戶端工具.md`、`12-真實DCC算圖.md`（Houdini/Maya/Nuke 包裝實務）。
- **IT 網管、資安與維運規劃**：
  詳讀 `11-正式部署風險與待辦.md`、`15-空間規劃.md`、`16-Portainer與SSH的分工.md`。
- **實際要動手部署（依機器角色查該準備什麼）**：
  直接翻閱 **`18-三種角色的準備清單.md`**，它把散在各篇的準備工作
  依 server / workstation / render host 三種角色重新整理成檢查清單，
  並附建議的部署順序。
- **上線除錯與突發狀況**：
  直接翻閱 **`17-故障排查與常見疏失速查.md`**，依畫面報錯快速對準可能疏失點。

## 名詞對照

| 元件 | 角色 |
|---|---|
| Cuebot | 排程器，農場大腦，對外開 gRPC 8443 |
| RQD | 跑在 render node 上的 daemon，實際執行 frame |
| Flyway | DB schema migration 工具，跑完就結束 |
| PostgreSQL | 所有 job / frame / host 狀態的儲存 |
| REST Gateway | 把 gRPC 包成 HTTP，給 CueWeb 用 |
| CueWeb | 網頁版監控 UI |
| CueGUI | 桌面版監控 UI（Cuetopia / CueCommander） |
| CueSubmit | 投 job 的桌面工具 |
| CueNIMBY | 藝術家工作站的系統列鎖定與排程工具 |

