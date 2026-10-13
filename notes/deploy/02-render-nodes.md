# 02 — Render Nodes (Windows)

Both dedicated render nodes and artist workstations must follow this guide. Key differences between the two roles are consolidated in Section 8.
Artist workstations additionally require [`03-workstations.md`](03-workstations.md).

---

## 1. Directory Structure

All nodes follow an identical local directory structure so that job command lines remain host-agnostic:

```
C:\opencue\
    venv\                Python virtual environment (RQD, ocrun)
    tmp\                 Scratch and temporary directory for RQD and frames (TEMP / TMP)
    dcc.toml             Installed DCC versions and executable locations  <- node/dcc-windows.toml
    rqd.conf             RQD daemon configuration                         <- node/rqd-windows.conf
    rqd-start.bat        Node launch script                               <- node/rqd-start.bat
    rqd-service.log      RQD console output (Generated automatically upon startup)
```

**Only items strictly required locally reside here.** Frame logs, scene files, render outputs, and runtime execution scripts live on shared network storage, never in `C:\opencue\`; see [`README.md`](README.md) "Local vs. Network Storage Strategy".

---

## 2. Critical: Configurations and Scripts Must Use Pure ASCII

All files under [`node/`](node/) are strictly pure ASCII. **Do not introduce non-ASCII/Unicode characters (including Chinese comments) when editing.**

| File | Parser Mechanism | Consequence of Non-ASCII Characters |
|---|---|---|
| `.bat` | Parsed by `cmd.exe` using system OEM code page (e.g. cp950) | Syntax corruption, e.g. `'tlocal' is not recognized` |
| `rqd.conf` | Read by RQD **without specifying an encoding**, falling back to system ANSI code page | Under traditional Chinese Windows (cp950), **RQD crashes on boot** (`UnicodeDecodeError`) |
| `.vbs` | Parsed by Windows Script Host using system ANSI code page | Unpredictable parsing failures |

The sandbox test machine happened to have "Beta: Use Unicode UTF-8 for worldwide language support" enabled (ACP = 65001), allowing UTF-8 commented configurations to load; **standard Chinese Windows machines fail immediately** (confirmed empirically via cp950 decoding tests).

Reference: [`notes/sandbox/09` Pitfall #13](../sandbox/09-nimby-and-hybrid-fleet.md#pitfall-13-batch-files-must-be-pure-ascii), [`notes/sandbox/17` Scenario 23](../sandbox/17-troubleshooting.md#scenario-23-rqd-crashes-immediately-on-launch-with-unicodedecodeerror), [`notes/sandbox/05` Issue #18](../sandbox/05-upstream-issues.md#18-python-rqd-reads-rqdconf-without-specifying-encoding).

---

## 3. Installation

### 3.1 Prerequisites

| Software | Purpose |
|---|---|
| Python 3.11 (Native Windows x86-64, **not** WSL, **not** Microsoft Store version) | Runs RQD and `ocrun` |
| Visual Studio Build Tools ("Desktop development with C++" workload) | Required to compile `winps` C-extension |
| OpenCue source repository (`git clone` or copied directory) | Source packages for installation |

### 3.2 Install Packages

Run from the root of the OpenCue repository:

```bat
python -m venv C:\opencue\venv
C:\opencue\venv\Scripts\python.exe -m pip install ./proto ./rqd
C:\opencue\venv\Scripts\python.exe -m pip install wmi pywin32
C:\opencue\venv\Scripts\python.exe -m pip install ./notes/deploy/node/ocrun
cd rqd\winps
C:\opencue\venv\Scripts\python.exe -m pip install .
cd ..\..
```

**Two critical packages easily overlooked**:

| Package | Consequence if Missing |
|---|---|
| `wmi`, `pywin32` | RQD **crashes on launch** (`No module named 'wmi'`); the upstream `rqd` package omits these dependencies. |
| `winps` | RQD runs, but **memory usage reports 0 permanently** with zero warning diagnostics. |

Reference: [`notes/sandbox/08`](../sandbox/08-windows-node-log.md).

### 3.3 Deploy Files

From the repository root, deploy the configuration templates:

```bat
mkdir C:\opencue\tmp
copy notes\deploy\node\rqd-windows.conf  C:\opencue\rqd.conf
copy notes\deploy\node\rqd-start.bat     C:\opencue\rqd-start.bat
copy notes\deploy\node\dcc-windows.toml  C:\opencue\dcc.toml
```

Populate `dcc.toml` with versions **actually installed** on this machine; see Section 5.

---

## 4. Configuring `rqd.conf`

The template defaults to **Dedicated Render Node**. Three fields must be customized per machine (labeled `EDIT` in the file); artist workstations require two additional modifications (labeled `EDIT (workstation)`, detailed in Section 8):

| Setting | Description |
|---|---|
| `OVERRIDE_CUEBOT` | OpenCue server hostname or IP address |
| `OVERRIDE_HOSTNAME` | The machine's **single-token short hostname** (e.g. `RENDER01`, not `RENDER01.studio.local`) |
| `RQD_TAGS` | Available dispatch tags on this node; **the first tag determines allocation assignment** |

**Why `OVERRIDE_HOSTNAME` must be a single-token short name**: Cuebot strips hostnames to their first dot-delimited token before making gRPC callbacks on port 8444. This short name must be resolvable from inside the Cuebot Docker container.
Reference: [`notes/sandbox/08`](../sandbox/08-windows-node-log.md), [`notes/sandbox/04` Pitfall #3](../sandbox/04-deployment-process.md#pitfall-3-rqd-reports-ipv6-address-cuebot-fails-to-connect-back).

### Facility Setting

```ini
DEFAULT_FACILITY = local
```

RQD's built-in default facility is `cloud`, whereas client-submitted jobs default to `local`. If facilities mismatch, the node **will never receive jobs, accompanied by zero error diagnostics**.

Verified in practice on Windows RQD: with this setting, hosts register under `local.*`; omitting it places them into `cloud.general`.
Reference: [`notes/sandbox/17` Scenario 20](../sandbox/17-troubleshooting.md#scenario-20-newly-joined-node-never-receives-work).

### Allocation Determined by the First Tag

When a node **registers for the first time**, Cuebot iterates through its reported tags, assigning the node to the first allocation matching a tag (`HostManagerService.java:189`). Therefore, the **first tag in `RQD_TAGS`** is decisive:

| Machine Role | `RQD_TAGS` Starting Tag | Registered Allocation |
|---|---|---|
| Artist Workstation | `desktop` | `local.desktop` |
| Dedicated Render Node | `general` | `local.general` |

Empirical verification across test nodes:

| `DEFAULT_FACILITY` | `RQD_TAGS` Prefix | Result |
|---|---|---|
| `local` | `general` | `local.general` |
| (Unset) | `general` | `cloud.general` |
| `local` | `desktop` | `local.desktop` |

Setting `OVERRIDE_IS_DESKTOP = True` also injects the `desktop` tag, but it is appended *after* `RQD_TAGS` and **does not influence initial allocation assignment**.

Allocation assignment occurs strictly on initial host registration; modifying `RQD_TAGS` subsequently does not alter allocation. Reassign manually via CLI if needed:

```bash
cueadmin -force -move local.general -host RENDER01
```

Once moved, pending jobs pick up the node automatically.

### Host Environment Variables Forwarded to Frames

RQD exposes a minimal set of environment variables to child frames on Windows (`SYSTEMROOT`, `APPDATA`, `TMP`, etc.). The `[UseHostEnvVar]` section at the end of `rqd.conf` allows passing designated host process variables into the frame environment:

```ini
[UseHostEnvVar]
ALLUSERSPROFILE
TZ
```

| Variable | Consequence if Omitted (Empirically Verified) |
|---|---|
| `ALLUSERSPROFILE` | Autodesk licensing components in Maya crash upon frame exit: rendering succeeds, but **every frame pops up an Autodesk Error Report modal**, adding ~15 seconds of process teardown delay per frame. |
| `TZ` | RQD hardcodes child frame timezones to `PST8PDT`. Local timestamps in frames lag Taiwan time by 15 hours; render output folders or date-stamped files inadvertently reflect the previous calendar day. Adding `TZ` here inherits host time; on Windows systems without `TZ`, the frame receives an empty value and correctly defaults to Windows local timezone settings. |

Do not add `USERPROFILE` or `LOCALAPPDATA`: child frames would inadvertently inherit logged-in artist personal preferences, scripts, and plugin caches.
Reference: [`notes/sandbox/28`](../sandbox/28-maya-crash-reporting.md), [`notes/sandbox/29`](../sandbox/29-frame-timezone.md).

### Precedence of Frame Environment Variables

Frames **do not** inherit the submitting workstation's environment, nor do they inherit the desktop user's profile on the render host. Environment variables are resolved in the following order (later layers override earlier ones):

| Order | Source | Variables |
|---|---|---|
| 1 | RQD | `PATH` (System directories + venv `Scripts` configured in `rqd-start.bat`), `SYSTEMROOT`, `APPDATA`, `TMP`, and Cuebot's `CUE_*` |
| 2 | `rqd.conf` `[UseHostEnvVar]` | Variables inherited from the host RQD process (e.g. `ALLUSERSPROFILE`, `TZ`) |
| 3 | Job-level Environment | Key-value pairs defined in the job submission **Environment** field |
| 4 | `ocrun` | `dcc.toml` `[env]` (Populated **only if unset by job**); mandatory DCC vars (`MAYA_DISABLE_CER`, `NUKE_DISK_CACHE`); `TEMP` fallback mapped from `TMP` |
| 5 | Rez (When `OCRUN_REZ` is set) | Environment resolved by `rez-env`; see ["Executing via Rez"](#executing-via-rez-ocrun_rez) |

Where to place variables:

| Variable Nature | Target Configuration Location |
|---|---|
| Host-specific or studio-wide defaults (License servers, Rez configs, studio paths) | Node's local `dcc.toml` `[env]` section (Section 5) |
| Job/Show specific (e.g. `OCIO`) | Job submission dialog Environment field (`KEY=VALUE` per line) |
| Managed via Rez packages | Submission dialog Environment field as `OCRUN_REZ` (and `OCRUN_REZ_TIME`) |
| Host system variables | `rqd.conf` `[UseHostEnvVar]` (Strictly minimal; see above) |

---

## 5. Invoking DCC Applications: `ocrun`

Job commands do not hardcode local DCC executable paths; they invoke them exclusively via `ocrun`:

```
ocrun <product> <version> <executable> [arguments...]

ocrun houdini 22.0.429 hython P:/proj/render.py
ocrun houdini 22.0.429 husk --make-output-path -f #IFRAME# -n 1 -o P:/proj/out.$F4.exr P:/proj/shot.usd
ocrun maya 2027 Render -r file -s #IFRAME# -e #IFRAME# P:/proj/scene.ma
ocrun nuke 17.0v1 Nuke17.0 -t P:/proj/render.py
```

`ocrun` looks up the product version directory from local `C:\opencue\dcc.toml`, executes the target binary, and forwards arguments verbatim.

- **Job commands remain uniform studio-wide; local `dcc.toml` files map to machine-specific installation paths** (edit sections labeled `EDIT` in [`node/dcc-windows.toml`](node/dcc-windows.toml)).
- Multiple versions coexist on the same node; each version occupies a line in `dcc.toml`.
- `#IFRAME#` is substituted with the frame index by Cuebot at dispatch time.
- If a version is unconfigured or the executable is missing, `ocrun` exits with code 127 and outputs diagnostic details to the frame log.
- Running `C:\opencue\venv\Scripts\ocrun.exe` with no arguments lists all configured DCC versions on that machine.
- `ocrun` ([`node/ocrun/`](node/ocrun/)) relies purely on the Python standard library, shared across Windows and Linux (Linux path: `/opt/opencue/dcc.toml`).

**Two mandatory prerequisites for frames to locate `ocrun`**:
- `rqd-start.bat` appends the virtualenv `Scripts` directory to `PATH`.
- `rqd.conf` configures `RQD_USE_PATH_ENV_VAR = 1` so child frames inherit RQD's `PATH`.

When killing frames, RQD issues `taskkill /T`, cleanly terminating the entire child process tree including DCC processes.
Reference: [`notes/sandbox/26`](../sandbox/26-ocrun-wrapper.md).

### License Servers Configured in `dcc.toml`

RQD **does not inherit user environment variables**. Configure studio license server variables in the `[env]` section of `dcc.toml`:

```toml
[env]
ADSKFLEX_LICENSE_FILE = '@license-server.studio.local'
foundry_LICENSE = '4101@license-server.studio.local'
solidangle_LICENSE = '5053@license-server.studio.local'
```

**Arnold strictly requires `solidangle_LICENSE`** (verified). If missing, Arnold halts each frame with a `license checkout error`. Interactive desktop Maya sessions succeed because the desktop user has this variable set, but RQD child processes do not inherit it.

Furthermore, when Arnold aborts due to missing licenses, `Render.exe` still returns exit code 0, causing OpenCue to falsely record frames as `SUCCEEDED` despite missing render outputs. `ocrun` intercepts and checks Maya output streams to trap these false successes; see below.
Reference: [`notes/sandbox/30`](../sandbox/30-arnold-licensing.md).

### Trapping False-Success Frames

Certain DCC applications exit with code 0 even after encountering fatal render errors. `ocrun` scans output streams line-by-line; if known fatal patterns appear, `ocrun` forces an exit code 1 and logs the failure cause (`[ocrun] failing the frame, the output reported: ...`):

| Product | Intercepted Error Patterns (Case-insensitive) |
|---|---|
| Maya | `aborting render because`, `license checkout error` |

Configured in `PRODUCT_FAIL_PATTERNS` inside [`node/ocrun/ocrun.py`](node/ocrun/ocrun.py). Ensure patterns strictly represent fatal conditions before adding new entries.

### Suppressing Crash Reporting Dialogs

When Maya crashes, Autodesk's error reporting modal (`cer_dialog.exe`) launches on the desktop: disrupting artists on workstations, and hanging indefinitely on headless dedicated nodes.

This occurs even after successful renders if `ALLUSERSPROFILE` is omitted, due to licensing module teardown faults. Resolve this via `[UseHostEnvVar]` in `rqd.conf` (Section 4).

`ocrun` injects `MAYA_DISABLE_CER=1` when executing Maya, but this suppresses only Maya's core crash dialog; licensing modules run an independent crash reporter unaffected by this flag.
Reference: [`notes/sandbox/28`](../sandbox/28-maya-crash-reporting.md), [`notes/sandbox/25` Section 5](../sandbox/25-maya-submission.md#5-issues-identified-during-manual-testing).

### Temp Directories

RQD passes `TMP` but omits `TEMP`. Nuke falls back to `C:\temp` if `TEMP` is missing, failing renders. `ocrun` automatically synthesizes `TEMP` matching `TMP`, and explicitly injects `NUKE_DISK_CACHE` into `TEMP\nuke`.
Reference: [`notes/sandbox/17` Scenario 7](../sandbox/17-troubleshooting.md#scenario-7-nuke-render-fails-with-unable-to-create-disk-cache).

### Executing via Rez (`OCRUN_REZ`)

When a job specifies `OCRUN_REZ` (a Rez package request) in its environment variables, `ocrun` executes:

```
rez-env <OCRUN_REZ> [--time <OCRUN_REZ_TIME>] --no-local -- <OpenCue venv python> -I -c <dump resolved environment>
```

`ocrun` resolves the environment from Rez, locates the binary from the resolved `PATH`, and **launches the process directly**. Bypassing shell wrappers during execution prevents character corruption of `$`, `%`, `&`, `^`, quotes, and spaces.

- DCC binary paths are governed by Rez packages, bypassing paths in `dcc.toml`.
- `OCRUN_REZ_TIME` captures the submission timestamp (epoch seconds), ensuring all frames resolve package versions deterministically.
- Both variables are populated in the job submission Environment field.

Node prerequisites for Rez:

| Requirement | Reason | Configuration Location |
|---|---|---|
| `rez-env` executable path | `rqd-start.bat` resets `PATH`; Rez CLI is absent from frame default `PATH` | `dcc.toml` under `[rez] rez_env` |
| Rez configuration (`REZ_CONFIG_FILE`, studio vars) | Studio variables are machine-level but not passed to child frames by RQD | `dcc.toml` under `[env]` |
| Rez package cache write permissions | Workstations run RQD under logged-in artist accounts, not farm service accounts | Ensure local cache directory allows artist write access |
| Pure ASCII in Rez configuration files (`rezconfig.py`) | Rez parses configs using system code page (cp950 on Chinese Windows); comments in non-ASCII fail `rez-env` launch | Use English comments only |
| Rez default shell accessible in `PATH` | `rez-env` invokes its configured `default_shell` | Included in `rqd-start.bat` for Windows PowerShell |

---

## 6. Dispatch Tags (`RQD_TAGS`)

```ini
# Dedicated Render Node
RQD_TAGS = general houdini22 houdini_22_0_429 maya2027 maya_2027 nuke17 nuke_17_0v1
# Artist Workstation
RQD_TAGS = desktop general houdini22 houdini_22_0_429 maya2027 maya_2027 nuke17 nuke_17_0v1
```

| Tag | Semantics |
|---|---|
| `desktop` | Artist workstation role; must lead the tag list to register under `local.desktop` |
| `general` | General compute pool |
| `houdini22` | Loose version binding: Any Houdini 22 release |
| `houdini_22_0_429` | Strict version binding: Exact build match |

- List only versions **physically installed** and mapped in `dcc.toml`.
- Restart RQD to apply tag changes. See [`04-operations.md` "Adding New DCC Versions"](04-operations.md#adding-new-dcc-versions).
- The `desktop` tag appears three times on workstations (in `RQD_TAGS`, via `OVERRIDE_IS_DESKTOP`, and on the allocation itself); this is normal.

### Node Tag String Length Limits

Cuebot concatenates all node tags (`RQD_TAGS`, `desktop`, `windows`, `rqdv-*`, hostname) into space-separated string `host.str_tags` in PostgreSQL. **Upstream OpenCue limits this field to 128 characters**; typical workstation tag lists easily reach 129 characters. When exceeded, nodes **silently fail to register**: RQD logs no errors, while Cuebot logs `value too long for type character varying(128)`.

The studio Flyway image includes an automatic migration ([`server/migrations/R__Studio_widen_host_tags.sql`](server/migrations/R__Studio_widen_host_tags.sql)) widening this limit to 4000 characters. **Always use the studio-provided Flyway image** (pre-configured in `server/env.example`).
Reference: [`notes/sandbox/32`](../sandbox/32-node-tag-limit.md).

- **Cuebot tag matching follows regex OR semantics**: If a layer requests multiple tags separated by `|`, matching any single tag permits dispatch. **Do not combine `general` with version tags in layers or services**, or jobs will dispatch to nodes lacking the target version.
- In production, **bind versions using Services** (bootstrapped via `OPENCUE_INIT_SERVICES`), rather than manual per-layer tags.
Reference: [`notes/sandbox/12`](../sandbox/12-real-dcc-rendering.md), [`notes/sandbox/21`](../sandbox/21-service-and-resource-model.md), [`notes/sandbox/17` Scenario 19](../sandbox/17-troubleshooting.md#scenario-19-job-dispatches-to-node-lacking-required-dcc-version).

---

## 7. Startup Script: `rqd-start.bat`

This script executes three crucial initialization steps:

1. **Locks working directory** to `C:\opencue`: Prevents Unix-style root paths from resolving against current working drives.
2. **Resets `PATH`, `TEMP`, and `TMP`**: Strips foreign user environments. Prevents third-party Unix toolchains (e.g. Git Bash) from shadowing Windows utilities (such as `timeout`). Restricts `PATH` strictly to Windows system directories and the virtualenv `Scripts` folder.
3. **Launches RQD, sleeps 20 seconds, then launches CueNIMBY**: Launching CueNIMBY before RQD finishes initialization causes `failed to lock host` exceptions.

Verify `NODE_ROLE` for the target machine:

| Value | Role |
|---|---|
| `set NODE_ROLE=workstation` | Artist workstation: Launches CueNIMBY |
| `set NODE_ROLE=render` | Dedicated render node: CueNIMBY disabled |

Reference: [`notes/sandbox/08`](../sandbox/08-windows-node-log.md), [`notes/sandbox/09`](../sandbox/09-nimby-and-hybrid-fleet.md), [`notes/sandbox/17` Scenarios 11, 13, 14](../sandbox/17-troubleshooting.md).

---

## 8. Dedicated Render Nodes vs. Workstations

The configuration template defaults to dedicated render nodes. Bold items below highlight changes required for workstations:

| Setting | Dedicated Render Node | Artist Workstation |
|---|---|---|
| `OVERRIDE_IS_DESKTOP` | `False` | **`True`** |
| `RQD_TAGS` Prefix | `general` | **`desktop`** |
| `NODE_ROLE` (`rqd-start.bat`) | `render` | **`workstation`** |
| CueNIMBY | Omit | **Required** ([`03-workstations.md`](03-workstations.md)) |
| Launch Method | Windows Service | **User Login** |
| Registered Allocation | `local.general` | `local.desktop` |

### Workstations: Must Launch at User Login (Not as Windows Services)

Both CueNIMBY system tray hooks and mapped drive letters are tied to interactive user login sessions. Windows Services execute in Session 0, isolated from user mapped drive letters.

Deployment options:
- IT configures a GPO scheduled task triggered "At log on", invoking `C:\opencue\rqd-start.bat`.
- Or place [`node/rqd-start-hidden.vbs`](node/rqd-start-hidden.vbs) into the user Startup directory (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`), launching RQD and CueNIMBY headless in the background without persistent cmd windows.

To terminate background processes, end `rqd.exe` and `cuenimby.exe` in Windows Task Manager.

### Dedicated Render Nodes: Windows Service and Drive Letter Considerations

Services start automatically on system boot without user login. However:

> Drive letters (`H:`, `P:`) are scoped to interactive logon sessions. Windows Services executing in Session 0 cannot see drive mappings created by users, while DCC scene files reference mapped drive letters.

Before deploying dedicated render nodes as services, execute a test job reading and writing to mapped drives under the service account. If mapped drives fail to resolve:
- Execute `net use` in the service startup wrapper under the service account.
- Or deploy persistent drive mappings for the service account via GPO.
- Or configure the node with auto-logon and launch RQD on login, identical to workstations.

Reference: [`notes/sandbox/11` Section 2](../sandbox/11-production-risks-and-todos.md#2-network-drive-letters-are-supported-with-one-exception).

---

## 9. Firewall Requirements

| Direction | Port | Purpose |
|---|---|---|
| Outbound | 8443 | gRPC connection to OpenCue server |
| **Inbound** | **8444** | **Cuebot callback to local RQD for frame dispatch** |
| Outbound | 445 | SMB shared storage access |

**Inbound port 8444 is the most frequent deployment oversight**, blocked by default on Windows Firewall. Symptoms of blocked port 8444: the node appears `UP` and healthy, but dispatched frames hang in `RUNNING` indefinitely with zero log generation.

```bat
netsh advfirewall firewall add rule name="OpenCue RQD" dir=in action=allow protocol=TCP localport=8444 remoteip=<OPENCUE_SERVER_IP>
```

Requires administrator privileges. Replace `<OPENCUE_SERVER_IP>` with the OpenCue server's IP (or a trusted subnet in CIDR form). RQD's port 8444 accepts unauthenticated gRPC calls, including launching frames and shutting down or rebooting the node, so only Cuebot should reach it.

---

## 10. Verification Checklist (Pilot Node)

Execute every check on the first pilot render node:

1. Node registers successfully with status `UP` under allocation `local.*`:

   ```bash
   cueadmin -lh
   ```

2. From the OpenCue server: Cuebot container resolves the node short hostname and reaches port 8444; see [`01-server.md` Section 7](01-server.md#7-post-deployment-verification).
3. Running `C:\opencue\venv\Scripts\ocrun.exe` displays configured DCC versions and paths.
4. Submit a real DCC test render job and confirm:
   - Job is dispatched to this node (Service and tag constraints match).
   - Frame completes with `SUCCEEDED`.
   - Frame logs load cleanly in CueGUI / CueWeb.
   - Network scene files are read and output images are written to shared storage.
   - Maya frames exit without popping up the Autodesk Error Report dialog.
   - Arnold frames **physically generate image files**, and logs contain no `license checkout error` warnings.

If any check fails, consult [`17-troubleshooting.md`](../sandbox/17-troubleshooting.md).

Once verified on the pilot machine, replicate to remaining nodes, customizing only:
- `OVERRIDE_HOSTNAME` and `RQD_TAGS` in `rqd.conf`
- Local paths in `dcc.toml`
- `NODE_ROLE` in `rqd-start.bat`
