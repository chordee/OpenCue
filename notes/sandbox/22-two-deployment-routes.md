# 22 — Two Deployment Routes: Portainer and docker compose

> **Empirical verification notes.** Production deployment procedures are documented in [`notes/deploy/01-server.md`](../deploy/01-server.md).
> Server configuration templates reside in [`notes/deploy/server/`](../deploy/server/).

The identical compose manifest [`notes/deploy/server/opencue.portainer.yml`](../deploy/server/opencue.portainer.yml) supports both deployment methods.
**Deployment engineers choose the appropriate route based on IT-granted privileges**, without modifying any YAML files.

---

## 1. Selecting a Deployment Route

| Granted Permissions | Recommended Route |
|---|---|
| Portainer web credentials only | **A. Portainer** |
| Host SSH with `docker` group membership | **B. docker compose** (Fastest) |
| Host SSH, but IT restricts building on shared servers | **A. Portainer** (Images compiled on development workstation) |

The core distinction between the two routes lies in **"Image Provenance"**:

```
A. Portainer         Dev machine build   ──push──> Registry ──pull──> Host Server
                                                  (Private or GHCR)

B. docker compose    Server git clone    ──build──> Local launch
                                                  (No registry required)
```

| Trait | A. Portainer | B. docker compose |
|---|---|---|
| Registry required | **Yes** (Private `registry.portainer.yml` or GHCR) | No |
| SSH / Docker permissions | No | **Yes** (Docker group equivalence to root) |
| Server-side image builds | No | **Yes** (Build cache consumes ~50 GB; CPU spikes during build) |
| Server external network access | Access to registry only | Must reach Maven / npm / PyPI during build |
| Portainer visual management | Full lifecycle governance | Displays "created outside of Portainer"; limited management |
| Site customizations (DNS, etc.) | Configured via environment variables or web editor | Composed via overlay `site.yml` |

---

## 2. Server Artifact Inventory

All assets reside in [`notes/deploy/server/`](../deploy/server/):

| File | Purpose | Route A | Route B |
|---|---|---|---|
| `opencue.portainer.yml` | **Primary manifest** shared by both routes | Yes | Yes |
| `env.example` | Environment variable template with annotations | Yes | Yes |
| `build.yml` | Overlay specifying build contexts and Dockerfiles | Dev machine | Yes |
| `site.example.yml` | Site-specific overlay (DNS, static extra_hosts) | Paste as needed | Overlay as needed |
| `init/` | Initialization container Dockerfile and bootstrap scripts | Yes | Yes |
| `registry.portainer.yml` | Self-hosted private registry template | Optional | — |

---

## 3. Route A: Portainer

### 1. Build and Push from Development Machine

```bash
cd notes/deploy/server
cp env.example .env          # Set OPENCUE_*_IMAGE to target registry endpoints

docker compose --env-file .env -f opencue.portainer.yml -f build.yml build
docker compose --env-file .env -f opencue.portainer.yml -f build.yml \
  push flyway cuebot rest-gateway cueweb init
```

**`push` must explicitly enumerate OpenCue service targets**, preventing accidental pushes of base database images like `postgres:15.1`.

Because `build.yml` adopts `OPENCUE_*_IMAGE` variable references directly, built images **immediately carry proper tags**, eliminating manual `docker tag` invocations.

### 2. Provision Stack via Portainer

- **Stacks → Add stack → Web editor**: Paste contents of `opencue.portainer.yml`.
- **Environment variables**: Input variables manually or upload using "Load variables from .env file".

Missing mandatory variables (marked with `:?` in YAML) immediately halt deployments with informative validation errors:

```
required variable OPENCUE_FLYWAY_IMAGE is missing a value: mandatory setting
```

All other variables supply safe production defaults.

### Empirical Results

Updated stack via Portainer API `PUT /api/stacks/3` supplying only initialization variables (`OPENCUE_INIT_IMAGE`, `OPENCUE_INIT_SHOWS`, `OPENCUE_INIT_SERVICES`):

```
opencue-db            Up (healthy)
opencue-flyway        Exited (0)
opencue-cuebot        Up (healthy)
opencue-rest-gateway  Up (healthy)
opencue-cueweb        Up (healthy)
opencue-init          Exited (0)      <- Successful bootstrap completion

Created show initb
  Created subscription local.general.initb (1000 cores)
  Created subscription local.desktop.initb (1000 cores)
  Created subscription cloud.general.initb (1000 cores)
Created service initsvc, tags=['general']
Initialization completed
```

Jobs submitted to `initb` requesting `initsvc` completed with `SUCCEEDED` on Windows nodes. Mandatory validations (`:?`), default substitutions (`:-`), and nested variables (`${A:-${B}}`) parsed cleanly in Portainer.

Git repository mode is documented in [`23-portainer-git-mode.md`](23-portainer-git-mode.md).

---

## 4. Route B: docker compose

On target server:

```bash
git clone https://github.com/chordee/OpenCue && cd OpenCue/notes/deploy/server
cp env.example .env          # Configure secrets and storage paths

docker compose --env-file .env -f opencue.portainer.yml -f build.yml up -d --build
```

Applying site-specific overrides:

```bash
cp site.example.yml site.yml   # Adjust internal DNS or static host entries
docker compose --env-file .env -f opencue.portainer.yml -f build.yml -f site.yml up -d --build
```

Updating stack:

```bash
git pull
docker compose --env-file .env -f opencue.portainer.yml -f build.yml up -d --build
```

### Relative Path Behavior

When combining multiple `-f` manifests, **relative paths evaluate relative to the working directory of the first specified file**.
`context: ../../..` in `build.yml` resolves to the repository root when commands execute inside `notes/deploy/server/`.

---

## 5. Initialization Container: `init`

### Purpose

Fresh databases contain only seed data (show `testing`). Production shows, subscriptions, and services previously required running manual Python scripts.

`init` operates as a one-shot container (like `flyway`), executing after Cuebot becomes healthy and exiting upon completion.

### Configuration

Controlled entirely via environment variables (no-op if unconfigured):

| Variable | Description | Default |
|---|---|---|
| `OPENCUE_INIT_SHOWS` | Comma-separated list of shows to create | Empty |
| `OPENCUE_INIT_ALLOCS` | Allocations subscribed by new shows | `local.general,local.desktop,cloud.general` |
| `OPENCUE_INIT_SUB_CORES` | Guaranteed core size and burst ceiling per subscription | `1000` |
| `OPENCUE_INIT_SERVICES` | Service definitions (JSON array) | Empty |

Format for `OPENCUE_INIT_SERVICES`:

```json
[
  {"name": "houdini2204", "tags": ["houdini_22_0_429"], "min_cores": 1, "min_memory_gb": 4},
  {"name": "maya2027",    "tags": ["maya_2027"],        "min_memory_gb": 8},
  {"name": "nuke17",      "tags": ["nuke_17_0v1"],      "min_memory_gb": 4}
]
```

Optional keys: `min_cores` (1), `max_cores` (0 = unlimited), `min_memory_gb` (4), `min_memory_increase_gb` (2), `threadable` (false). Refer to [`21-service-and-resource-model.md`](21-service-and-resource-model.md).

### Idempotency

Re-runs safely on stack updates without overwriting existing entities or discarding manual adjustments made via CueGUI:

```
== Initial Execution                   == Subsequent Update
Created show inita                       Show inita exists
  Created sub local.general.inita          Subscription local.general.inita exists
  Created sub cloud.general.inita          Subscription cloud.general.inita exists
Service houdini2204 exists               Service houdini2204 exists
Created service inittest                 Service inittest exists
```

Modifications to existing services should be performed through management GUIs.

### Critical Discovery: Unsubscribed Shows Never Dispatch Frames

Initial implementations subscribed only `local.general` and `cloud.general`. Tasks submitted to new shows hung indefinitely in **WAITING** with zero errors:

```
job:  facility=local, os=Windows, PENDING
layer: tags=general, 1 core, 1 GB
host: LAPTOP-ULJICLO8  tags include general, OS=Windows, 8 idle cores, OPEN
      ↑ All constraints satisfied
```

**Reason**: Windows workstations resided in `local.desktop`, which the new show did not subscribe to. Cuebot filters jobs starting from shows subscribed to the target allocation (`FIND_SHOWS` in `DispatchQuery.java`).

Subscribing `local.desktop` dispatched tasks within **10 seconds**.

Defaults now include all three core allocations. Custom allocations must be appended to `OPENCUE_INIT_ALLOCS`. See [`17` Scenario 22](17-troubleshooting.md#scenario-22-jobs-submitted-to-newly-created-show-stuck-in-waiting).

### Version Number Mocking in Container Build

The repository's `.dockerignore` excludes `ci/`, but packaging scripts in `proto` and `pycue` read version strings from `../ci/generate_version_number.py`. `init/Dockerfile` injects a stub returning clean PEP 440 version identifiers (defaulting to `0.0.0` or overridden via `OPENCUE_VERSION`).

---

## 6. Primary Manifest Architecture: Environment-Driven Configuration

### 1. Mandatory Variables and Defaults

| Category | Variables | Behavior |
|---|---|---|
| Mandatory (`:?`) | `POSTGRES_PASSWORD`, `JWT_SECRET`, `CUEWEB_NEXTAUTH_SECRET`, `CUE_FRAME_LOG_DIR`, five `OPENCUE_*_IMAGE` targets | Halts deployment immediately if unset; prevents weak default credentials |
| Defaulted | `POSTGRES_USER` / `POSTGRES_DB` = `cuebot`, ports = `8443` / `3000` | Applied transparently |
| Defaulted | `FRAME_LOG_ROOT_WINDOWS` / `_LINUX` | Falls back to `CUE_FRAME_LOG_DIR` |
| Defaulted | `CUEWEB_LOG_ROOTS` = `/mnt/logs` | Enforces restricted root directory reads (see [`13`](13-cueweb-and-rest-gateway.md)) |

### 2. Optional Volume Bind Mounts

When `FRAME_LOG_MOUNT_SOURCE` or `RENDER_OUT_MOUNT_SOURCE` are unconfigured, CueWeb mounts an empty fallback volume (`opencue-cueweb-empty`). CueWeb launches normally while disabling previews. Leaving mounts blank previously triggered syntax errors (`invalid spec: ::ro`).

### 3. Node Name Resolution: Moving DNS Configuration Out of Primary Manifest

Testing empty variable substitutions revealed unexpected Docker behavior:

```
# dns_search omitted entirely          # dns_search: ${DNS_SEARCH:-} (unconfigured)
nameserver 127.0.0.11                  nameserver 127.0.0.11
options ndots:0                        search                <- Empty search line clears domains
                                       options ndots:0
```

An unpopulated `dns_search` entry emits an empty search line in `/etc/resolv.conf`, **stripping search domains inherited from the host**.

Design decision:
- **Primary manifest omits DNS definitions entirely**, inheriting host `/etc/resolv.conf` search domains natively.
- If host inheritance fails, overlay `dns` and `dns_search` via `site.example.yml`.
- `extra_hosts` defaults safely to `opencue-placeholder: 127.0.0.1`.

---

## 7. Route B Empirical Benchmark

Tested using isolated project namespace and port offsets:

```bash
docker compose -p opencue-clitest --env-file cli.env \
  -f opencue.portainer.yml -f build.yml -f cli-test.yml up -d --build
```

Clean database, built completely from source:

```
opencue-clitest-db-1            Up (healthy)     postgres:15.1
opencue-clitest-flyway-1        Exited (0)       opencue-clitest/flyway:dev
opencue-clitest-cuebot-1        Up (healthy)     opencue-clitest/cuebot:dev
opencue-clitest-rest-gateway-1  Up (healthy)     opencue-clitest/rest-gateway:dev
opencue-clitest-cueweb-1        Up (healthy)     opencue-clitest/cueweb:dev
opencue-clitest-init-1          Exited (0)       opencue-clitest/init:dev

Created show clishow
  Created subscription local.general.clishow (1000 cores)
  Created subscription local.desktop.clishow (1000 cores)
  Created subscription cloud.general.clishow (1000 cores)
Created service clisvc, tags=['general']
Initialization complete

CueWeb http://localhost:13000 → HTTP 200
```

Build duration: Cuebot Gradle compilation required **610 seconds**; CueWeb `npm ci` took 150 seconds on a 16-thread development host. Shared servers will experience significant CPU spikes during builds.

---

## 8. Publishing Images to GitHub Container Registry (GHCR)

Using GitHub Container Registry (`ghcr.io`) removes the need for private registry infrastructure:
- **Public packages allow anonymous pulls without authentication.**
- AMD64 images compiled once execute across Intel and AMD hardware.
- Workflows triggered from public repositories publish packages with public visibility automatically.
- Images contain no secrets; credentials are provided exclusively via deployment environment variables.
- Anonymous CueWeb instances leave `NEXT_PUBLIC_AUTH_PROVIDER` unconfigured (allowing UI operations without authentication, isolated via internal networks or reverse proxies).

### GitHub Actions Workflow

In `.github/workflows/sandbox-images.yml`:
- Trigger: Manual dispatch (`workflow_dispatch`).
- Employs `build.yml` directly, mirroring local build outputs.
- Pushes to `ghcr.io/<owner>/opencue/{cuebot,flyway,rest-gateway,cueweb,init}` using commit tags (`1.34.4-<short-sha>`) and `latest`.

Workflow run (commit `1d73523b`) finished in **6.5 minutes**, producing public images verifiable without authentication.

### Portainer Configuration Using GHCR

```
OPENCUE_CUEBOT_IMAGE=ghcr.io/chordee/opencue/cuebot:1.34.4-1d73523b
OPENCUE_FLYWAY_IMAGE=ghcr.io/chordee/opencue/flyway:1.34.4-1d73523b
OPENCUE_REST_GATEWAY_IMAGE=ghcr.io/chordee/opencue/rest-gateway:1.34.4-1d73523b
OPENCUE_CUEWEB_IMAGE=ghcr.io/chordee/opencue/cueweb:1.34.4-1d73523b
OPENCUE_INIT_IMAGE=ghcr.io/chordee/opencue/init:1.34.4-1d73523b
```

Initial pull of all five images (~6 GB combined) required ~34 minutes over standard internet connections. Container recreation took ~30 seconds, during which existing containers served traffic until downloads finished. Pre-pulling images prior to scheduled maintenance windows is recommended.
