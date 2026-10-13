# OpenCue Production Deployment Guide

This directory covers **deployment procedures only**. The testing process, pitfalls encountered, and source code references behind each decision are documented in `notes/sandbox/`, referenced throughout via "Reference" tags.

---

## Environment Prerequisites

| Item | Details |
|---|---|
| OpenCue Server | A single Linux + Docker host, managed via Portainer. **Does not participate in rendering**. Other studio services may coexist on this host. |
| Render Nodes | Windows. Categorized into **Artist Workstations** (utilized after work hours) and **Dedicated Render Nodes**. |
| DCC Applications | Houdini / Maya / Nuke. **Installation paths vary per machine; multiple versions coexist**, with projects specifying required versions. |
| Network Drive | Drive letters are consistent studio-wide; project files reference asset paths using mapped drive letters. |

---

## Guide Index by Machine Role

| Role | Document | Configuration Directory |
|---|---|---|
| OpenCue Server | [`01-server.md`](01-server.md) | [`server/`](server/) |
| Dedicated Render Node | [`02-render-nodes.md`](02-render-nodes.md) | [`node/`](node/) |
| Artist Workstation | [`02-render-nodes.md`](02-render-nodes.md) + [`03-workstations.md`](03-workstations.md) | [`node/`](node/) + [`client/`](client/) |
| Post-deployment Ops | [`04-operations.md`](04-operations.md) | — |
| Troubleshooting | [`17-troubleshooting.md`](../sandbox/17-troubleshooting.md) | — |

Artist workstations hold a **dual role**: daytime client workstations, and evening/night render nodes. Both guides must be completed.

---

## Local vs. Network Storage Strategy

| Local to Each Node (`C:\opencue\`) | Shared Network Storage (Studio-wide) |
|---|---|
| `venv\`: Python, RQD, `ocrun`, client tools | Frame logs (`CUE_FRAME_LOG_DIR`, UNC share) |
| `rqd.conf`: Machine-specific hostnames and tags | Scene files, render outputs (Project shares) |
| `rqd-start.bat` | Pipeline tools: DCC submission scripts, runtime execution wrappers |
| `dcc.toml`: Installed DCC versions and local paths | |
| `tmp\`: Render scratch and cache | |

**Rationale for Local Storage**: RQD must launch at system boot before network drives are mounted. Running Python from network shares is slow and unstable. Moreover, `dcc.toml` and `rqd.conf` are inherently node-specific.

**Rationale for Network Storage**: All nodes must read identical toolkits. Hosting pipeline tools on a shared share allows single-point updates without nodes lagging on outdated versions. Active DCC sessions must be restarted to load updated tools; see [`04-operations.md` Section 8](04-operations.md#8-pipeline-tool-distribution).

The specific network mount point is determined by the studio (illustrated here as `P:\pipeline\opencue\`):

| Path | Content |
|---|---|
| `P:\pipeline\opencue\client\maya\` | Maya submission tool; see [`03-workstations.md` Section 6](03-workstations.md#6-submitting-directly-from-maya) |
| `P:\pipeline\opencue\client\nuke\` | Nuke submission tool; see [`03-workstations.md` Section 8](03-workstations.md#8-submitting-directly-from-nuke) |
| `P:\pipeline\opencue\releases\<version>\client\houdini\` | Houdini submission tools and frame execution scripts; see [`03-workstations.md` Section 7](03-workstations.md#7-submitting-directly-from-houdini) |
| `P:\pipeline\opencue\releases\<version>\...` | Other execution scripts invoked by jobs during render runtime |

**Runtime scripts invoked during rendering should be version-pinned in release directories and immutable post-release** so that queued jobs do not inadvertently execute unverified in-flight changes. Submission-only scripts (e.g. Maya shelf tools) may be overwritten in place. See [`04-operations.md` Section 8](04-operations.md#8-pipeline-tool-distribution).

Important considerations:
- Paths **must not contain spaces** ([`03-workstations.md` Section 9](03-workstations.md#9-pre-submission-checklist)).
- Network items require network drive availability. Submission tools are used interactively by logged-in artists, and render scripts are invoked when running frames; both are safe. RQD itself launches at boot and must remain local.
- When running dedicated render nodes as a Windows service, **drive letter visibility is unverified** ([`02-render-nodes.md` Section 8](02-render-nodes.md#8-dedicated-render-nodes-vs-workstations)). If inaccessible in Session 0, script paths must use UNC paths.

---

## Pre-built Container Images

Pre-built Docker images are hosted publicly on GitHub Container Registry (GHCR), **accessible without authentication**:

| Component | Image |
|---|---|
| Cuebot | `ghcr.io/chordee/opencue/cuebot:1.34.22-49916ee4` |
| Flyway (DB Migration) | `ghcr.io/chordee/opencue/flyway:1.34.22-49916ee4` |
| REST Gateway | `ghcr.io/chordee/opencue/rest-gateway:1.34.22-49916ee4` |
| CueWeb | `ghcr.io/chordee/opencue/cueweb:1.34.22-49916ee4` |
| init (Bootstrap show/service) | `ghcr.io/chordee/opencue/init:1.34.22-49916ee4` |

- These defaults are pre-configured in [`server/env.example`](server/env.example).
- Tags are `<upstream release>-<commit SHA>`: the version is the upstream release the build is based on, and the SHA identifies the studio commit built.
- Target architecture: **linux/amd64** only (x86-64).
- CueWeb is packaged **without authentication**: any client reaching port 3000 can manage jobs. Restrict access via internal firewall.
- Total download size is ~6 GB; allow adequate time for initial pulls.
- New image builds are triggered via the **Sandbox images** GitHub Actions workflow; see [`04-operations.md`](04-operations.md).

---

## Deployment Workflow

```
1. OpenCue Server                            01-server.md
   └─ Deploy stack -> Verify port 8443 and CueWeb UI
        │
2. Pilot Dedicated Render Node (Single unit) 02-render-nodes.md
   ├─ Install Python + RQD + winps + ocrun
   ├─ Configure dcc.toml + rqd.conf
   ├─ [Verify] cueadmin -lh displays node with alloc prefix "local"
   ├─ [Verify] Cuebot container resolves & reaches node port 8444
   └─ [Verify] Submit and complete a real DCC test render
        │
3. Scale Remaining Dedicated Render Nodes
   └─ Replicate configuration; customize hostname and dcc.toml paths
        │
4. Artist Workstations                       03-workstations.md + 02-render-nodes.md
   ├─ Client tools + opencue.yaml
   ├─ [Verify] CueGUI connects to farm; CueSubmit queues test jobs
   └─ Install RQD + CueNIMBY (Scheduled overnight rendering)
        │
5. Maintenance & Operations                  04-operations.md
   └─ DB backups, historical job pruning, frame log rotation
```

**Step 2 must be tested on a single machine first.** Resolve and verify all node-level issues on this single pilot machine before mass rollouts to prevent repeated troubleshooting across nodes.

---

## Unverified In-Situ Edge Cases

The following items cannot be fully verified within a single-host sandbox and require careful validation during on-site deployment:

| Item | Potential Impact | Reference |
|---|---|---|
| Physical cross-machine networking (Inbound port 8444) | If blocked, frames will hang indefinitely in `RUNNING`. | [`02`](02-render-nodes.md) |
| Network drive letter visibility under Windows Service | If inaccessible, frames cannot resolve project assets. | [`02`](02-render-nodes.md) |
| Boot/Login automatic startup | Verification needed for headless nodes. | [`02`](02-render-nodes.md) |
| Container inheritance of host DNS search domains | If short hostnames fail to resolve, frames hang in `RUNNING`. | [`01`](01-server.md) |
| End-to-end UNC path storage access | CueWeb unable to load logs if mount path diverges. | [`01`](01-server.md) |
| Arnold / MtoA licensing | Unlicensed watermarks or false exits. | — |

For full verification statuses, refer to [`19-verification-summary.md`](../sandbox/19-verification-summary.md).

---

## Directory & File Overview

### Documentation

| File | Description |
|---|---|
| [`README.md`](README.md) | Overview and index (this file) |
| [`01-server.md`](01-server.md) | OpenCue server setup guide |
| [`02-render-nodes.md`](02-render-nodes.md) | Windows render node setup guide |
| [`03-workstations.md`](03-workstations.md) | Artist workstation client tools |
| [`04-operations.md`](04-operations.md) | Upgrades, backups, and maintenance |

### `server/`: Server Configurations

| File | Description |
|---|---|
| [`server/opencue.portainer.yml`](server/opencue.portainer.yml) | Primary compose stack (Portainer & Docker Compose compatible) |
| [`server/env.example`](server/env.example) | Environment variable template |
| [`server/build.yml`](server/build.yml) | Compose override for local image builds |
| [`server/site.example.yml`](server/site.example.yml) | Site-specific override (DNS, extra_hosts, etc.) |
| [`server/init/`](server/init/) | Source files for bootstrap container |
| [`server/registry.portainer.yml`](server/registry.portainer.yml) | Self-hosted private Docker registry (not needed when using GHCR) |
| [`server/monitoring.portainer.yml`](server/monitoring.portainer.yml) | Optional monitoring stack (Prometheus + Grafana) |

### `node/`: Render Node Assets

All text files strictly use pure ASCII encoding; see [`02-render-nodes.md` Section 2](02-render-nodes.md#2-critical-configurations-and-scripts-must-use-pure-ascii).

| File | Target Location | Description |
|---|---|---|
| [`node/rqd-windows.conf`](node/rqd-windows.conf) | `C:\opencue\rqd.conf` | RQD daemon configuration |
| [`node/rqd-start.bat`](node/rqd-start.bat) | `C:\opencue\rqd-start.bat` | Node startup script |
| [`node/rqd-start-hidden.vbs`](node/rqd-start-hidden.vbs) | User Startup folder | Background launcher for workstation login |
| [`node/dcc-windows.toml`](node/dcc-windows.toml) | `C:\opencue\dcc.toml` | Local DCC versions and executable paths |
| [`node/ocrun/`](node/ocrun/) | Installed via pip into venv | Unified CLI runner `ocrun` (Cross-platform) |
| [`node/cuenimby-workstation.json`](node/cuenimby-workstation.json) | `%USERPROFILE%\.config\opencue\cuenimby.json` | CueNIMBY schedule configuration |

### `client/`: Workstation Assets

| File | Target Location | Description |
|---|---|---|
| [`client/opencue-client.yaml`](client/opencue-client.yaml) | `%APPDATA%\opencue\opencue.yaml` | Connection settings for client utilities |
| [`client/maya/`](client/maya/) | `P:\pipeline\opencue\client\maya\` (Network share) | In-DCC Maya submission tool |
| [`client/nuke/`](client/nuke/) | `P:\pipeline\opencue\client\nuke\` (Network share, in `NUKE_PATH`) | In-DCC Nuke submission tool |
| [`client/houdini/`](client/houdini/) | `P:\pipeline\opencue\releases\<version>\client\houdini\` (Network share) | In-DCC Houdini submission tool and execution scripts |
| [`client/houdini/opencue.json`](client/houdini/opencue.json) | Houdini packages directory | Package definition appending Houdini tools to `PYTHONPATH` |
