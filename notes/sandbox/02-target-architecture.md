# 02 — Target Architecture (Derived from Studio IT Specifications)

## Confirmed Studio Constraints

1. The target deployment platform is a **single Linux host running Docker**.
2. That host **co-locates numerous other studio services**; container isolation is mandatory -> OpenCue is merely one tenant.
3. The Docker host **does not participate in rendering**.
4. Compute nodes executing frames are **predominantly Windows machines**.
5. Administrative access: SSH is anticipated, but **operations must be fully viable via Portainer alone** if host SSH is restricted by IT policy.

## Derived Target Architecture

```
┌─────────────────────────────────────────┐
│ Linux Host (Docker, Multi-tenant)       │
│                                          │
│  OpenCue Stack                           │
│   ├── postgres      (Internal only)      │
│   ├── flyway        (Runs once & exits)  │
│   ├── cuebot        (Ingress 8443/gRPC)  │
│   ├── rest-gateway  (Optional)           │
│   └── cueweb        (Optional, Port 3000)│
│                                          │
│  Other Studio Stacks...                  │
└──────────────┬───────────────────────────┘
               │ gRPC 8443
     ┌─────────┴─────────┬─────────────┐
     │                   │             │
┌────▼─────┐      ┌──────▼────┐  ┌─────▼────┐
│ Windows  │      │ Windows   │  │ Windows  │
│ RQD 8444 │      │ RQD 8444  │  │ RQD 8444 │
│ (+NIMBY) │      │ (+NIMBY)  │  │ (+NIMBY) │
└──────────┘      └───────────┘  └──────────┘
```

**Crucial Architectural Distinction: `rqd` is omitted from the Docker stack.** Upstream compose files note that in production, RQD should run on dedicated render hosts. Because our Docker host does not render, RQD is excluded from the server stack entirely.

This "Cuebot in Docker, RQD on native worker hosts" hybrid architecture is documented upstream in `sandbox/Running_Hybrid_RQD_setup_using_sandbox.md` (corresponding to `docs/_docs/developer-guide/hybrid-rqd-setup.md`).

---

## OpenCue Component Roles & Service Quick Reference

The OpenCue ecosystem comprises 4 tiers: Client Tooling, Core Scheduling, Render Nodes, and Monitoring:

| Component | Execution Environment | Responsibility & Division of Scope | Port / Protocol |
|---|---|---|---|
| **pyoutline** | Client (Python) | Job definition framework. Structures jobs into layers, frame ranges, dependencies, and execution commands; generates serialized Session definitions. | Local Python API |
| **CueSubmit** | Artist Workstations | Desktop submission GUI (or in-DCC shelf tool). Lets artists select scenes, define frame ranges, assign Layer Tags, and queue jobs to Cuebot. | 8443 / gRPC |
| **CueAdmin** | Admin Terminals | CLI administration tool. Manages shows, allocations, subscriptions, and host statuses; moves nodes, forces unlocks, and kills jobs. | 8443 / gRPC |
| **CueGUI** | Artist / TD Desktops | Comprehensive desktop monitoring client (Cuetopia monitors jobs/frames; CueCommander monitors host allocation loads). | 8443 / gRPC |
| **CueNIMBY** | Artist Workstations | System tray daemon. Locks workstations based on **time schedules** (e.g. work hours) or **manual artist toggles**, notifying Cuebot to halt new dispatches. **Does not monitor keyboard/mouse input**—input activity detection is the responsibility of RQD's internal NIMBY daemon (`rqd/rqd/rqnimby.py`, via `pynput`); the two are independent (see [`09-nimby-and-hybrid-fleet.md`](09-nimby-and-hybrid-fleet.md)). | 8443 / gRPC |
| **Cuebot** | Server Container | **Stateless scheduling brain**. Manages job state machines, computes priorities and core quotas, and dispatches frames to matching RQD nodes. | 8443 (Ingress) / gRPC |
| **PostgreSQL** | Server Container | **Single source of truth (Stateful)**. Persists all jobs, frames, layers, hosts, tags, allocations, and historical analytics. | 5432 (Internal) / TCP |
| **Flyway** | Server Container | **One-shot schema migration tool**. Applies DDL scripts to create or upgrade schemas on startup; terminates immediately upon success. | 5432 (Internal) / TCP |
| **RQD** | Render Nodes (Win/Linux) | **Host execution daemon**. Registers hardware specs and tags with Cuebot, listens for dispatch commands, spawns render processes, and captures logs. | 8444 (Ingress) / gRPC |
| **REST Gateway** | Server Container | **gRPC to HTTP/JSON bridge**. Translates Cuebot's gRPC endpoints into REST APIs and validates incoming JWT tokens for CueWeb. | 8448 (Internal) / HTTP |
| **CueWeb** | Server Container | **Web management portal (Next.js)**. Browser-based dashboard for monitoring jobs, downloading logs, inspecting frame states, and lightweight administration. | 3000 (External) / HTTP |

---

## End-to-End Frame Lifecycle

The 7 sequential stages of an asset frame from artist dispatch to rendered output:

```
[Artist / DCC]
      │ 1. Submit (CueSubmit / pyoutline)
      ▼
   [Cuebot] ── 2. Persist state ──> [PostgreSQL] (State: PENDING / WAITING)
      │
      │ 3. Dispatching (Matches Tag, Allocation, Memory)
      ▼ (Inbound connection to node 8444)
 [Windows RQD] (State: RUNNING)
      │
      ├─ 4. Launch DCC process (ocrun -> hython / Render / Nuke)
      ├─ 5. Stream frame log (Writes to CUE_FRAME_LOG_DIR //fileserver/.../xxx.rqlog)
      ├─ 6. Output image file (Writes to project share H:\... or UNC)
      │
      ▼ 7. Report completion (ReportStatus: Exit code 0=SUCCEEDED, non-zero=DEAD)
   [Cuebot] ── Update state ──> [PostgreSQL]
      │
      ▼ 8. UI refresh (CueGUI turns green / CueWeb displays log and preview)
```

1. **Job Assembly & Submission**:
   - The artist selects frame ranges (e.g. 1-100) and tags (e.g. `general`, `houdini22`) in Maya / Houdini or standalone `cuesubmit`.
   - `pyoutline` serializes the job structure and transmits it to **Cuebot** via gRPC (port 8443).
2. **Registration & Queuing**:
   - Cuebot registers the job and layers in **PostgreSQL**; frames are expanded as individual entities initialized in `WAITING`.
3. **Dispatch Matching**:
   - Cuebot's internal Dispatcher continuously matches waiting frames with eligible hosts.
   - Evaluates three criteria: **Host is Unlocked**, **Memory/Core quotas are satisfied**, and **Host tags satisfy layer tag requirements**.
   - Upon matching, Cuebot issues an inbound `RunFrame` gRPC call to RQD on the target Windows node (port 8444).
4. **Execution on Node**:
   - RQD spawns task environment variables (`CUE_IFRAME`, `TEMP`, etc.).
   - Invokes `ocrun houdini 22.0.429 hython ...`, which resolves the target DCC binary from local `dcc.toml` and launches rendering ([`26-ocrun-wrapper.md`](26-ocrun-wrapper.md)).
5. **Logging & Profiling**:
   - RQD streams stdout/stderr directly into a `.rqlog` file at the specified UNC path.
   - Background threads query `winps` to sample process tree memory usage (RSS).
6. **Completion Reporting**:
   - The DCC process exits, returning an exit code.
   - RQD transmits execution results to Cuebot: Exit 0 marks the frame `SUCCEEDED`; non-zero marks it `DEAD`.
     (Note: OpenCue frames fail as `DEAD`, **never `FAILED`**; keep this in mind when querying PostgreSQL).
7. **Visualization**:
   - Cuebot persists status updates to the database; **CueGUI** updates to green.
   - If accessed via **CueWeb**, the Next.js server queries REST Gateway and reads `.rqlog` files from read-only mounts for web display.

---

## Critical Implementation Notes

### 1. RQD Port is Global Across the Entire Fleet

Upstream documentation highlights:

> **CueBot connects to ALL RQD instances using a single configured port (default: 8444).**

All worker nodes must listen on the **identical port**. Because our server stack excludes Docker RQD, local port 8444 conflicts are avoided.

### 2. Windows RQD Configuration Nuances

Reference settings from `sandbox/rqd_windows.conf`:

| Setting | Value | Rationale |
|---|---|---|
| `RQD_BECOME_JOB_USER` | `False` | Disables POSIX user switching on Windows |
| `RQD_USE_PATH_ENV_VAR` | `1` | Inherits `PATH` to locate render binaries |
| `OVERRIDE_IS_DESKTOP` | `True` | Identifies machine as workstation rather than dedicated render node |
| `OVERRIDE_NIMBY` | `True` | Yields compute resources when artists are active |
| `MINIMUM_IDLE` | `900` | Requires 15 minutes of idle time before picking up frames |
| `RQD_TMPDIR` | `C:\tmp\rqd` | Windows local scratch path |

**NIMBY is vital for desktop workstations borrowed after hours**, causing RQD to yield automatically when artists are active. `cuenimby` provides a system tray interface for artist control.

### 3. Path Alignment Strategy

Handling cross-platform paths divides into two distinct tiers:

- **Cuebot does not parse file paths**; it merely forwards command strings to RQD. Cuebot on Linux communicating with RQD on Windows introduces zero inherent path conflicts.
- Alignment is required between the **submitting workstation** and the **executing render node**. If artists submit from Windows and render on Windows, paths match natively (drive letters are synchronized studio-wide; only frame logs require UNC paths; see [`11-production-risks-and-todos.md` Section 2](11-production-risks-and-todos.md#2-network-drive-letters-are-supported-with-one-exception)).

### 4. Frame Log Directory

The upstream compose file specifies `CUE_FRAME_LOG_DIR=/tmp/rqd/logs` (Linux path). However, log writing is handled by **Windows RQD daemons**, which cannot write to Linux local paths.
Resolved empirically: paths must use forward-slash UNC syntax (`//fileserver/opencue/logs`); see [`08-windows-node-log.md`](08-windows-node-log.md).

### 5. Multi-tenant Host Isolation Requirements

Because the Docker host co-locates external services:

| Domain | Isolation Practice |
|---|---|
| Stack Project Name | Pin fixed compose project name (e.g. `opencue`) to prevent container name clashes |
| PostgreSQL Port 5432 | **Do not publish port 5432 to host**; host may already run another PostgreSQL instance; keep OpenCue DB internal |
| Cuebot Port 8443 | Must publish port 8443 for worker nodes and client tools |
| RQD Port 8444 | Omit from stack entirely |
| CueWeb Port 3000 | Expose behind an authenticated reverse proxy |
| Docker Networks | Create dedicated bridge network (`opencue`); do not use Docker default bridge |
| Resource Limits | Enforce CPU/Memory limits to protect neighboring services |
| Restart Policy | `restart: unless-stopped` to support unattended host reboots |

## Two Deployment Approaches

### A. Host SSH Access (Ideal)

Clone repository and execute `docker compose up -d`, matching our sandbox validation workflow. Images can be compiled locally or pulled from registries.

### B. Portainer-only Access (Fallback)

Constraints and adaptations:

| Constraint | Solution |
|---|---|
| In-situ `build:` is awkward | Pre-build images via CI/CD and publish to registry; compose references `image:` only |
| Flyway image requires embedded migration SQL | Pre-bake migration files into Flyway image and publish to registry |
| `${HOME}` shell variables fail | Replace with explicit environment variables in Portainer stack settings |
| Host filesystem file placement is constrained | Replace bind mounts with named volumes |

Tested and validated on Portainer CE (`portainer-ce:lts`, port 9443).
