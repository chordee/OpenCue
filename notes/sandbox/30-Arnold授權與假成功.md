# 30 — Arnold 在農場上拿不到授權，frame 卻顯示成功

正式做法整理在 [`notes/deploy/02-算圖節點.md` 第五節](../deploy/02-算圖節點.md#五呼叫-dccocrun)，本篇是查證紀錄。

環境：Maya 2027、MtoA（Arnold 7.5.1.1）、本機 RQD，2026-09-25。

---

## 一、發現經過

在 Maya 介面內以新版工具重新投遞 `scene_luffy_test.ma`（Arnold）2 格。兩格都是 SUCCEEDED、exit 0，
但 log 裡有：

```
[clm.v1] generic license checkout error (22)
ERROR   | aborting render because this is a batch render and abort_on_license_fail option is enabled
```

**Arnold 沒有算出任何圖，frame 卻被當成成功。**

回頭檢查同一個場景過去的紀錄：

| 時間 | 工具 | 結果 |
|---|---|---|
| 09-24 22:30（[`25` 第五節](25-Maya內投遞.md#五人工測試中發現的問題)記錄為「3 格成功、每格 98 秒」） | `Render-2027.bat` | 全部是授權失敗、中止算圖 |
| 09-25 03:06（記憶體耗盡那次） | `Render-2027.bat` | 同上 |
| 09-25 03:48 | `ocrun` | 同上 |

所以與 `ocrun`、`[UseHostEnvVar]` 的修改無關，**農場上的 Arnold 從一開始就沒有真正算過圖**。

---

## 二、原因：授權伺服器的環境變數沒有傳給 frame

直接執行 `ocrun maya 2027 Render -r file -s 1 -e 1 -cam persp1 ...`，只改環境變數：

| 環境 | 授權錯誤 | 輸出圖 |
|---|---|---|
| 完整的使用者環境 | 無 | 有 |
| RQD 的環境（含 `ALLUSERSPROFILE`、空的 `TZ`） | **有** | 無 |
| RQD ＋ `LOCALAPPDATA`、`USERPROFILE` | 有 | 無 |
| RQD ＋ `USERNAME`、`COMPUTERNAME`、`USERDOMAIN`、`PROGRAMDATA`、`HOMEDRIVE`、`HOMEPATH` | 有 | 無 |
| RQD ＋ `SOLIDANGLE_LICENSE` | 無 | **有** |
| RQD ＋ `RLM_LICENSE` | 無 | **有** |

這台機器的 Arnold 透過 RLM 授權伺服器取得授權，位置寫在使用者環境的 `SOLIDANGLE_LICENSE`。
桌面上的 Maya 讀得到，RQD 啟動的 frame 讀不到。

**修正**：寫進 `dcc.toml` 的 `[env]`（範本早已預留這一行，只是沒有實測）：

```toml
[env]
solidangle_LICENSE = '5053@<授權伺服器>'
```

修正後從農場算一格：20 秒完成，有輸出圖，log 沒有授權錯誤。
先前每格 50～100 秒，是在授權檢查上等到逾時。

同一時段 03:49 有一次授權模組的 `BREAKPOINT` 當機（`0x80000003`），發生在授權失敗的路徑上；
補上授權後沒有再出現。

---

## 三、假成功：`Render.exe` 在 Arnold 中止時仍回傳 0

授權問題修好了，但「失敗卻回報成功」這件事本身更危險：任何讓 Arnold 中止的原因
（授權伺服器斷線、授權數不足），農場都會顯示全部成功。

**對策**：`ocrun` 對 Maya 逐行檢查輸出，出現以下字串（不分大小寫）就讓 frame 以 exit 1 結束：

```
aborting render because
license checkout error
```

輸出仍然原樣寫進 frame log，最後多一行說明：

```
[ocrun] failing the frame, the output reported: ... [clm.v1] generic license checkout error (22)
```

程式本身回傳非 0 時，照原本的 exit code 結束，不受影響。

### 實測

| 情況 | 結果 |
|---|---|
| 單元測試（Windows、Linux 容器） | 7 項通過，包括「出現錯誤字串 → 1」與「輸出原樣轉出、非 0 保留」 |
| 暫時拿掉 `dcc.toml` 的授權，從農場算一格 | exit 1，frame 進入重試，log 最後有 `[ocrun] failing the frame` |
| 補回授權，從農場算一格 | exit 0、20 秒、有輸出圖，沒有被誤判 |

---

## 四、尚未驗證

- 其他 DCC 的「失敗卻回傳 0」：Houdini（Karma）、Nuke 都還沒有找出類似的情況，
  目前只有 Maya 有檢查字串
- 授權伺服器有、但授權數用完時的訊息是否同樣會被抓到
- `ADSKFLEX_LICENSE_FILE`、`foundry_LICENSE` 是否也需要（本機的 Maya、Nuke 在 frame 裡都能跑，推測不需要，但沒有逐一確認）
