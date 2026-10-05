# 33 — Rebuilding the Sandbox from Scratch Following Documentation

Tearing down the local OpenCue environment completely and rebuilding from an empty database strictly following [`notes/deploy/`](../deploy/README.md) to audit procedural instructions for gaps or bottlenecks. Server actions were executed via Portainer; nodes and workstations followed guides 02 and 03. Conducted 2026-09-25.

---

## 1. Test Environment Setup

| Component | Implementation |
|---|---|
| Server | Local Docker Desktop instance; purged existing stack and removed DB volumes (backed up beforehand) |
| Render Node & Workstation | Single host laptop; wiped `C:\opencue\` completely and rebuilt in workstation role |
| Shared Network Storage | `D:\opencue_share` mapped to `P:` via `subst P: D:\opencue_share` to mirror `P:\...` paths in documentation |
| Project Workspace | `P:\projects\opencue_test\{scenes,scripts,render}`; updated lab scripts to target this path |
| Frame Logs | Initially set to `CUE_FRAME_LOG_DIR = P:/logs` (violating Section 01 UNC mandates); unreadable in CueWeb; subsequently corrected to local SMB share (see Section 3) |

Drives mounted via `subst` exist only within the interactive user login session, behaving identically to mapped network drives and requiring re-execution upon reboot.

---

## 2. Bottlenecks and Ambiguities Encountered During Procedure Execution

| Step | Issue | Resolution |
|---|---|---|
| 01: Create Stack | Compose Path field rendered as a link showing full path but linking to `server/...`; copying the link target corrupted the path, causing deployment failure (`open /data/compose/7/server/opencue.portainer.yml: no such file`) | Converted documentation reference to plain text |
| 01: Create Stack | Existing stack persisted, causing name collision | Updated 01 with prerequisites; containers mounting deleted host directories must be removed before stack deletion |
| 01: Verification | Flyway log concluded with 3 lines of `duplicate key ... c_task_lock_pk` | Harmless conflict between upstream seed data and migrations; documented in 01; see [`05` Issue #26](05-upstream-issues.md#26-clean-deployments-duplicate-task_lock-insertions-between-seed-data-and-migrations) |
| 02: Node Registration | **Node registration failed permanently**: cumulative tag string length (129) exceeded upstream schema limit (128) | Applied studio Flyway migration; see [`32`](32-node-tag-limit.md) |
| 02: Configuration | `rqd-start.bat` omitted EDIT marker for `NODE_ROLE`, despite documentation stating it must be reviewed per machine | Added EDIT marker |
| 03: Configuration | Client templates referenced server as `linux-server.studio.local`; other docs referenced `opencue-server.studio.local` | Standardized references |
| 04: Upgrade Images | **Pull and redeploy** button disabled after modifying environment variables | Clarified requirement to click **Save settings** first; updated 04 with button names |
| 04: Upgrade Images | Image download speeds were slow (local host to GHCR), requiring nearly an hour to swap containers | Documented in 04; noted that existing containers run uninterrupted during downloads |

Deleting `C:\opencue` encountered two local host blocks: active RQD processes holding open working directories, and development file protection policies, both resolved manually.

---

## 3. Verification Results

### Server (`01` Section 7)

| Check Item | Result |
|---|---|
| Container States | Flyway and init: Exited (0); all other services reported healthy |
| Init Container | Initialized `houdini2204`, `maya2027`, and `nuke17` services successfully |
| CueWeb | HTTP 200 |
| Hostname Resolution & Port 8444 | `getent hosts LAPTOP-ULJICLO8` succeeded; TCP handshake successful |

### Render Node and Workstation (`02`, `03`)

| Check Item | Result |
|---|---|
| venv & Dependencies | RQD, winps (compiled locally), wmi, pywin32, `ocrun`, and client utilities installed |
| `ocrun` Configured Versions | Maya 2027, Houdini 22.0.429, Nuke 17.0v1 |
| Node Registration | Registered successfully post tag-width fix; status UP, allocation `local.desktop` |

### Submission Tools (Loaded from `P:`)

Executed [`lab/check_submit_tools.py`](lab/check_submit_tools.py) specifying `--maya-dir`, `--houdini-dir`, `--nuke-dir` pointing to `P:` deployment locations: all 15 tests passed. Emitted Houdini commands targeted versioned directory `P:/pipeline/opencue/releases/2026.09.25/client/houdini/opencue_houdini_render.py`.

Submitted live tasks via `--submit`: Houdini, Maya, and Nuke all succeeded, writing scenes, scripts, outputs, and frame logs directly to `P:`. An initial Nuke run failed because the output directory did not exist (Write nodes do not auto-create directories by default); Nuke terminated with exit code 1 as expected. Enabling `create_directories` in the test script resolved the issue.

### Container Image Upgrade

Updated five stack images in Portainer to `1.34.4-1acac546` (incorporating studio migrations):

```
flyway: Successfully validated 43 migrations ... Schema "public" is up to date.
init:   service houdini2204 already exists ... (preserving existing entries)
```

The node reconnected automatically in `local.desktop`; CueWeb returned 200; a test Houdini frame rendered in 43 seconds.

### CueWeb Frame Log Retrieval

Using `P:/logs` caused CueWeb to display "Log file not found": Cuebot recorded paths as `P:/logs/...`, which do not exist inside Linux containers. This was an artifact of bypassing UNC path rules in the test environment.

Audit revealed that **`env.example` template configurations were also mismatched**: `CUE_FRAME_LOG_DIR=//fileserver/opencue/logs`, but `FRAME_LOG_MOUNT_TARGET` and `CUEWEB_LOG_ROOTS` were defined as `/mnt/logs`. CueWeb received `//fileserver/opencue/logs/...` (normalized to `/fileserver/opencue/logs/...` in Linux), which failed to align with mount points. Both variables were updated to match `CUE_FRAME_LOG_DIR` with the leading slash stripped; rule documented in Section 01.

Verification: Shared `D:\opencue_share` as SMB share `opencue_share`; updated stack environment variables:

```
CUE_FRAME_LOG_DIR=//LAPTOP-ULJICLO8/opencue_share/logs
FRAME_LOG_MOUNT_TARGET=/LAPTOP-ULJICLO8/opencue_share/logs
CUEWEB_LOG_ROOTS=/LAPTOP-ULJICLO8/opencue_share/logs
```

Submitted a Shell job: RQD wrote logs via UNC; `/api/getlog?path=//LAPTOP-ULJICLO8/...` returned HTTP 200 with complete log contents. Jobs dispatched prior to the configuration change retained `P:` paths and remained unreadable.

Portainer flashed "Unable to retrieve stack file" once upon clicking Update, but redeployment executed in the background and applied the new variables, attributable to transient Git polling latency.

---

## 4. Isolated Non-Reproducible Anomaly: Maya Stalling for Approximately 11 Minutes

During initial regression testing post-rebuild, two Maya frames (launched at 14:26:03 and 14:26:37) stalled during Arnold plugin initialization, **terminating concurrently at 14:37:30**. Logs jumped directly from Arnold version banners to `00:11:11`.

Subsequent test runs failed to reproduce the issue:

| Scenario | Execution Duration |
|---|---|
| Direct execution, minimal RQD environment | 12s (emitted `OptiX cache ... LOCALAPPDATA undefined` warning) |
| Direct execution, `LOCALAPPDATA` supplied / directed to empty folder | 40s / 20s |
| Direct execution, full user environment | 14s |
| Farm render, single frame / 2 concurrent frames | 18s / 18s each |
| Farm render, concurrent with Houdini and Nuke | 33s each |

`LOCALAPPDATA` was not the cause. Both frames terminating simultaneously suggests a shared resource lock timeout (such as license verification or cache initialization), likely a one-time cold-start artifact. No configuration changes were made.

---

## 5. Post-Reboot Behavior

Placed `rqd-start-hidden.vbs` in the Startup folder and rebooted: RQD and CueNIMBY launched automatically upon user login. Two issues were observed:

| Issue | Cause | Mitigation |
|---|---|---|
| RQD, CueNIMBY, pycue failed to reach `localhost:8443` (`End of TCP stream`); CueWeb port 3000 operated normally | Docker Desktop port forwarding corrupted. Cuebot remained reachable internally; host port 8443 had a lingering WSL `wslrelay` socket bound on `::1` | Restarted `opencue-cuebot` container. Specific to Docker Desktop; production Linux hosts are unaffected |
| `P:` drive missing | `subst` drives expire with user sessions | Re-executed `subst P: D:\opencue_share`; frames resumed reading `P:` immediately without restarting RQD |

---

## 6. Pending Verification Items

- Secondary physical render hosts (cross-node networking, firewall traversal, drive letter consistency).
- Visibility of `P:` when executing RQD as a headless Windows Service.
- Dedicated network file storage appliances (tests utilized Docker and local host file sharing on a single machine).
