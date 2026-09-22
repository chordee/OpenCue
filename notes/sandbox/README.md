# OpenCue Sandbox 建置筆記

記錄在本機把 OpenCue sandbox 環境架起來的完整過程、踩到的坑、以及
「之後要在正式 Linux 宿主 + Portainer 上架設」時需要改掉的地方。

## 背景與目標

- 本機是 Windows 11，但**最終的 Docker 宿主預期是 Linux**，入口可能掛 Portainer。
- 因此測試刻意**全程在 WSL2 Ubuntu 內操作**，而不是 Windows 原生路徑。
  理由：路徑、權限、bind mount 行為跟正式 Linux 宿主一致，筆記可直接搬過去；
  若遷就 Windows，會養出一堆正式環境用不到的 workaround。
- Repo 是 fork：`chordee/OpenCue`，測試分支 `demo/sandbox-test`。

## 筆記索引

| 檔案 | 內容 |
|---|---|
| `00-環境與前置.md` | 本機環境盤點、版本、必要目錄 |
| `01-平台差異與Portainer.md` | 官方 compose 對 Linux 宿主 / Portainer 不友善之處 |
| `02-目標架構.md` | 依 IT 描述推導的正式環境架構與注意事項 |
| `03-容器說明.md` | stack 裡每個容器的角色、設定與正式環境注意事項 |
| `04-部署過程.md` | 實際啟動步驟、踩到的坑與結果 |
| `05-可回饋上游的問題.md` | 本次發現的 OpenCue 專案本身問題與建議修法 |

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
