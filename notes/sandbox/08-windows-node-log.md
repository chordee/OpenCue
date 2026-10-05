# 08 — Windows Render Node Verification Log

Verification Objective: **Run Cuebot inside Docker as the server, with Windows machines operating as render nodes and artist workstations.**
This precisely matches the ultimate production deployment topology.

Conclusion: **Fully feasible; frames successfully executed and completed on Windows.**
However, five pitfalls were encountered during implementation, two of which will inevitably recur in production deployments.

## Architecture

```
Docker (Portainer stack "opencue")            Windows Host Machine
  ├── opencue-db      (5432 internal only)      ├── RQD (Native, Python version)
  ├── opencue-flyway  (one-shot migration)      │    Listens on port 8444
  └── opencue-cuebot  (8443 exposed)  ←─gRPC──→ └── Workstation client tools (venv)
```

## Installation

Using Windows-native Python 3.11.9 to create a virtual environment (**not WSL**):

```bash
python -m venv C:\Users\<user>\opencue-win-venv
C:\Users\<user>\opencue-win-venv\Scripts\python.exe -m pip install ./proto ./rqd
```

Installed the **Python version of RQD** (`rqd/`), rather than the Rust version, because:
- `sandbox/rqd_windows.conf` targets Python RQD's `[Override]` INI syntax.
- Rust RQD explicitly marks `run_as_user` as unsupported on Windows (`rust/crates/rqd/src/frame/running_frame.rs:942`).

### Pitfall #5: Undeclared Windows Dependencies

Crashed immediately upon first launch:

```
File "rqd/rqmachine.py", line 762, in __updateProcsMappingsFromWindows
    import wmi
ModuleNotFoundError: No module named 'wmi'
```

In `rqd/pyproject.toml`, `dependencies` lists only `opencue_proto / psutil / pynput / future`, with **zero Windows-specific packages declared**. However, `rqmachine.py` unconditionally imports `wmi` on Windows platforms.

Manually installed missing dependencies:

```bash
pip install wmi pywin32
```

**Upstream Feedback Item**: Conditional dependencies should be added:

```toml
dependencies = [
    ...,
    "wmi; sys_platform == 'win32'",
    "pywin32; sys_platform == 'win32'",
]
```

## Configuration

Configuration file location (`rqconstants.py:145`): `%LOCALAPPDATA%\OpenCue\rqd.conf`, or overridden via `RQD_CONFIG_FILE` environment variable or `-c` argument.

Template available at [`notes/deploy/node/rqd-windows.conf`](../deploy/node/rqd-windows.conf). Key settings:

| Setting | Value | Description |
|---|---|---|
| `OVERRIDE_CUEBOT` | `localhost` | Cuebot address. Set to Linux server hostname or IP in production |
| `OVERRIDE_HOSTNAME` | `LAPTOP-ULJICLO8` | **Hostname reported to Cuebot (see Pitfall #6 below)** |
| `RQD_BECOME_JOB_USER` | `False` | Disable user switching on Windows |

### Pitfall #6: Cuebot Truncates Hostnames to First Label and Requires In-Container Resolution

Initially, `OVERRIDE_HOSTNAME` was set to `host.docker.internal` (standard Docker mechanism to resolve the host machine).

`rqd/rqd/rqutil.py:207` `getHostname()` returns `OVERRIDE_HOSTNAME` verbatim. However, `cueadmin -lh` showed the registered hostname as **`host`** — **Cuebot truncates FQDNs to their first label on the server side**.

Cuebot then attempts to contact port 8444 using that stored short name:

```
docker exec opencue-cuebot getent hosts host
  → NO-RESOLVE
docker exec opencue-cuebot getent hosts host.docker.internal
  → 192.168.65.254
```

Consequently, frames could not be dispatched (exhibiting symptoms identical to [Pitfall #3 in `04-deployment-process.md`](04-deployment-process.md#pitfall-3-rqd-reports-ipv6-address-cuebot-fails-to-connect-back)).

**Fix**: Configure a **single-label** actual hostname and supply `extra_hosts` in the Cuebot compose service:

```yaml
cuebot:
  extra_hosts:
    - "${RENDER_NODE_NAME}:${RENDER_NODE_ADDR}"
```

(In this local test, the render node was the Docker host itself, so `RENDER_NODE_ADDR=host-gateway`.)

**Crucial Production Takeaway**:
Every **short hostname** reported by Windows render nodes must be resolvable **from within the Cuebot container**. Because containers do not automatically inherit host DNS search domains, short name queries inside the container may fail even if studio DNS functions properly.

Pre-deployment verification command:

```bash
docker exec opencue-cuebot getent hosts <windows_node_short_hostname>
```

If unresolvable, configure container DNS search domains or enumerate `extra_hosts` entries in compose.

Verify actual reverse reachability:

```bash
docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/<node_hostname>/8444" && echo OK || echo FAIL'
```

### Pitfall #7: Linux-Style Log Paths Resolve to "Current Working Drive" on Windows

Cuebot defaults to `CUE_FRAME_LOG_DIR=/tmp/rqd/logs`. When Python RQD on Windows receives this path, it resolves it as an **absolute path relative to the current working drive**.

Launching RQD from `D:\dev\OpenCue` caused logs to be written to:

```
D:\tmp\rqd\logs\testing\testshot\logs\<job>--<id>\<job>.<frame>.rqlog
```

**No error is logged; files are quietly written to unexpected locations.** Starting from another drive or via Windows service causes logs to redirect elsewhere. Meanwhile, Cuebot and CueWeb continue referencing `/tmp/rqd/logs/...`, resulting in failed log viewing in GUI tools.

The log file even contained mixed separators:

```
logDestination  /tmp/rqd/logs/testing/testshot/logs/<job>--<id>\<job>.<frame>.rqlog
```

**Production Mandate**: Set `CUE_FRAME_LOG_DIR` to a shared storage path accessible to all nodes (**frame logs must use forward-slash UNC syntax**, as CueWeb inside Linux containers must also read them; other asset paths can use mapped drives; see [`11` Section 2](11-production-risks-and-todos.md#2-network-drive-letters-are-supported-with-one-exception)), avoiding default `/tmp/rqd/logs`.

### Pitfall #8: PATH Environment Variable Pollution

The initial test command `cmd /c timeout /t 3 /nobreak` failed:

```
D:\dev\OpenCue>cmd /c timeout /t 3 /nobreak
timeout: invalid time interval '/t'
```

This invoked **GNU coreutils `timeout`** rather than Windows native `timeout.exe` — because RQD was launched from Git Bash, inheriting a PATH containing `C:\Program Files\Git\usr\bin`, which `RQD_USE_PATH_ENV_VAR=1` passed directly to the frame subprocess.

**Lesson**: RQD on Windows nodes must be launched from a **clean execution environment** (Windows Service or Scheduled Task), rather than interactive developer shells, preventing inconsistent frame runtime environments across machines.

### Pitfall #9: Command Quotes Stripped by shlex

`load_test_jobs.py --command` uses `shlex.split()`, which parses:

```bash
--command "python.exe -c import time;time.sleep(3)"
```

into individual tokens, passing `import` as a script argument to Python and triggering `SyntaxError`.

Testing commands should invoke standalone script files directly:

```bash
--command "C:/Users/chordee/opencue-win-venv/Scripts/python.exe C:/tmp/rqd/testframe.py"
```

## Successful Verification Run

Frame log (`D:\tmp\rqd\logs\...\0001-test_layer.rqlog`):

```
=== OpenCue test frame ===
system : Windows 10
node   : LAPTOP-ULJICLO8
python : 3.11.9
cwd    : D:\dev\OpenCue
frame  : 0001-test_layer
show   : testing
=== frame done ===

RenderQ Job Complete
exitStatus          0
renderhost          LAPTOP-ULJICLO8
```

All 3 frames completed with `SUCCEEDED`. **The entire pipeline was validated end-to-end**:
Cuebot scheduler in Linux container → dispatches to Windows-native RQD → executes Python on Windows → writes logs → reports completion.

## Observation: Working Directory (`cwd`) Does Not Take Effect

The JobSpec in the frame log declares:

```
cwd  C:\Users\chordee\AppData\Local\Temp/testing-testshot-.../0001-test_layer
```

However, `os.getcwd()` inside the frame printed `D:\dev\OpenCue` (RQD's own working directory). Windows RQD appeared not to switch the child process working directory.

**Impact**: Render jobs relying on relative paths cannot locate project assets.

Follow-up testing confirmed this behavior (see below).

## Unverified Items at Initial Testing

> **Note**: This section reflects findings at the time of initial testing. Several items have since been validated.
> **Refer to [`19-verification-summary.md`](19-verification-summary.md) for the definitive status matrix.**

| Item | Notes |
|---|---|
| True multi-machine LAN | Tested using Docker host with `host-gateway`. Production traverses separate physical machines over LAN |
| NIMBY | Disabled in configuration initially. Workstation user-preemption behavior required testing |
| CueNIMBY | Tray notification utility uninstalled during initial phase |
| Daemonization | Running RQD as a native Windows service required verification (Pitfalls #7 and #8 indicate this is mandatory) |
| Production DCCs | Test frames ran Python scripts; Maya, Houdini, Nuke, Blender required testing |

---

# Sequel: Clean Runtime Execution & winps Compilation

## Launching via Wrapper Script (Resolving Pitfalls #7 and #8)

Created `C:\opencue\rqd-start.bat` (template in [`notes/deploy/node/rqd-start.bat`](../deploy/node/rqd-start.bat)):

```bat
@echo off
cd /d C:\opencue
set RQD_CONFIG_FILE=C:\opencue\rqd.conf
"C:\Users\chordee\opencue-win-venv\Scripts\rqd.exe" >> C:\opencue\rqd-service.log 2>&1
```

Benefits: Fixes working directory and prevents inheriting developer shell environment variables.

Local verification confirmed **system PATH is clean** (excluding `Git\usr\bin`), eliminating Pitfall #8 when launched outside Git Bash.

## Correct Approach for Log Directory Configuration

Previously, log file destination depended on whichever drive RQD happened to launch from.

**Correct Approach**: Since all render nodes run Windows, configure Cuebot's `CUE_FRAME_LOG_DIR` directly using a **Windows-compatible path**. Cuebot merely passes this string to RQD without parsing it locally.

```
CUE_FRAME_LOG_DIR=C:/opencue/logs
```

(Updated in [`notes/deploy/server/env.example`](../deploy/server/env.example) and applied to stack via Portainer API.)

Verification:

```
C:\opencue\logs\testing\testshot\logs\<job>--<id>\<job>.0001-test_layer.rqlog  ← Present
New rqlog files under D:\tmp within last 5 minutes                           ← 0 files
```

Across multiple render nodes, replace this with a forward-slash UNC path (e.g., `//fileserver/opencue/logs`).

## winps: Memory Reporting on Windows

### Behavior Without winps

`rqd/rqd/rqmachine.py:317`:

```python
def rssUpdate(self, frames):
    if platform.system() == 'Windows' and winpsIsAvailable:
        self.rssUpdateWindows(frames)
        return
    if platform.system() != 'Linux':
        return          # ← Windows without winps aborts immediately
```

Without `winps`, Windows render frames **never report memory consumption**, leaving `int_mem_max_used` permanently 0.

**Impact**: OpenCue memory-based enforcement mechanisms (killing runaway frames, memory profiling) become entirely non-functional on Windows nodes.

### Compilation Requirements

`pip install ./rqd` does not build `winps`. It is a C++ extension under `rqd/winps/` requiring manual build:

```bash
cd rqd/winps
<venv>/Scripts/python.exe -m pip install .
```

Requires **MSVC C++ Build Tools** (compiled cleanly in our environment).

Note: `rqd/winps/setup.py` uses `from distutils.core import setup`. Although `distutils` was removed in Python 3.12, setuptools provides a compatibility layer. Compiled successfully on **Python 3.11.9**.

### Empirical Verification

After installing winps, executed a frame allocating 300 MB for 35 seconds:

```
    str_name     | str_state | int_mem_max_used | int_exit_status
-----------------+-----------+------------------+-----------------
 0001-test_layer | SUCCEEDED |           333548 |               0
```

333548 KB ≈ 325 MB, matching expectation. **winps is fully operational.**

### Critical Insight: `maxrss = 0` Does Not Mean Zero Memory Usage Nor a Broken winps

`rqconstants.py:55` defines `RSS_UPDATE_INTERVAL = 10` (seconds).

RQD samples running frame processes **once every 10 seconds**. Whether a frame records memory usage depends on whether its execution lifetime crosses a sampling boundary.

Empirical comparison (first two rows executed identical hython script):

| Frame | Execution Profile | `int_mem_max_used` |
|---|---|---|
| `drivetest` (Failed attempt) | Retried after failure, **ran two iterations**, crossed sample point | **461,956 KB** |
| `drivetest` (Successful run) | Ran single iteration (~7s), landed between sample intervals | **0** |
| `nuke_render` | ~2s per frame | **0** |
| `maya_render` | ~18s per frame, always crosses sample interval | 530,644 KB |
| `houdini_render` | ~6s per frame, 4 sequential frames | 1,145,644 KB |

**Two Common Misinterpretations**:

1. **Assuming winps is broken upon seeing 0**: The frame simply finished between sample intervals. Verify winps with frames running longer than 10 seconds.
2. **Using historical memory metrics for capacity planning**: **Short frame metrics are unreliable**. Exclude frames reporting 0 to avoid severe underestimation.

## Confirmed: Frame Working Directory (`cwd`) Fails on Windows

Comparative testing verified this issue definitively.

Frame JobSpec declares an isolated temporary directory:

```
cwd  C:\Users\chordee\AppData\Local\Temp/<job>/<frame>
```

However, `os.getcwd()` inside the frame consistently reported RQD's own working directory:

| RQD Working Directory | Frame Actual cwd |
|---|---|
| `D:\dev\OpenCue` (Launched via Git Bash) | `D:\dev\OpenCue` |
| `C:\opencue` (Launched via wrapper script) | `C:\opencue` |

**Impact**: Renders relying on relative paths look in incorrect directories; concurrent frames share working directories with race condition risks.

**Production Workaround**: Enforce absolute paths in all render commands.

## Automatic Startup Considerations

Goal: Launch RQD automatically upon user logon.

| Approach | Result |
|---|---|
| Scheduled Task (`schtasks /create /sc onlogon`) | Access denied without administrative privileges |
| Startup folder `.vbs` | Blocked by environment security persistence restrictions |

Ready-to-deploy templates:
- [`notes/deploy/node/rqd-start.bat`](../deploy/node/rqd-start.bat) — Execution wrapper
- [`notes/deploy/node/rqd-start-hidden.vbs`](../deploy/node/rqd-start-hidden.vbs) — Silent window launcher

**Production Architecture Recommendation**: Do not run RQD as a Windows Service on artist workstations. Windows Services run in Session 0, which **cannot inspect user keyboard/mouse input**, breaking NIMBY preemption. Workstations should use logon-triggered Scheduled Tasks distributed via Group Policy (GPO) to execute in the user session. Dedicated headless render nodes should use native Windows Services.
