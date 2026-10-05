# 18 — Three Role Preparation Checklists

> **Superseded by [`notes/deploy/`](../deploy/README.md)**. Refer to that directory for definitive deployment guides.
> This document is retained for historical implementation context.

Earlier notes were organized chronologically by testing milestones, scattering host requirements across multiple documents. This guide consolidates configuration prerequisites categorized by **machine roles** to serve as a deployment checklist.

## Host Role Clarification

| Role | OS | Description |
|---|---|---|
| **OpenCue Server** | Linux + Docker | Runs Cuebot / DB / CueWeb. **Does not participate in rendering.** |
| **Artist Workstation** | Windows | Primary workstation for artists. **Harvested as a render node after business hours.** |
| **Render Host** | Windows | Dedicated headless render node; unattended. |

**Artist Workstations possess dual identities** — they host both "Client Utilities" and "Render Node Agents", requiring the most comprehensive preparation.

---

# 1. OpenCue Server (Linux + Docker)

The application layer is encapsulated within Docker containers, but **several host-level infrastructure requirements must be satisfied on the host operating system**.

## 1. Prerequisites

```
Docker Engine + Docker Compose
Portainer (Optional)
```

## 2. Inbound Network Ports

| Port | Direction | Purpose | Requirement |
|---|---|---|---|
| **8443** | Inbound | RQD registration, heartbeats, and client connectivity | **Mandatory** |
| 3000 | Inbound | CueWeb browser UI | Optional (if deployed) |
| 5432 | — | **Do not expose**; internal container network only | — |
| 8448 | — | **Do not expose**; internal communication between CueWeb and REST Gateway | — |

## 3. Critical: In-Container DNS Resolution for Render Node Short Hostnames

Cuebot truncates hostnames reported by RQDs to their first label and connects back to port 8444. Therefore, that short hostname must be resolvable **from within the Cuebot container** — containers do not automatically inherit host DNS search domains.

Post-deployment verification commands:

```bash
docker exec opencue-cuebot getent hosts RENDER01
docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/RENDER01/8444" && echo OK || echo FAIL'
```

If resolution fails, overlay [`notes/deploy/server/site.example.yml`](../deploy/server/site.example.yml) to add `dns` and `dns_search` pointing to internal studio DNS servers (see [`11` Section 1](11-production-risks-and-todos.md#1-multi-node-dns-resolution-avoid-hardcoded-extra_hosts) and [`22` Section 6](22-two-deployment-routes.md#6-primary-manifest-architecture-environment-driven-configuration)). **Avoid hardcoding entries in extra_hosts, which does not scale.**

Failure to resolve hostnames leaves frames stuck in `RUNNING` with zero log output while host lists show healthy `UP` status, creating a severe diagnostic blind spot.

## 4. Shared Storage (Required Only for CueWeb)

CueWeb requires access to shared storage to read and render frame logs in the browser:
- Mount SMB shares on the host OS and bind mount into the container.
- Alternatively, use Docker's local volume driver with `type: cifs` (avoids host mounting, though the **host kernel must support CIFS**; see [`16-portainer-and-ssh-division.md`](16-portainer-and-ssh-division.md)).

If CueWeb web log inspection is not utilized, this mount can be omitted.

## 5. Maintenance Schedules (Mandatory)

Operations unsupported by Portainer that require host cron or maintenance containers (see [`16-portainer-and-ssh-division.md`](16-portainer-and-ssh-division.md)):

| Task | Consequence if Omitted |
|---|---|
| PostgreSQL historical table purge | **Unbounded database growth** (No automated cleanup in Cuebot) |
| `pg_dump` logical backups | Total state loss upon host storage failure |
| Frame log retention purge | Shared storage exhaustion |
| Registry garbage collection | Registry disk exhaustion |

## 6. Miscellaneous Configuration

- `daemon.json`: Enforce container log rotation (unbounded by default).
- systemd: Ensure Docker service starts automatically on host boot.
- Registry: **Must configure valid TLS certificates**; otherwise, `insecure-registries` must be added to host daemon configs.

References: [`07`](07-portainer-deployment-log.md), [`11`](11-production-risks-and-todos.md), [`14`](14-registry-workflow.md), [`15`](15-storage-planning.md), [`16`](16-portainer-and-ssh-division.md).

---

# 2. Artist Workstation (Windows)

Dual role: Interactive workstation during daytime; render node overnight.

## 1. Python Environment

Validated using native **Python 3.11.9** on Windows (**not WSL**):

```
python -m venv C:\opencue\venv
```

## 2. Package Installation

```bash
# Client utilities
pip install ./proto ./pycue ./pyoutline ./cueadmin ./cuegui ./cuesubmit ./cuenimby

# Render node agent
pip install ./rqd
pip install wmi pywin32          # Mandatory Windows dependencies omitted in pyproject.toml
cd rqd/winps && pip install .    # Mandatory for memory metrics reporting; requires MSVC
```

Installed packages:
`opencue_cuegui`, `cuenimby`, `cuesubmit`, `proto`, `pycue`, `pyoutline`, `rqd`, `PySide6 6.5.3`, `pywin32`, `wmi`, `winps`.

Critical omissions to avoid:
- `wmi` / `pywin32`: Without these, RQD crashes on launch.
- `winps`: Without this, RQD reports 0 for all memory metrics without warning.

## 3. Configuration File Placement Matrix

Configuration paths across OpenCue components on Windows:

| Component | Path |
|---|---|
| pycue / cuegui / cuesubmit / cueadmin | `%APPDATA%\opencue\opencue.yaml` |
| CueNIMBY | `%USERPROFILE%\.config\opencue\cuenimby.json` |
| RQD | `%LOCALAPPDATA%\OpenCue\rqd.conf` (or via `RQD_CONFIG_FILE`) |

CueNIMBY uses Linux convention `~/.config` without platform branching. On fresh Windows machines, `~/.config` does not exist, causing CueNIMBY to fail on launch because `mkdir()` omits `parents=True` (see [`05` Issue #10](05-upstream-issues.md#10-cuenimby-fails-to-launch-on-clean-windows-machines-due-to-directory-creation-failure)). Ensure setup scripts create this directory beforehand.

Templates: [`notes/deploy/client/opencue-client.yaml`](../deploy/client/opencue-client.yaml), [`notes/deploy/node/cuenimby-workstation.json`](../deploy/node/cuenimby-workstation.json), [`notes/deploy/node/rqd-windows.conf`](../deploy/node/rqd-windows.conf).

## 4. Directory Layout

```
C:\opencue\
    venv\            Python virtual environment
    bin\             DCC wrapper scripts (.bat per version)
    scripts\         Render scripts
    tmp\             RQD temporary directory, Nuke disk cache
    logs\            (Local frame logs if not writing to shared storage)
```

## 5. DCC Software & Wrapper Scripts

Standardized location for wrappers: `C:\opencue\bin\`:
- `hython-22.0.429.bat`
- `maya-render-2027.bat`
- `nuke-17.0v1.bat`

Filename must be identical across nodes; internal contents resolve to local installation paths.

Mandatory requirements:
1. **Must be pure ASCII text**: `cmd.exe` parses batch files using the system OEM code page. UTF-8 multi-byte characters break block parsing (see [`09` Pitfall #13](09-nimby-and-hybrid-fleet.md#pitfall-13-batch-files-must-be-pure-ascii)).
2. **Declare license servers**: RQD does not inherit user environment variables (`ADSKFLEX_LICENSE_FILE`, `foundry_LICENSE`, `solidangle_LICENSE`).
3. **Return explicit non-zero exit codes** (e.g. exit 127) when executables are missing.

## 6. RQD Configuration (`rqd.conf`)

```ini
[Override]
OVERRIDE_CUEBOT      = <Linux Server Hostname or IP>
OVERRIDE_HOSTNAME    = <Single-label Local Hostname>
RQD_BECOME_JOB_USER  = False
RQD_USE_IP_AS_HOSTNAME = 0
OVERRIDE_IS_DESKTOP  = True
OVERRIDE_NIMBY       = False          # Managed via CueNIMBY scheduling
RQD_TMPDIR           = C:\opencue\tmp
RQD_TAGS             = general houdini22 houdini_22_0_429 maya2027 nuke17
```

`RQD_TAGS` must enumerate all installed DCC versions. `OVERRIDE_HOSTNAME` must be a single-label short name resolvable inside Cuebot.

## 7. Execution Architecture: User Logon Trigger, Not Windows Service

Both NIMBY and CueNIMBY must run inside the **interactive user session**. Windows Services execute in Session 0 and cannot monitor user mouse and keyboard activity, breaking preemption.

The launch script `C:\opencue\bin\rqd-start.bat` manages:
1. Fixing working directories.
2. Initializing clean `PATH` and `TEMP/TMP` variables.
3. Sequencing launch: start RQD, pause, then start CueNIMBY.

## 8. CueNIMBY Scheduling

```json
"schedule": {
  "monday": { "start": "09:00", "end": "18:00", "state": "disabled" },
  ...
}
```

Express schedules using **non-crossing disabled intervals**. Spanning midnight (e.g., `18:00-09:00 available`) triggers upstream evaluation bugs and inverts states (see [`09` Pitfall #11](09-nimby-and-hybrid-fleet.md#pitfall-11-schedules-crossing-midnight-fail-completely)).

## 9. Firewall & Networking

| Port / Protocol | Direction | Requirement |
|---|---|---|
| Outbound 8443 | Outbound | Connects to OpenCue Server |
| **Inbound 8444** | Inbound | **Mandatory**; Cuebot connects back to dispatch frames |
| Network drives | — | Synchronized letter mappings studio-wide |

## 10. Endpoint Protection (EDR / Antivirus)

RQD's built-in NIMBY (`OVERRIDE_NIMBY = True`) uses `pynput` to attach global input hooks, which enterprise EDR regularly flags as keyloggers. Utilizing CueNIMBY scheduling while setting `OVERRIDE_NIMBY = False` avoids global input hooks entirely (see [`11` Section 5](11-production-risks-and-todos.md#5-antivirus--edr-may-flag-nimby-as-spyware)).

## 11. In-DCC Submission Plugins (Optional)

Plugins available in `cuesubmit/plugins/`:
- Maya: `CueMayaSubmit.py`, `userSetup.py`
- Nuke: `CueNukeSubmit.py`, `menu.py`
(Blender plugins are not included in upstream OpenCue).

---

# 3. Render Host (Windows Dedicated Headless)

Similar to workstations, but omits client utilities and runs as a headless Windows Service.

## Comparison with Workstations

| Feature | Artist Workstation | Dedicated Render Node |
|---|---|---|
| Client Utilities (cuegui / cuesubmit) | Required | **Not needed** |
| CueNIMBY | Required | **Not needed** |
| `OVERRIDE_IS_DESKTOP` | `True` | **`False`** |
| `OVERRIDE_NIMBY` | `False` (Scheduled) | `False` |
| Launch Method | User logon trigger | **Windows Service** |
| Allocation | `local.desktop` | `local.general` |
| `OVERRIDE_CORES` | Reserve interactive cores | Maximize all cores |

## Software Installation

```bash
pip install ./proto ./rqd
pip install wmi pywin32
cd rqd/winps && pip install .
```

## Service Mode Drive Mappings (Verification Required)

Mapped drive letters are tied to interactive logon sessions. Windows Services run in Session 0 where interactive drive mappings do not exist.
- Verify whether the service account accesses mapped drive letters (e.g., `H:\`).
- If inaccessible, map drives via `net use` upon service startup, configure GPO persistent mappings, or transition asset paths to UNC.

## Execution: Windows Service

Dedicated render nodes run as native Windows Services, resolving auto-start on boot. Configure `NODE_ROLE=render` in wrapper scripts to bypass CueNIMBY.

---

# 4. Common Studio Pre-Requisites

| Requirement | Description |
|---|---|
| **Synchronized Drive Letters** | Identical drive letters map to identical network shares across all machines |
| **DNS Short Name Resolution** | Short hostnames resolvable inside the Cuebot container |
| **Shared Storage Quotas & Purging** | Frame logs and render output retention policies |
| **Forward-Slash UNC Log Roots** | `CUE_FRAME_LOG_DIR` configured with `//fileserver/...` |
| **Clock Synchronization (NTP)** | Uniform system clocks for logs, heartbeats, and frame profiling |

---

# 5. Recommended Staged Deployment Sequence

```
1. OpenCue Server
   └─ Deploy Docker stack and confirm port 8443 reachability
        │
2. Single Render Host (Validation Pilot)
   ├─ Install Python, RQD, and winps
   ├─ Configure wrappers, rqd.conf, and RQD_TAGS
   ├─ Verify registration in cueadmin -lh
   ├─ Verify Cuebot container resolves short name and reaches port 8444
   └─ Submit real DCC render job and verify completion
        │
3. Scale Remaining Render Hosts
   └─ Replicate configuration, adjusting OVERRIDE_HOSTNAME and local paths
        │
4. Artist Workstations
   ├─ Install client tools and opencue.yaml
   ├─ Validate cuegui visibility and cuesubmit dispatching
   └─ Configure RQD and CueNIMBY for after-hours harvesting
        │
5. Maintenance Automation
   └─ Configure database maintenance, backups, and log purging
```

**Pilot a single render node first.** Validating the complete chain on one node prevents replicating troubleshooting efforts across twenty machines.
