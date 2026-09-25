# 32 — 節點的 tag 總長度超過 128 字元就註冊不上

正式做法整理在 [`notes/deploy/02-算圖節點.md` 第六節](../deploy/02-算圖節點.md#六派工標籤rqd_tags)，本篇是查證紀錄。

環境：全新重建的 sandbox（空的 DB），2026-09-25。

---

## 一、現象

照 [`deploy/02`](../deploy/02-算圖節點.md) 從頭設定工作站後啟動 RQD，`cueadmin -lh` 一直是空的。
RQD 的 log 停在 `RQD Started`，沒有任何錯誤。Cuebot 的 log：

```
HostReportHandler   : Unable to find host LAPTOP-ULJICLO8 ...
HostManagerService  : set LAPTOP-ULJICLO8 to the given allocation local.desktop
CueExceptionUtil    : ... PL/pgSQL function recalculate_tags(character varying) line 15 at EXECUTE;
                      ERROR: value too long for type character varying(128)
```

節點註冊到一半失敗，整筆資料沒有寫入。

---

## 二、原因

`recalculate_tags()` 把 `host_tag` 的所有 tag 以空白串起來，寫進 `host.str_tags`（`V1__Initial_schema.sql`）：

| 位置 | 上限 |
|---|---|
| 函式內的暫存變數 `full_str_tag` | 256 |
| **`host.str_tags` 欄位** | **128** |

範本的工作站設定註冊後的 tag（修正後實際寫入的結果）：

```
desktop desktop desktop general houdini22 houdini_22_0_429 maya_2027 maya2027 nuke17 nuke_17_0v1 rqdv-dev windows LAPTOP-ULJICLO8
```

**129 個字元**。`desktop` 出現三次：`RQD_TAGS` 開頭（讓 allocation 落在 `local.desktop`）、
`OVERRIDE_IS_DESKTOP = True`、allocation 本身。

舊的 sandbox 沒有遇到，是因為當時 `RQD_TAGS` 以 `general` 開頭，只有兩個 `desktop`，共 121 字元。
正式環境的節點若並存多個 DCC 版本，每多一個版本就多 10～16 個字元，一定會超過。

---

## 三、修正：加寬欄位

在 flyway image 加入工作室的 repeatable migration
[`R__Studio_widen_host_tags.sql`](../deploy/server/migrations/R__Studio_widen_host_tags.sql)：

- `host.str_tags` 改為 `VARCHAR(4000)`（與 `layer.str_tags` 相同）
- `recalculate_tags()` 的暫存變數改為 4000，其餘與 DB 中現行版本逐字相同

做法的選擇：

- **repeatable migration（`R__`）**：Flyway 在所有版本化 migration 之後執行，檔案內容不變就不會再跑。
  上游之後新增的 `V50`、`V51` 不會與它衝突
- **不改上游的檔案**：另寫 [`deploy/server/flyway.Dockerfile`](../deploy/server/flyway.Dockerfile)，
  與 `sandbox/flyway.Dockerfile` 相同，多複製 `notes/deploy/server/migrations/`；`build.yml` 改用它
- 沒有 view 依賴 `host.str_tags`（查 `pg_depend` 確認），`ALTER` 可以直接做
- Cuebot 的 Java 程式沒有檢查這個欄位的長度

---

## 四、實測

| 情況 | 結果 |
|---|---|
| 在現有 DB 上以 transaction 試跑後 rollback | 欄位暫時變成 4000，rollback 後回到 128 |
| 本機 build 的 image 套用到**已有資料、註冊失敗過**的 DB | `Migrating schema "public" with repeatable migration "Studio widen host tags"`；節點在下一次回報時自動註冊成功，`local.desktop`，tag 串 129 字元 |
| 同一個 image 部署**全新的 DB**（臨時的 postgres 容器） | 43 個 migration（42 個版本化 ＋ 1 個 repeatable），欄位 4000，show `testing` 與 5 個 allocation 照常建立 |
| **舊的** flyway image 對已套用 `R__` 的 DB 執行 | **exit 1**：`Validate failed ... Detected applied migration not resolved locally: Studio widen host tags` |

最後一項的意思是：DB 一旦套用過這個 migration，**就不能再用不含它的 flyway image**。
重新部署前，stack 的 `OPENCUE_FLYWAY_IMAGE` 必須已經換成工作室的新版。

---

## 五、尚未驗證

- 以 GitHub Actions 發布的正式 image（本篇用的是本機 build 的 image）
- Portainer 以新 image 從空的 DB 部署整個 stack
- 上游日後若重新定義 `recalculate_tags()`，要確認暫存變數的長度是否又被改回 256
