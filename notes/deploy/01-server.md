# 01 — OpenCue Server

Linux + Docker host hosting Cuebot, PostgreSQL, REST Gateway, and CueWeb. **Does not participate in rendering.**

---

## 1. Pre-deployment IT Requirements

These prerequisites exist outside Docker and cannot be managed via Portainer.

### 1.1 Inbound/Outbound Port Matrix

| Source | Destination | Port | Purpose | Requirement |
|---|---|---|---|---|
| Render Nodes, Artist Workstations | OpenCue Server | **8443** | RQD registration/heartbeats, CueGUI / CueSubmit gRPC | **Mandatory** |
| OpenCue Server | Render Nodes, Artist Workstations | **8444** | Cuebot callback to RQD for frame dispatching | **Mandatory** (Inbound required on nodes) |
| Web Browsers | OpenCue Server | 3000 | CueWeb web UI | When using CueWeb |
| — | — | 5432, 8448 | PostgreSQL DB, REST Gateway | **Do not expose** (Internal container network only) |

**Important: Ports 8443 and 3000 lack authentication by default.** Reaching port 8443 allows control over the entire render farm via `cueadmin`, and reaching port 3000 permits killing/retrying jobs in CueWeb. **Expose these ports strictly to trusted studio internal networks.**

Reference: [`notes/sandbox/11` Section 3](../sandbox/11-production-risks-and-todos.md#3-network-communication-matrix-and-firewall-requirements).

### 1.2 Shared Storage Mounted on Host

CueWeb requires direct filesystem access to frame logs. Ensure IT mounts the shared frame log directory (the same location written to by render nodes) on the Docker host, e.g. at `/mnt/opencue/logs`.

- If web thumbnail previews are desired, render output storage must also be mounted, e.g. `/mnt/projects/render`.
- If viewing logs in CueWeb is not required, this step may be omitted.

Reference: [`notes/sandbox/13`](../sandbox/13-cueweb-and-rest-gateway.md), [`notes/sandbox/16`](../sandbox/16-portainer-and-ssh-division.md) (Alternatively, CIFS Docker volumes can be used without host mounts, but `cifs-utils` is still required on the host).

### 1.3 DNS Resolution

Cuebot connects back to render nodes using their **short hostnames** (e.g. `RENDER01`). If the host OS can resolve short hostnames via studio DNS search domains, Docker containers inherit this configuration automatically without extra setup.

Verify on the Docker host:

```bash
getent hosts RENDER01        # Must resolve successfully
```

Reference: [`notes/sandbox/11` Section 1](../sandbox/11-production-risks-and-todos.md#1-multi-node-dns-resolution-avoid-hardcoded-extra_hosts), [`notes/sandbox/22` Section 6](../sandbox/22-two-deployment-routes.md#6-primary-manifest-architecture-environment-driven-configuration).

### 1.4 Docker Container Log Rotation

Docker's default JSON log driver **does not limit log file size**. Configure log rotation in `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
```

Reference: [`notes/sandbox/15` Section 6](../sandbox/15-storage-planning.md#6-docker-host-container-log-rotation).

### 1.5 Internet Access to ghcr.io

Required only when pulling pre-built images from GitHub Container Registry (GHCR). If blocked by corporate firewalls or proxies, set up a self-hosted private registry instead (see Section 6).

---

## 2. Choosing a Deployment Route

| Access Level | Deployment Route |
|---|---|
| Portainer account only | **A. Portainer** (Recommended) |
| SSH access with `docker` permissions | Either Route A or Route B |
| Source code modifications needed | **B. Docker Compose** (Build locally on host) |

Both routes share the identical compose file [`server/opencue.portainer.yml`](server/opencue.portainer.yml), **requiring no changes to the YAML itself**.

Reference: [`notes/sandbox/22`](../sandbox/22-two-deployment-routes.md) (Both routes verified in practice).

---

## 3. Route A: Portainer

### 3.1 Prepare Environment Variables

Copy [`server/env.example`](server/env.example) and populate the following **Mandatory** fields:

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL root/app database password |
| `JWT_SECRET` | Secret token used by CueWeb to communicate with REST Gateway (random long string) |
| `CUEWEB_NEXTAUTH_SECRET` | NextAuth session secret (random long string) |
| `CUE_FRAME_LOG_DIR` | Shared frame log directory, **must use forward-slash UNC syntax**, e.g. `//fileserver/opencue/logs` |
| Five `OPENCUE_*_IMAGE` vars | Pre-configured with GHCR public images; modification typically unnecessary |

Generate random secret strings using:

```bash
openssl rand -base64 32
```

Other commonly adjusted settings:

| Variable | Description |
|---|---|
| `CUEWEB_PUBLIC_URL` | Web address accessed by users in their browsers |
| `FRAME_LOG_MOUNT_SOURCE` | Path where frame log share is mounted on the host (Section 1.2) |
| `FRAME_LOG_MOUNT_TARGET`, `CUEWEB_LOG_ROOTS` | **Both must match `CUE_FRAME_LOG_DIR` with one leading slash removed**, e.g. `/fileserver/opencue/logs`. If mismatched, CueWeb reports "Log file not found" |
| `OPENCUE_INIT_SHOWS` / `OPENCUE_INIT_SERVICES` | Bootstrap shows and services automatically created post-deployment (Section 4) |

**Why `CUE_FRAME_LOG_DIR` requires forward-slash UNC syntax**: This path is written by Windows render nodes and subsequently read by CueWeb inside a Linux container. Drive letters (e.g. `L:/...`) cannot be resolved inside Linux containers, causing CueWeb to return HTTP 400. The `//server/share/...` forward-slash UNC syntax is the only cross-platform representation valid on both sides.
Reference: [`notes/sandbox/13`](../sandbox/13-cueweb-and-rest-gateway.md), [`notes/sandbox/11` Section 2](../sandbox/11-production-risks-and-todos.md#2-network-drive-letters-are-supported-with-one-exception).

### 3.2 Create the Stack in Portainer

1. Navigate to Portainer -> **Stacks** -> **Add stack**.
2. Name: `opencue` (Cannot collide with an existing stack; delete legacy stacks prior to recreating).
3. Build method: Select **Repository** (Recommended):

   | Field | Value |
   |---|---|
   | Repository URL | `https://github.com/chordee/OpenCue` |
   | Repository reference | `refs/heads/studio/deploy` (**Do not use** `studio/main` or `studio/release`; see rationale below) |
   | Compose path | `notes/deploy/server/opencue.portainer.yml` (Relative to repo root) |
   | Authentication | Disabled (Public repo) |

   If the Docker host cannot access GitHub directly, choose **Web editor** and paste the raw content of [`server/opencue.portainer.yml`](server/opencue.portainer.yml).
4. Environment variables: Click **Load variables from .env file** and upload your populated `.env`, or manually add rows.
5. Under Repository mode, toggle **GitOps updates** on, set Mechanism to **Polling**, with an interval of 5–15 minutes.
6. Click **Deploy the stack**.

The advantage of Repository mode is that YAML modifications in git are synchronized automatically without manual copy-pasting.

**Why track `studio/release` instead of `studio/main`**:
`studio/main` is the daily active branch where notes, experimental scripts, and iterative changes are frequently committed. If production tracks it directly, **any push will automatically deploy to production within minutes**, including faulty YAML definitions. The `studio/release` branch is advanced only when production rollouts are intentionally approved, enabling clear release boundaries and simple rollbacks. See [`04-operations.md` Section 1](04-operations.md#1-upgrades-and-rollbacks).

**Why `studio/deploy` instead of `studio/release`**:
Portainer refuses to clone a repository containing symlinks (`repository contains a symlink, which is not allowed for security reasons`), and the upstream source tree contains several. `studio/deploy` holds only `notes/deploy/server/` at the same paths, so the Compose path above is unchanged. It is generated, never edited by hand: the **Studio deploy branch** workflow ([`.github/workflows/studio-deploy-branch.yml`](../../.github/workflows/studio-deploy-branch.yml)) commits the current `notes/deploy/server/` of `studio/release` to it on every push to `studio/release`, and skips the commit when those files did not change.

Reference: [`notes/sandbox/23`](../sandbox/23-portainer-git-mode.md).

If mandatory environment variables are missing, deployment fails immediately with explicit diagnostics:

```
required variable POSTGRES_PASSWORD is missing a value: mandatory setting
```

### 3.3 Update Behaviors in Repository Mode

| Scenario | Behavior |
|---|---|
| Push to `studio/main` | **Does not trigger deployment** |
| Push to `studio/release` (No change under `notes/deploy/server/`) | `studio/deploy` is not updated, so **no deployment** |
| Push to `studio/release` (Other files under `notes/deploy/server/` modified) | Triggers deployment, but **only re-runs flyway and init**; active services experience zero downtime |
| Push to `studio/release` (YAML modified) | **Recreates only services with altered configurations** (e.g. changing Cuebot CLI flags restarts Cuebot only) |
| Environment variables altered in Portainer UI | Does not apply automatically; requires clicking **Pull and redeploy**, which **recreates all containers** |
| Image tag upgrades | **Never happens automatically**. Tags reside in Portainer environment variables and require manual update (see [`04-operations.md`](04-operations.md)) |
| Clicking **Pull and redeploy** | **Forcefully recreates all containers**, incurring brief service interruption; do not click casually |

Note: The Webhook URL mechanism **requires no authentication**; keep the UUID secret.

### 3.4 Initial Deployment Duration

The 5 container images total approximately 6 GB. Downloading from GHCR during initial deployment can take 30+ minutes depending on network bandwidth. Portainer remains busy waiting until all image layers are downloaded; this loading delay is expected.

- You may ask IT to pre-pull these 5 images directly on the Docker host via `docker pull`.
- Reverse proxies in front of Portainer might time out during deployment, but the process continues safely in the background.

Reference: [`notes/sandbox/22` Section 8](../sandbox/22-two-deployment-routes.md#8-publishing-images-to-github-container-registry-ghcr).

---

## 4. Bootstrapping: Shows, Subscriptions, and Services

The `init` service inside the stack runs automatically once Cuebot becomes healthy, configuring items defined in environment variables:

```
OPENCUE_INIT_SHOWS=projA,projB
OPENCUE_INIT_SERVICES=[{"name":"houdini2204","tags":["houdini_22_0_429"],"min_memory_gb":4}]
```

- **Idempotent**: Runs on every stack update without overwriting or resetting existing entities.
- **Modifying existing services**: Service modifications must be carried out in CueGUI / CueWeb; updating environment variables has no retroactive effect on existing records.
- Service `tags` must match `RQD_TAGS` in the node's `rqd.conf`. **Do not include `general` alongside specific version tags**, or version binding fails due to regex OR matching semantics.
- To configure new DCC versions across server, nodes, and workstations, refer to [`04-operations.md` "Adding New DCC Versions"](04-operations.md#adding-new-dcc-versions).

### Critical: New Shows Must Subscribe to Node Allocations

If a show has no subscription to a given allocation, nodes in that allocation **will never receive jobs from that show**, accompanied by **zero error warnings**.

The `init` container subscribes to `local.general`, `local.desktop`, and `cloud.general` by default. Artist workstations commonly reside in `local.desktop`; ensure it is not omitted. If custom allocations exist, append them to `OPENCUE_INIT_ALLOCS`.

Reference: [`notes/sandbox/22` Section 5](../sandbox/22-two-deployment-routes.md#5-initialization-container-init), [`notes/sandbox/17` Scenario 22](../sandbox/17-troubleshooting.md#scenario-22-jobs-submitted-to-newly-created-show-stuck-in-waiting).

### Shows Cannot Be Deleted Once Created

As long as a show has processed at least one job, it cannot be deleted in OpenCue—it can only be disabled. **Plan naming carefully**; avoid using production environments for arbitrary testing.
Reference: [`notes/sandbox/20`](../sandbox/20-dependencies-and-operations.md).

---

## 5. Route B: Docker Compose

Requires host SSH and `docker` privileges.

```bash
git clone https://github.com/chordee/OpenCue
cd OpenCue/notes/deploy/server
cp env.example .env              # Configure variables as detailed in Section 3
```

Deploying directly with pre-built GHCR images:

```bash
docker compose --env-file .env -f opencue.portainer.yml up -d
```

Building from source on the host (image names in `.env` can be customized, e.g. `opencue/cuebot:local`):

```bash
docker compose --env-file .env -f opencue.portainer.yml -f build.yml up -d --build
```

Trade-offs of building on the Docker host:
- Build cache requires ~**50 GB** disk space; Cuebot compilation takes ~10 minutes, consuming 100% CPU during that window (Reference: [`notes/sandbox/15`](../sandbox/15-storage-planning.md), [`notes/sandbox/22` Section 7](../sandbox/22-two-deployment-routes.md#7-route-b-empirical-benchmark)).
- Outbound access to Maven, npm, and PyPI mirrors is required.
- Stacks managed via CLI offer only limited visibility and management inside Portainer.

### Site-specific Overrides

If the Docker host cannot resolve render node short names, customize `site.example.yml` and overlay it:

```bash
cp site.example.yml site.yml
docker compose --env-file .env -f opencue.portainer.yml -f site.yml up -d
```

Route A does not support file overlays directly; incorporate custom configurations directly into the Portainer Web editor if required.

---

## 6. Self-hosted Registry (When GHCR is Inaccessible)

Used when the host cannot connect to ghcr.io, or when deploying customized images:

1. Deploy [`server/registry.portainer.yml`](server/registry.portainer.yml) as an independent stack.
2. Build and push from your workstation/dev machine:

   ```bash
   cd notes/deploy/server
   docker compose --env-file .env -f opencue.portainer.yml -f build.yml build
   docker compose --env-file .env -f opencue.portainer.yml -f build.yml \
     push flyway cuebot rest-gateway cueweb init
   ```

   `push` must explicitly enumerate services to avoid attempting to push external base images like `postgres:15.1`.

3. Update the 5 image path variables in `env.example` to point to the internal registry.

**Production internal registries require TLS and authentication** (unverified in sandbox). Without TLS, every Docker host pulling images must configure `insecure-registries` in `daemon.json`, necessitating Docker engine restarts.

Reference: [`notes/sandbox/14`](../sandbox/14-registry-workflow.md).

---

## 7. Post-deployment Verification

```bash
# 1. Container health: flyway and init should be Exited (0), others Healthy.
#    During initial deployment, the last lines of flyway logs may show 3 lines of
#    duplicate key ... "c_task_lock_pk" because upstream seed and migrations insert identical keys.
#    This is benign and does not affect operation.
docker ps -a --filter name=opencue-

# 2. Inspect initialization actions
docker logs opencue-init

# 3. Verify CueWeb response
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000     # Expect: 200

# 4. Once render nodes register: Verify Cuebot resolves hostnames and reaches port 8444
docker exec opencue-cuebot getent hosts RENDER01
docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/RENDER01/8444" && echo OK || echo FAIL'
```

If you only possess Portainer access, verify steps 1 and 2 in the Portainer Containers interface (inspect status and logs), and run step 4 via the container **Console**.

**Failure in Step 4 manifests as frames stuck in `RUNNING` indefinitely with zero log output**, while the host list appears normal in CueGUI. Always verify this step once a node comes online.

---

## 8. Monitoring Stack (Optional)

[`server/monitoring.portainer.yml`](server/monitoring.portainer.yml) is a standalone stack comprising Prometheus, Grafana, and PostgreSQL exporter. Configurations use compose inline `configs`, allowing direct Portainer deployment without host file mounts.

1. Ensure the `opencue` stack is fully deployed first (the monitoring stack connects to its existing `opencue` Docker network).
2. Create a new stack, paste `monitoring.portainer.yml`, and supply environment variables:

   | Variable | Description |
   |---|---|
   | `POSTGRES_PASSWORD` | Identical to `POSTGRES_PASSWORD` used in the opencue stack |
   | `GRAFANA_ADMIN_PASSWORD` | Admin password for Grafana web interface |

3. Open `http://<server-ip>:3001` in your browser. Go to Dashboards -> Import, and import:
   `sandbox/config/grafana/dashboards/PostgreSQL.json`

- **Resource footprint**: ~130 MB memory total across all 3 containers; image footprints ~1.5 GB.
- Prometheus is not exposed publicly (no auth). Only Grafana port 3001 should be opened to the internal network.
- **Upstream `cuebot.json` dashboard is obsolete** (dating from 2021; 9 metrics no longer exist in modern Cuebot), rendering panels largely blank. Build custom dashboards for Cuebot monitoring. For supported metrics, see [`notes/sandbox/24` Section 4](../sandbox/24-dispatch-and-monitoring.md#4-monitoring-infrastructure-prometheus--grafana).
- Cuebot queue metrics require setting `CUEBOT_METRICS_COLLECTOR=true` in the opencue stack (requires Pull and redeploy).

Reference: [`notes/sandbox/24`](../sandbox/24-dispatch-and-monitoring.md).

---

## 9. Long-term Operations Outside Docker

These administrative tasks require host privileges or external containerized cron orchestrations. Details are covered in [`04-operations.md`](04-operations.md):

| Task | Consequence if Neglected |
|---|---|
| PostgreSQL database backups (`pg_dump`) | Host failure wipes farm job state and history |
| Database history table pruning | DB disk space grows indefinitely (no built-in auto-purging) |
| Frame log retention pruning | Shared network storage disk space exhaustion |
| Registry garbage collection | Applicable only when operating self-hosted registries |
