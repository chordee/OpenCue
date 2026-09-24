# 14 — Registry 流程

`13` 已確認自建 image 不是選項而是必要步驟。這一份把
**build → push → Portainer pull** 整條走完並驗證。

## 為什麼一定要 registry

| 原因 | 說明 |
|---|---|
| CueWeb / REST Gateway 沒有公開 image | Docker Hub 上是 404 |
| 公開的 cuebot 版本落後 | 最新 tag `1.19.1`，原始碼是 `1.34.4` |
| Portainer 沒有 build context | 只能 `image:`，不能 `build:` |
| 認證設定是 build-time | CueWeb 的 `NEXT_PUBLIC_AUTH_PROVIDER` 必須在 build 時決定 |

## 架設 registry

範本見 `notes/deploy/server/registry.portainer.yml`。本次測試用的最小指令：

```bash
docker run -d --name opencue-registry --restart unless-stopped \
  -p 5000:5000 -v opencue-registry-data:/var/lib/registry registry:2
```

驗證：

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/v2/
# 200
```

**registry 是獨立的基礎設施，不要放進 opencue 那個 stack** ——
它的生命週期與 OpenCue 無關，而且 OpenCue stack 更新時會依賴它。

## Tag 慣例

**不要用 `latest`。** 本次使用：

```
<版本>-<commit 短 SHA>
1.34.4-fe0b32bf
```

版本來自 `VERSION.in`（`1.34`）加上建置編號，SHA 來自 `git rev-parse --short HEAD`。
這樣任何一個跑在正式環境的容器都能追溯到確切的原始碼。

## Push

```bash
VER=1.34.4-$(git rev-parse --short HEAD)
REG=localhost:5000/opencue

docker tag opencue-cuebot:latest        $REG/cuebot:$VER
docker tag opencue-flyway:latest        $REG/flyway:$VER
docker tag opencue/rest-gateway:latest  $REG/rest-gateway:$VER
docker tag opencue/cueweb:latest        $REG/cueweb:$VER

for n in cuebot flyway rest-gateway cueweb; do
    docker push $REG/$n:$VER
done
```

**注意 image 名稱的來源不一致**：`cuebot` 與 `flyway` 由 compose 自動命名為
`opencue-cuebot` / `opencue-flyway`（專案名 + 服務名），而 `rest-gateway`
與 `cueweb` 因為 compose 裡有 `image:` 宣告，被標成 `opencue/rest-gateway`
與 `opencue/cueweb`。第一次操作很容易弄錯。

驗證 registry 內容：

```bash
curl -s http://localhost:5000/v2/_catalog
{"repositories":["opencue/cuebot","opencue/cueweb","opencue/flyway","opencue/rest-gateway"]}

curl -s http://localhost:5000/v2/opencue/cuebot/tags/list
{"name":"opencue/cuebot","tags":["1.34.4-fe0b32bf"]}
```

## Portainer 從 registry 部署

把 stack 的環境變數改成 registry 參照：

```
OPENCUE_CUEBOT_IMAGE=localhost:5000/opencue/cuebot:1.34.4-fe0b32bf
OPENCUE_FLYWAY_IMAGE=localhost:5000/opencue/flyway:1.34.4-fe0b32bf
OPENCUE_REST_GATEWAY_IMAGE=localhost:5000/opencue/rest-gateway:1.34.4-fe0b32bf
OPENCUE_CUEWEB_IMAGE=localhost:5000/opencue/cueweb:1.34.4-fe0b32bf
```

更新時帶上 `pullImage: true`：

```bash
curl -sk -X PUT -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  --data-binary @payload.json \
  "https://localhost:9443/api/stacks/3?endpointId=3"
```

payload 的 `pullImage` 欄位控制是否重新拉取。

### 驗證方式：先刪掉本機 tag

**直接部署無法證明有 pull**，因為剛 push 完本機也有同樣的 image。
所以先刪除本機的 registry tag：

```bash
for n in cuebot flyway rest-gateway cueweb; do
    docker rmi localhost:5000/opencue/$n:1.34.4-fe0b32bf
done
docker images | grep localhost:5000     # 應為空
```

（保留原始的 build tag 當後路，刪的只是 registry 參照的那個 tag。）

再透過 Portainer 更新 stack，結果：

```
NAMES                  IMAGE                                                 STATUS
opencue-cueweb         localhost:5000/opencue/cueweb:1.34.4-fe0b32bf         Up (healthy)
opencue-rest-gateway   localhost:5000/opencue/rest-gateway:1.34.4-fe0b32bf   Up (healthy)
opencue-cuebot         localhost:5000/opencue/cuebot:1.34.4-fe0b32bf         Up (healthy)
opencue-flyway         localhost:5000/opencue/flyway:1.34.4-fe0b32bf         Exited (0)
opencue-db             postgres:15.1                                         Up (healthy)
```

本機的 registry tag 重新出現 → **確實是從 registry 拉下來的**。

部署後農場功能不受影響：

```
Host             ... State  Locked  Alloc
LAPTOP-ULJICLO8  ... UP     LOCKED  local.desktop     <- Windows RQD 重新註冊
                                       LOCKED 是 CueNIMBY 排程，正確

docker exec opencue-cuebot ls /opt/opencue/*.jar
/opt/opencue/cuebot-1.34-custom-all.jar

POST /api/job/getjobs  ->  HTTP 200
```

## 正式環境還需要處理的

### 非 localhost 一律需要 TLS

Docker 只對 `localhost` / `127.0.0.1` 的 registry 預設允許明文 HTTP。
正式環境的 registry 在另一台機器上，**必須**擇一：

- 提供有效的 TLS 憑證（建議）
- 在每一台會拉取的 Docker daemon 上設定 `insecure-registries`（不建議）

若用 `insecure-registries`，Linux 宿主要改 `/etc/docker/daemon.json` 並重啟
daemon —— 那需要 SSH 或 IT 協助，**Portainer 本身改不了這個**。
這會回到「只有 Portainer 存取權」的限制上，值得提早跟 IT 確認。

### 認證

最小可用版本沒有認證，任何能連到 5000 的人都能推送與拉取。
正式環境至少要 htpasswd，Portainer 端則在
Registries 設定裡存好憑證供 stack 使用。

### 空間管理

image 會持續累積。`registry.portainer.yml` 已開啟
`REGISTRY_STORAGE_DELETE_ENABLED`，但**刪除 manifest 之後還要執行
garbage-collect 才會真的回收磁碟空間**：

```bash
docker exec opencue-registry \
  bin/registry garbage-collect /etc/docker/registry/config.yml
```

本次四個 image 的大小：

| Image | 大小 |
|---|---|
| cueweb | 2.52 GB |
| flyway | 2.15 GB |
| cuebot | 1.06 GB |
| rest-gateway | 184 MB |

**每個版本約 6 GB。** 保留十個版本就是 60 GB，需要規劃保留策略。
（`flyway` 有 2.15 GB 對一個 one-shot 容器而言偏大，見 `04`。）

### 備份

`opencue-registry-data` volume 若遺失，所有版本的 image 都要重建。
若建置機器與原始碼都還在，重建是可行的，但會花不少時間。
建議納入備份，或至少確保能從 CI 重現。

## 完整的正式部署流程

```
建置機器                        Registry                  Linux 宿主
  git clone <repo>
  git checkout <tag>
  docker compose build
    cuebot / flyway
    rest-gateway / cueweb
  docker tag  ...:<ver>-<sha>
  docker push  ──────────────>  registry.studio.local
                                  /opencue/cuebot:<ver>-<sha>
                                  /opencue/flyway:<ver>-<sha>
                                  /opencue/rest-gateway:<ver>-<sha>
                                  /opencue/cueweb:<ver>-<sha>
                                        │
                                        │ pull
                                        ▼
                                                        Portainer stack
                                                          更新環境變數的
                                                          image tag 即可
                                                          完成版本升級
```

**升級與回滾都只是改 stack 的環境變數**，這正是把 image 參照抽成變數的用意。

---

## 升級與回滾實測

「改 stack 的環境變數即可升級／回滾」先前只是推論，這一份是實測。

### 測試方法：做出可分辨的兩個版本

直接把同一個 image 標成兩個 tag 無法證明什麼 ——
容器跑的是同一份內容，只是名字不同。

所以用現有 image 加一層標記做出真正不同的版本，
**只多一層，不需要重新編譯 Java**：

```dockerfile
FROM localhost:5000/opencue/cuebot:1.34.4-fe0b32bf
RUN echo "ROLLBACK_TEST_V2" > /opt/opencue/VERSION_MARKER
LABEL opencue.rollback.test="v2"
```

```bash
docker build -t localhost:5000/opencue/cuebot:1.34.4-v2test .
docker push localhost:5000/opencue/cuebot:1.34.4-v2test
```

### 升級

只改 stack 的一個環境變數，`pullImage: true`：

```
OPENCUE_CUEBOT_IMAGE=localhost:5000/opencue/cuebot:1.34.4-v2test
```

結果：

```
opencue-cuebot | localhost:5000/opencue/cuebot:1.34.4-v2test | Up (healthy)
docker exec opencue-cuebot cat /opt/opencue/VERSION_MARKER
ROLLBACK_TEST_V2
```

### 回滾

把環境變數改回原值，重新 PUT：

```
opencue-cuebot | localhost:5000/opencue/cuebot:1.34.4-fe0b32bf | Up (healthy)
docker exec opencue-cuebot cat /opt/opencue/VERSION_MARKER
cat: /opt/opencue/VERSION_MARKER: No such file or directory
```

**標記檔消失證明跑的真的是舊 image**，不只是 tag 字串換掉。

兩個節點在 Cuebot 重啟後都自動重新註冊，狀態 `UP`。

Portainer API 呼叫本身約 **53 秒**（含 pull 與重建容器）。

## 【重要】升級時執行中的 frame 不會被中斷

這是正式環境最關心的問題：**能不能在有工作在跑的時候升級？**

實測方法：送出一個 150 秒的長 frame，等它進入 `RUNNING` 後，
在執行中途觸發 stack 更新。

結果：

```
更新前    RUNNING@render02
更新中    RUNNING@render02        <- 存活
更新中    RUNNING@render02
更新後    SUCCEEDED@render02  exit 0
```

同時在節點容器內確認 `sleep 150` 的行程**全程沒有被中斷**。

**原因是架構使然**：Cuebot 是**無狀態**的，frame 由 RQD 獨立執行，
Cuebot 回來後 RQD 再把結果回報上去。

**實務意義**：Cuebot 的升級不需要等農場清空，
可以在有工作執行時進行。但仍有兩點要注意：

| 注意 | 說明 |
|---|---|
| **停機期間不會派新工作** | 約 1 分鐘的空窗，閒置節點會空等 |
| **停機時間不能太長** | RQD 有重試上限；超過的話 frame 可能被判定為孤兒 |

本次停機約 1 分鐘，frame 毫無影響。更長的停機（例如 DB 遷移）
需要另外評估。

## 坑：registry 的刪除有兩個前提

清理測試 image 時踩到的，對 `15` 的空間管理有直接影響。

### 前提一：`REGISTRY_STORAGE_DELETE_ENABLED` 必須在啟動時設定

```bash
docker exec opencue-registry printenv | grep DELETE
（沒有輸出）
```

本次的 registry 是用最簡單的 `docker run registry:2` 起的，
沒有帶這個環境變數，**因此無法刪除任何 manifest**。

**這個設定無法事後補上** —— 必須重新啟動 registry 才會生效。
`notes/deploy/server/registry.portainer.yml` 的範本已包含它，
但**正式部署時要確認真的有帶上**，否則之後想清理會發現做不到。

### 前提二：現代的 buildx 推送的是 OCI manifest

查詢 manifest digest 時用傳統的 Docker v2 header 會得到 404：

```bash
curl -I -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  http://registry/v2/<repo>/manifests/<tag>
HTTP/1.1 404 Not Found
```

加上 OCI 的型別才查得到：

```bash
curl -I -H "Accept: application/vnd.oci.image.manifest.v1+json, \
application/vnd.docker.distribution.manifest.v2+json, \
application/vnd.oci.image.index.v1+json" \
  http://registry/v2/<repo>/manifests/<tag>

HTTP/1.1 200 OK
Content-Type: application/vnd.oci.image.index.v1+json
Docker-Content-Digest: sha256:ebab3a78...
```

**寫清理腳本時一定要帶完整的 Accept header**，否則會誤判成「該 tag 不存在」
而跳過，導致空間永遠回收不了。

### 完整的刪除流程

```bash
# 1. 取得 digest（注意 Accept header）
DIGEST=$(curl -s -I \
  -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  http://registry/v2/<repo>/manifests/<tag> \
  | grep -i docker-content-digest | tr -d '\r' | cut -d' ' -f2)

# 2. 刪除 manifest（需要 REGISTRY_STORAGE_DELETE_ENABLED=true）
curl -X DELETE http://registry/v2/<repo>/manifests/$DIGEST

# 3. 回收磁碟空間（沒有這一步，空間不會真的釋放）
docker exec <registry容器> \
  bin/registry garbage-collect /etc/docker/registry/config.yml
```
