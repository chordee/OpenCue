# 03 — Compose Stack Container Breakdown

Based on `docker-compose.yml` at the repository root. Defines 16 services organized into profiles; only 4 start by default.

## Profile Groupings

| Profile | Included Services | Launch Command |
|---|---|---|
| (Default) | `db`, `flyway`, `cuebot`, `rqd` | `docker compose up -d` |
| `cueweb` | `rest-gateway`, `cueweb` | `docker compose --profile cueweb up -d` |
| `monitoring` | `db-exporter`, `prometheus`, `grafana`, `loki` | `--profile monitoring` |
| `monitoring-full` | `zookeeper`, `kafka`, `kafka-ui`, `elasticsearch`, `kibana`, `monitoring-indexer` | `--profile monitoring-full` |
| `all` | All services | `--profile all` |

---

## The Four Core Services (Default Profile)

### `db` — PostgreSQL Database

| Item | Value |
|---|---|
| Image | `postgres:15.1` (Official image, no build required) |
| Port | `5432:5432` |
| Volume | `db-data` (Named volume) |
| Credentials | `cuebot` / `cuebot_password` (Hardcoded in compose) |

**Role**: Single source of truth for OpenCue. Shows, jobs, layers, frames, hosts, allocations, subscriptions, and filters persist here. Cuebot itself is completely stateless; restarting Cuebot loses zero data, whereas database loss is irrecoverable.

**Production Considerations**:
- Do not publish port 5432 (avoids port collisions with host-level PostgreSQL instances and removes unnecessary public exposure).
- Move credentials to `.env` or Docker secrets (note passwords appear twice in upstream compose: under `db` environment, and within cuebot's `command:` parameter).
- Include `db-data` volume in automated backup cycles.

### `flyway` — Database Schema Migration

| Item | Value |
|---|---|
| Build | `sandbox/flyway.Dockerfile` (Base `almalinux:9` + Flyway 9.11.0) |
| Port | None |
| Lifecycle | **One-shot; exits immediately upon completion** |

**Role**: Applies SQL DDL scripts sequentially from `cuebot/src/main/resources/conf/ddl/postgres/migrations`, followed by `seed_data.sql`. `cuebot` declares `depends_on` with `condition: service_completed_successfully`, meaning **Cuebot starts only after Flyway completes successfully**.

Seeing the `flyway` container in status `Exited (0)` is **completely normal behavior**.

**Production Considerations**:
- Migration SQL files are **baked into the container image** via `COPY`. Upgrading OpenCue versions requires rebuilding this image.
- In Portainer-only environments, this image must be pre-built and pushed to a registry.

### `cuebot` — Scheduler (Farm Brain)

| Item | Value |
|---|---|
| Build | `cuebot/Dockerfile` (Gradle builds Java / Spring Boot application) |
| Image | `opencue/cuebot` (Commented out in upstream compose) |
| Port | `8443:8443` (gRPC), `8080` metrics endpoint commented by default |
| Environment | `CUE_FRAME_LOG_DIR=/tmp/rqd/logs` |
| `depends_on` | `db` healthy + `flyway` successfully completed |

**Role**:
- Serves gRPC requests from clients (`cueadmin`, `cuesubmit`, `pyoutline`, REST Gateway).
- Manages job and frame state machines.
- Evaluates dispatch matching: "which waiting frame assigns to which available RQD host".
- Receives frame completion, failure, and resource profiling reports from RQD.

**This is the single critical service for the farm**. If Cuebot stops, all RQD nodes idle and client UIs disconnect.

**Production Considerations**:
- Reference registry `image:` with deterministic tags (never `latest`).
- Port `8443` must be published externally for Windows render node communication.
- Configure `CUE_FRAME_LOG_DIR` with forward-slash UNC syntax; see [`02-target-architecture.md`](02-target-architecture.md).
- Publish port `8080` internally for Prometheus scraping (requires adding `--metrics.prometheus.collector=true` to CLI flags).

### `rqd` — Render Queue Daemon

| Item | Value |
|---|---|
| Build | `rust/Dockerfile.rqd` (**Rust implementation of RQD**, not Python) |
| Port | `8444:8444` |
| Environment | `OPENRQD__GRPC__CUEBOT_ENDPOINTS=cuebot:8443`, `OPENRQD__MACHINE__USE_IP_AS_HOSTNAME=true` |
| Volume | `/tmp/rqd/logs`, `/tmp/rqd/shots`, `${HOME}/.opencue/sessions`, `/tmp/opencue`, `/var/folders` (ro) |

**Role**: Simulates a worker render node. Registers hardware specs (cores, RAM) with Cuebot on boot, receives dispatched frames, runs commands, streams stdout/stderr to `.rqlog`, and reports results.

**This container contains zero DCC applications**—no Blender, Maya, or Nuke. Sandbox demo jobs execute dummy tasks like `/bin/sleep N` to validate scheduling state transitions.

**Production Decision: Remove this service from the stack entirely.**
Upstream compose comments note: "In a production environment, this should be disabled from the stack and only run on render hosts". Our server host does not render; external Windows machines run native Python RQD daemons.

---

## CueWeb Profile (Web Interface)

### `rest-gateway` — gRPC to HTTP Bridge

| Item | Value |
|---|---|
| Image | `opencue/rest-gateway:latest` |
| Port | `8448:8448` |
| Environment | `CUEBOT_ENDPOINT=cuebot:8443`, `JWT_SECRET=${JWT_SECRET:-opencue-dev-jwt-secret-change-in-production}` |

**Role**: Bridges Cuebot's gRPC protocol into HTTP/JSON for browser consumption by CueWeb. Implements JWT authentication.

**Production Considerations**: Replace the default dev `JWT_SECRET`.

### `cueweb` — Web UI

| Item | Value |
|---|---|
| Image | `opencue/cueweb:latest` |
| Port | `3000:3000` |
| Framework | Next.js |

**Role**: Browser-based job monitoring and management dashboard, mirroring core CueGUI features.

**Production Pitfall**: Next.js client-side `NEXT_PUBLIC_*` variables are **baked into JS bundles at build time**. If an image is built with `http://localhost:8448`, client browsers on other subnets encounter `ECONNREFUSED`. Rebuild images with target production endpoints as build arguments.

---

## Monitoring Profile (Metrics & Logging)

| Service | Image | Port | Role |
|---|---|---|---|
| `db-exporter` | `prometheuscommunity/postgres-exporter` | 9187 | Exports PostgreSQL metrics to Prometheus |
| `prometheus` | `prom/prometheus:v3.9.1` | 9090 | Metrics scraping and storage |
| `grafana` | `grafana/grafana:12.3.5` | 3001->3000 | Web dashboards (default admin/admin) |
| `loki` | `grafana/loki:3.6.0` | 3100 | Log aggregation. Requires uncommenting `logging: driver: loki` across services |

Optional stack. Recommended to defer until core farm dispatching is verified.

---

## Monitoring-Full Profile (Event Streaming)

| Service | Image | Port | Role |
|---|---|---|---|
| `zookeeper` | `cp-zookeeper:7.7.7` | 2181 | Kafka coordination |
| `kafka` | `cp-kafka:7.7.7` | 9092 / 29092 | Event streaming message bus |
| `kafka-ui` | `provectuslabs/kafka-ui` | 8090->8080 | Web UI for Kafka |
| `elasticsearch` | `elasticsearch:9.3.0` | 9200 / 9300 | Long-term event storage and search |
| `kibana` | `kibana:9.3.0` | 5601 | Elasticsearch query dashboard |
| `monitoring-indexer` | Built from `rust/Dockerfile.monitoring-indexer` | None | Indexes Kafka events into Elasticsearch |

**Note**: Cuebot **does not emit Kafka events by default**. To activate, append `--monitoring.kafka.enabled=true` to Cuebot's CLI command.
This stack is resource-heavy (Elasticsearch is RAM-intensive); exercise caution on shared multi-tenant hosts.

---

## Persistent Volumes

| Volume | Purpose |
|---|---|
| `db-data` | PostgreSQL records — **The single critical stateful store** |
| `prometheus-data` | Historical metrics |
| `grafana-data` | Dashboard configurations |
| `elasticsearch-data` | Historical event index |

---

## Recommended Production Minimum Composition

Under the assumption "Linux host does not render, Windows hosts act as render nodes, Docker host co-locates other services":

```
Mandatory: db, flyway, cuebot
Recommended: rest-gateway, cueweb (If web monitoring is desired)
Omit: rqd (Docker host does not render)
Evaluate Later: monitoring stack (High resource footprint)
```

---

## Operational Guide: When and Why to Access Containers (`docker exec`)

Operators frequently face uncertainty regarding when it is appropriate to execute commands inside containers:

### 1. The Cardinal Rule: When NEVER to Mutate In-Container State

> **Containers are disposable and stateless. Direct changes made inside running containers are wiped upon restart or image updates.**

- **Never enter containers to edit configuration files**: Do not edit Spring properties inside `opencue-cuebot` or Next.js files in `opencue-cueweb`.
  - **Consequence**: Portainer redeployments or container restarts immediately overwrite modifications.
  - **Correct Practice**: Manage parameters via [`notes/deploy/server/env.example`](../deploy/server/env.example) (Portainer environment variables) or edit compose definitions.
- **Never compile or install dependencies inside containers**: Do not run Gradle inside `opencue-cuebot` or `npm install` inside `opencue-cueweb`.
  - **Correct Practice**: Build containers via standalone build pipelines and push to registries ([`14-registry-workflow.md`](14-registry-workflow.md)).

---

### 2. When to Use `docker exec` (Diagnostics & Ad-hoc Administration)

Use `docker exec` strictly for **inspecting state, extracting diagnostics, or running one-off administrative maintenance**:

#### Scenario A: Diagnosing DNS Short-Name Resolution (Inside `cuebot`)
When frames hang in `RUNNING` with zero logs, verify that Cuebot can resolve the Windows node hostname:
```bash
# 1. Test short hostname resolution inside Cuebot
docker exec opencue-cuebot getent hosts <NodeShortName>

# 2. Test TCP reachability to RQD gRPC port 8444
docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/<NodeShortName>/8444" && echo REACHABLE || echo BLOCKED'
```

#### Scenario B: Diagnosing Mount Point Visibility (Inside `cueweb`)
When web log viewers or thumbnail previews fail, verify that shared storage is visible:
```bash
# Confirm shared folders contain files rather than empty mount points
docker exec opencue-cueweb ls -la /mnt/logs
docker exec opencue-cueweb ls -la /mnt/render
```

#### Scenario C: Low-level PostgreSQL Diagnostics & Ad-hoc Backups (Inside `db`)
When debugging allocation tag mismatches or taking manual snapshots:
```bash
# 1. Query tags assigned to a specific host
docker exec -it opencue-db psql -U cuebot -c "
SELECT h.str_name, ht.str_tag, ht.str_tag_type 
FROM host h JOIN host_tag ht ON h.pk_host=ht.pk_host 
WHERE h.str_name='<NodeName>';"

# 2. Query tags requested by waiting layers (Requires JOIN on job table)
docker exec -it opencue-db psql -U cuebot -c "
SELECT l.str_name, l.str_tags
FROM layer l JOIN job j ON l.pk_job = j.pk_job
WHERE j.str_state = 'PENDING';"

# 3. Take an ad-hoc database dump
docker exec opencue-db pg_dump -U cuebot -d cuebot -Fc -f /tmp/backup.dump
docker cp opencue-db:/tmp/backup.dump ./cuebot-manual.dump
```

#### Scenario D: Investigating Healthcheck Failures
When a container is flagged `unhealthy`, run probe commands directly to inspect exit codes:
```bash
# Manually invoke Cuebot health probe
docker exec opencue-cuebot curl -sf http://localhost:8080/
echo "Exit Code: $?"  # Exit 22 indicates endpoint inactive but Spring healthy; other codes indicate failure
```

---

### 3. Container Diagnostic Cheat Sheet

| Container Name | Diagnostic Command | Expected Output / Purpose |
|---|---|---|
| `opencue-db` | `docker exec opencue-db pg_isready -U cuebot` | `accepting connections` (DB is healthy) |
| `opencue-flyway` | `docker logs opencue-flyway` | Confirm final log reads `Successfully applied X migrations` |
| `opencue-cuebot` | `docker logs --tail 100 opencue-cuebot \| grep WARN` | Check for `RqdClientException` or host connection warnings |
| `opencue-rest-gateway` | `docker logs opencue-rest-gateway` | Inspect JWT validation failures or timeout errors |
| `opencue-cueweb` | `docker logs opencue-cueweb` | Check Next.js server-side errors fetching jobs or logs |
