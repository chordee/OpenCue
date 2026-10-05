# 19 — Comprehensive Verification Status Matrix

Sections titled "Unverified" across earlier sandbox notes reflected testing status at the time of writing. Many have since been validated. This document serves as the **authoritative reference status matrix**.

Status Legend:
- Verified: Empirically tested and confirmed working.
- Partially Verified: Core mechanism validated, but specific edge conditions remain untested.
- Unverified: Not yet tested, but testable locally.
- Not Testable Locally: Requires production network, permissions, or software licenses.

---

## 1. Verified Capabilities

| Item | Reference |
|---|---|
| Portainer stack creation, updates, and environment variable configuration | [`07`](07-portainer-deployment-log.md) |
| Registry pipeline: build → push → Portainer pull (verified via local tag deletion) | [`14`](14-registry-workflow.md) |
| Cuebot ↔ Windows native RQD bidirectional gRPC communication (including port 8444 callback) | [`08`](08-windows-node-log.md) |
| Real DCC rendering: Houdini (Karma), Maya (Software), Nuke | [`12`](12-real-dcc-rendering.md) |
| Standalone Houdini husk and OpenGL ROP rendering | [`12`](12-real-dcc-rendering.md) |
| Multi-node coexistence and tag-based job routing | [`12`](12-real-dcc-rendering.md) |
| **Tag matching evaluates regex OR** — Overturned initial assumption | [`12`](12-real-dcc-rendering.md) |
| **Facility mismatch silently halts job dispatching** | [`12`](12-real-dcc-rendering.md) |
| Heterogeneous multi-OS fleet (Windows + Linux nodes concurrent) | [`12`](12-real-dcc-rendering.md) |
| Per-OS frame log root mapping (`log.frame-log-root.<OS>`) | [`12`](12-real-dcc-rendering.md) |
| CueNIMBY scheduled host locking and unlocking | [`09`](09-nimby-and-hybrid-fleet.md) |
| **CueNIMBY cross-midnight schedules fail completely** | [`09`](09-nimby-and-hybrid-fleet.md) |
| CueWeb + REST Gateway + JWT authentication (401 without token, valid response with token) | [`13`](13-cueweb-and-rest-gateway.md) |
| CueWeb log and preview allowlist configurations | [`13`](13-cueweb-and-rest-gateway.md) |
| CueGUI desktop connection, job lists, and LogView displaying Windows log paths | Visual verification |
| Frame access to network shares (both mapped drive letters and UNC in user session) | [`11`](11-production-risks-and-todos.md) |
| winps memory profiling and 10-second sampling window behavior | [`08`](08-windows-node-log.md) |
| Resource usage benchmarks (~600 MB RAM / 0.6 cores baseline) | [`06`](06-resource-usage.md) |
| Storage footprint benchmarks (Docker build cache at 50 GB) | [`15`](15-storage-planning.md) |
| **Job dependencies**: chain, diamond, and fan-in topologies | [`20`](20-dependencies-and-operations.md) |
| **Two-stage Houdini rendering** (hython generates USD → husk renders EXR with LayerOnLayer dependency) | [`20`](20-dependencies-and-operations.md) |
| **CueWeb submission interface** (including documented limitations) | [`13`](13-cueweb-and-rest-gateway.md) |
| CueWeb UI dashboard metrics matching database state | Visual verification |
| Operator management: pause / resume / retry / term / lock / move | [`20`](20-dependencies-and-operations.md) |
| **Memory over-subscription behavior** (`oom_frame_overboard_allowed_threshold=-1.0`) | [`13`](13-cueweb-and-rest-gateway.md) |
| **Custom Services inheriting tags and memory** (submissions declare service name only) | [`21`](21-service-and-resource-model.md) |
| Conceptual clarity across Layer, Username, Facility, Service, and Dependencies | [`21`](21-service-and-resource-model.md) |
| **Stack upgrades and rollbacks** (verified via distinct image versions) | [`14`](14-registry-workflow.md) |
| **In-flight frame survival during Cuebot upgrades** | [`14`](14-registry-workflow.md) |
| **Unified stack deployment via environment variables** (mandatory `:?` checks, optional defaults) | [`22`](22-two-deployment-routes.md) |
| **docker compose route**: clean DB, source builds, all six containers healthy | [`22`](22-two-deployment-routes.md) |
| **GHCR automated build workflow**: successfully pushed five images; anonymous pull supported | [`22`](22-two-deployment-routes.md) |
| **`rqd.conf` with Chinese characters crashes on cp950 systems** | [`05` Issue #18](05-upstream-issues.md#18-python-rqd-reads-rqdconf-without-specifying-encoding), [`17` Scenario 23](17-troubleshooting.md#scenario-23-rqd-crashes-immediately-on-launch-with-unicodedecodeerror) |
| **Portainer Git mode**: deploy from GitHub, preserve DB volume, polling/webhook updates | [`23`](23-portainer-git-mode.md) |
| **Doc-only commits trigger zero-downtime redeploys** (re-runs flyway and init only) | [`23`](23-portainer-git-mode.md) |
| **`rqd.conf` template operational on Windows RQD**; `DEFAULT_FACILITY` functional | [`17` Scenario 20](17-troubleshooting.md#scenario-20-newly-joined-node-never-receives-work) |
| **Node allocation determined by first tag** (`desktop` prefix enters `local.desktop`) | [`17` Scenario 20](17-troubleshooting.md#scenario-20-newly-joined-node-never-receives-work) |
| **Database backup and restore** (`--clean --if-exists` across blank and existing DBs) | [`11` Section 6](11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups) |
| **Workstations and dedicated nodes online concurrently**: both receive dispatches | [`24`](24-dispatch-and-monitoring.md) |
| **Host locking does not interrupt running frames**; killed frames requeue cleanly | [`24`](24-dispatch-and-monitoring.md) |
| **500 frame stress test**: 100% success rate, 0 DEAD | [`24`](24-dispatch-and-monitoring.md) |
| **Git mode manifest updates recreate targeted service only** | [`24`](24-dispatch-and-monitoring.md) |
| **Monitoring stack** (Prometheus + Grafana with inline configurations in Portainer) | [`24`](24-dispatch-and-monitoring.md) |
| **Path spaces fail without quotes**: pyoutline joins arguments without escaping | [`17` Scenario 24](17-troubleshooting.md#scenario-24-frame-fails-when-path-contains-spaces) |
| **Two-stage Maya submitter**: automatic version and service matching; 10 frames successful | [`25`](25-maya-submission.md) |
| **Autodesk CER crash window resolved**: `ALLUSERSPROFILE` added to `[UseHostEnvVar]` in `rqd.conf` | [`28`](28-maya-crash-reporting.md), [`17` Scenario 25](17-troubleshooting.md#scenario-25-autodesk-crash-error-report-window-pops-up-on-render-node) |
| **`ocrun` replaces DCC batch wrappers**: Houdini, Maya, and Nuke renders operational | [`26`](26-ocrun-wrapper.md) |
| **Killing frames terminates entire process tree** (`ocrun` and child DCC processes) | [`26`](26-ocrun-wrapper.md) |
| **`job.kill()` requires reason argument**; silent rejection without reason | [`17` Scenario 26](17-troubleshooting.md#scenario-26-killing-job-via-api-silently-fails-while-job-keeps-running) |
| **Two-stage Houdini submitter**: File Cache (sim/cache), ROP Geometry, Karma LOP | [`27`](27-houdini-submission.md) |
| **RQD hardcodes `TZ=PST8PDT`**: resolved via `[UseHostEnvVar]` TZ pass-through | [`29`](29-frame-timezone.md) |
| **Houdini submitter filters nodes by RopNode + allowlist** | [`27`](27-houdini-submission.md) |
| **Submission UI regression test suite** (`lab/check_submit_tools.py`): 15 tests pass | [`04` Section 9](../deploy/04-operations.md#9-post-upstream-regression-testing) |
| **Arnold license validation on farm**: `solidangle_LICENSE` required in `dcc.toml` | [`30`](30-arnold-licensing.md) |
| **`ocrun` detects Arnold license aborts and forces exit code 1** | [`30`](30-arnold-licensing.md) |
| **Two-stage Nuke submitter**: `-F #FRAMESPEC#` chunking and multi-Write node execution | [`31`](31-nuke-submission.md) |
| **Node tag length widened**: database column widened to 4000 characters via migration | [`32`](32-node-tag-limit.md) |
| **Full clean rebuild from documentation**: stack deployment, client configs, 3 DCC renders | [`33`](33-rebuild-from-scratch.md) |
| **init container**: provisions shows, subscriptions, services idempotently | [`22`](22-two-deployment-routes.md) |
| Empty `dns_search` strips inherited search domains (removed from primary stack) | [`22`](22-two-deployment-routes.md) |

---

## 2. Partially Verified Capabilities

| Item | Verified Aspects | Untested Boundary Conditions |
|---|---|---|
| **Multi-Node Dispatching** | Scheduling logic (tags, facilities, OS filtering) | Secondary node was a Linux container, not physical Windows over LAN |
| **`ocrun` Wrapper Architecture** | Path resolution on single host; container unit tests | Untested on a secondary physical machine with different install paths |
| **Network Drive Access** | Writable in interactive user sessions | Untested in Session 0 Windows Service execution |
| **CueNIMBY** | Schedule locking and unlocking logic | System tray visual appearance and manual interactive toggles |
| **Memory Telemetry** | winps operational and metrics accurate | Quantitative accuracy under production scale short-frame workloads |

---

## 3. Unverified (Locally Testable)

| Item | Notes |
|---|---|
| **Standalone Desktop CueSubmit** | CueWeb submission verified; standalone Qt application launch untested |
| **RQD Built-in NIMBY Input Detection** | Real-time keyboard/mouse termination under `OVERRIDE_NIMBY = True` |
| **Maya Submitter** | Tested on Maya 2027; older releases untested |
| **Nuke Submitter** | Tested on Nuke 17.0v1; older releases untested |
| **Houdini Submitter** | Tested on core nodes; Redshift and complex DOP simulations untested |
| **Loki Logging Backend** | Evaluated and declined ([`24` Section 5](24-dispatch-and-monitoring.md#5-loki-log-backend-evaluated-only-not-tested)) |

---

## 4. Not Testable Locally (Requires Production Environment or Licenses)

| Item | Prerequisite |
|---|---|
| **Physical Multi-Machine LAN Routing** | Secondary physical Windows host, physical LAN, studio DNS |
| **Inbound Port 8444 Firewall Filtering** | Physical machines traversing network firewalls |
| **Drive Letter Uniformity Across Hosts** | Secondary physical host |
| **Windows Service Execution (Session 0)** | Administrator privileges |
| **Auto-Start on Boot (Scheduled Tasks)** | Administrator privileges / Group Policy distribution |
| **End-to-End Enterprise Storage** | Studio file server (validated local SMB via UNC in [`33`](33-rebuild-from-scratch.md#cueweb-frame-log-retrieval)) |
| **Registry TLS & Authentication** | Enterprise TLS certificates |
| **Scheduled Host Cron Maintenance** | Host root access or containerized cron deployment |
| **Off-Host Backup Replication** | External backup destination |
| **High-Volume Cuebot Scaling** | Fleets of dozens of render nodes |
| **Long-Term Operational Stability** | Multi-week runs (database growth, log rotation, memory leaks) |
| **Arnold Commercial Floating Tokens** | Floating license server |
| **Blender Rendering** | Clean Blender executable installation |
