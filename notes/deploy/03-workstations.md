# 03 — Artist Workstations (Client Setup)

Artist workstations operate as interactive client machines during working hours, and serve as render nodes after hours.
This guide addresses **client-side setup exclusively**. For render node configuration, follow [`02-render-nodes.md`](02-render-nodes.md), ensuring `OVERRIDE_IS_DESKTOP = True`, `RQD_TAGS` begins with `desktop`, and `NODE_ROLE=workstation` (these three parameters override the template's dedicated render node defaults).

---

## 1. Toolset Overview

| Tool | Purpose |
|---|---|
| **CueGUI** | Desktop monitoring GUI. Integrates Cuetopia (Job/Frame inspection) and CueCommander (Node monitoring). |
| **CueSubmit** | Desktop job submission interface. |
| **CueNIMBY** | System tray daemon that automatically locks the workstation during working hours to prevent job dispatching. |
| `cueadmin` / `cueman` | Command-line administration utilities (For TDs and Pipeline Admins). |
| CueWeb | Browser-based monitoring UI. Requires no client installation; access via `http://<server-ip>:3000`. |

For artists who only need to monitor job completion status, CueWeb is sufficient and desktop tool installation can be omitted.

**Important: "Autoload Mine" in CueWeb does not function in deployments without user authentication.** CueWeb evaluates "my jobs" based on the logged-in user profile. When operating in unauthenticated mode, all users resolve as `unknown`, preventing automatic retrieval of submitted jobs.
To inspect jobs, query by Show or Job name in the search bar above the job table on the CueWeb home page and click **Load**.
Reference: `getServerSession` in `cueweb/app/page.tsx` (verified).

---

## 2. Installation

Client utilities share the virtual environment created for the render node at `C:\opencue\venv`. From the OpenCue repository root, execute:

```bat
C:\opencue\venv\Scripts\python.exe -m pip install ./proto ./pycue ./pyoutline ./cueadmin ./cuegui ./cuesubmit ./cuenimby
```

This installs PySide6 automatically as a dependency.
Reference: [`notes/sandbox/10`](../sandbox/10-Windows用戶端工具.md).

---

## 3. Critical: Configuration Files Reside in Three Disparate Locations

| Component | Target Location | Template Source |
|---|---|---|
| CueGUI / CueSubmit / cueadmin (pycue) | `%APPDATA%\opencue\opencue.yaml` | [`client/opencue-client.yaml`](client/opencue-client.yaml) |
| CueNIMBY | `%USERPROFILE%\.config\opencue\cuenimby.json` | [`node/cuenimby-workstation.json`](node/cuenimby-workstation.json) |
| RQD | `C:\opencue\rqd.conf` | [`node/rqd-windows.conf`](node/rqd-windows.conf) |

CueNIMBY follows Linux conventions using `~/.config` without Windows path adaptation.

### Pre-create the CueNIMBY Directory

Fresh Windows user profiles lack `%USERPROFILE%\.config`. Because CueNIMBY fails to create missing parent directories automatically, **it crashes on initial boot**. Pre-create the directory during deployment:

```bat
mkdir "%USERPROFILE%\.config\opencue"
copy notes\deploy\node\cuenimby-workstation.json "%USERPROFILE%\.config\opencue\cuenimby.json"
```

Reference: [`notes/sandbox/05` Issue #10](../sandbox/05-可回饋上游的問題.md#10-cuenimby-在全新的-windows-機器上會因建立設定目錄失敗而無法啟動), [`notes/sandbox/10`](../sandbox/10-Windows用戶端工具.md).

---

## 4. Configuration

### `opencue.yaml`

```yaml
cuebot.facility_default: local

cuebot.facility:
    local:
        - opencue-server.studio.local:8443
```

Only the server endpoint requires customization. Ensure `facility_default` matches the node's `DEFAULT_FACILITY` (both `local`).

### `cuenimby.json`

Customize `cuebot_host` and `hostname` (the node's single-token short hostname, matching `OVERRIDE_HOSTNAME` in `rqd.conf`).

Configuring schedule rules:

```json
"schedule": {
  "monday": { "start": "09:00", "end": "18:00", "state": "disabled" },
  ...
}
```

This instructs CueNIMBY: "On Mondays from 09:00 to 18:00, lock this machine; allow rendering outside these hours."

**Always define locked windows without crossing midnight.** Writing cross-midnight active windows such as `18:00-09:00 available` causes CueNIMBY's calculation logic to invert completely, opening the node during work hours and locking it overnight.
Reference: [`notes/sandbox/09` Pitfall #11](../sandbox/09-NIMBY與混合機隊.md#坑-11跨午夜的排程時段完全失效), `cuenimby/scheduler.py:78-87`.

Days omitted from the schedule (e.g. weekends) **retain their previous state without toggling**. Because Friday transitions to available at 18:00, weekends remain open. However, if CueNIMBY is started from scratch on a weekend, it inherits the node's current status at startup.
Reference: `_check_schedule()` in `cuenimby/scheduler.py`.

### Workstation Lock Does Not Abort In-Flight Frames

When CueNIMBY locks the workstation at 09:00, **currently executing frames continue rendering until completion**; only incoming dispatching of new frames is halted (verified). A long-running frame will continue utilizing CPU/GPU during the artist's morning work hours.

The current studio policy is **not to abort in-flight frames automatically**. Artists or administrators may manually cancel tasks when needed:
- In CueGUI -> CueCommander, locate the host -> Right-click the active frame -> Kill.
- Or cancel active frames on that workstation via Python:

  ```python
  import opencue
  for proc in opencue.api.getProcs(host=["WS01"]):
      proc.kill()
  ```

Cancelled frames **return to the waiting queue and restart from scratch on another available node**; this does not count as a task failure or increment retry counters, although prior work on that frame is discarded.

Reference: [`notes/sandbox/24` Section 1](../sandbox/24-派工行為與監控.md#一工作站與專職機同時在線).

---

## 5. Verification

1. **CueGUI**: Run `C:\opencue\venv\Scripts\cuegui.exe`
   - Confirms job queues and host lists appear.
   - Double-clicking a frame opens its log viewer.
2. **CueSubmit**: Run `C:\opencue\venv\Scripts\cuesubmit.exe` and queue a basic test job.
   (Desktop CueSubmit verified via automation; web submission verified via CueWeb).
3. **CueNIMBY**: During working hours, `cueadmin -lh` reports the host as `LOCKED`; after 18:00, it transitions to `OPEN`.

Upon first launch, CueGUI generates configuration files under `%APPDATA%\.cuecommander\config.ini`; outputting two benign initial WARNING logs is normal.

---

## 6. Submitting Directly from Maya

### Architecture

The upstream Maya plugin (`cuesubmit/plugins/maya/`) executes its submission UI **inside Maya's embedded Python interpreter**, requiring OpenCue packages to be installed per Maya version (e.g. Maya 2027 runs Python 3.13, incompatible with the workstation's Python 3.11 virtualenv).
To eliminate multi-version maintenance overhead, a decoupled two-tier architecture is used ([`client/maya/`](client/maya/)):

```
Maya (Any version)                         C:\opencue\venv (Single central instance)
opencue_maya_launcher.py         -->      opencue_maya_submit.py
Gathers metadata using maya.cmds:          CueSubmit UI, pre-populated with:
  Scene path, cameras, frame ranges,        Scene path, cameras, frame range
  Maya version                              Command:  ocrun maya <version> Render
Requires zero OpenCue packages in Maya      Service:  Service possessing maya_<version> tag
```

- Jobs automatically inherit the exact Maya version and service from which they were launched, preventing artist selection errors.
- **Services are resolved inversely via version tags** (`maya_<version>`, e.g. 2027 -> `maya2027`), decoupled from arbitrary service naming.
  **Pre-flight checks verify that every service on the layer contains this tag**, rejecting submission if mismatched: preventing jobs from dispatching to nodes lacking that version if the generic upstream `maya` service (tagged `general desktop`) is mistakenly chosen. If missing, the dialog title alerts `no service has the maya_<version> tag`, prompting the admin to configure the service ([`04-operations.md` "Adding New DCC Versions"](04-operations.md#adding-new-dcc-versions)).
- The launcher launches asynchronously without blocking the interactive Maya session.
- Diagnostic logs for submission dialogs are recorded at `%LOCALAPPDATA%\OpenCue\submit.log`.

### Deployment

**Render Nodes**: Node `dcc.toml` must declare the target Maya version; see [`02-render-nodes.md` Section 5](02-render-nodes.md#5-invoking-dcc-applications-ocrun).
Dispatched command line: `ocrun maya <version> Render ...`.

**Server**: Each Maya version requires a corresponding service whose tags include `maya_<version>` (bootstrapped via `OPENCUE_INIT_SERVICES`).

**Pipeline Tool Share** (Network storage, single copy):
- Place the two files from [`client/maya/`](client/maya/) into `P:\pipeline\opencue\client\maya\` (path must not contain spaces).
- Tool updates are deployed here. Submission dialogs re-read files on each launch; the in-Maya launcher caches into memory on import, requiring Maya restarts to reload modifications. Maya render frames invoke `Render` directly and never read this network folder, permitting safe in-place updates (unlike Houdini; see Section 7).

**Workstations**:
1. Deploy the Maya module definition [`client/maya/opencue.mod`](client/maya/opencue.mod) to `%USERPROFILE%\Documents\maya\modules\` (loaded across all Maya versions), or studio-wide `MAYA_MODULE_PATH`. This appends the tool directory to Maya's `PYTHONPATH`.

   **Do not use `Maya.env` to configure `PYTHONPATH`**: If `PYTHONPATH` is already defined in the system environment, Maya ignores definitions inside `Maya.env`, causing tool imports to fail (verified). Module files do not suffer from this limitation.
2. Create a shelf button with Python code:

   ```python
   import opencue_maya_launcher; opencue_maya_launcher.submit()
   ```

The default Show is read from environment variable `PROJECT`.

### Pre-submission Requirements and Constraints

- **Project paths must not contain spaces.** CueSubmit tokenizes command strings by whitespace, rendering quoting ineffective ([`notes/sandbox/17` Scenario 24](../sandbox/17-故障排查與常見疏失速查.md#場景-24路徑含空白時-frame-失敗)). Studio pipelines must enforce space-free project directory paths.
- **Output directories are governed by the Maya project workspace.** The command line does not inject output directory flags; scenes must reside within a project containing a valid `workspace.mel`, otherwise render outputs fall back to local `Documents\maya\projects\default\images` on the render node.
- **Workstation environment variables do not transfer to frames.** Pass required settings via the submission dialog Environment field; see [`02-render-nodes.md` "Precedence of Frame Environment Variables"](02-render-nodes.md#precedence-of-frame-environment-variables).
- **Do not select the built-in `maya` service**, which is tagged `general | desktop` and breaks version binding.
- **A single camera must be selected.** If left empty, no camera flag is passed and Maya renders all renderable cameras in the scene. When only one renderable camera exists, it is pre-selected. (Upstream CueSubmit outputs `-cam [None]` when unselected; this tool fixes this issue; see [`notes/sandbox/25` Section 5](../sandbox/25-Maya內投遞.md#五人工測試中發現的問題)).

### Verification Status

- Verified end-to-end under Maya 2027: launcher executes in pure `mayapy` without OpenCue packages; submission dialog correctly populates services, command lines, and frame ranges; 10 frames rendered successfully.
- Migrated to `ocrun` with programmatic submission: 2 frames completed successfully ([`notes/sandbox/26`](../sandbox/26-ocrun取代wrapper.md)).
- Interactive validation via Maya UI: resolved and patched `-cam [None]` bug; re-submission of 3 frames succeeded.
- Re-tested with `ocrun` and version tag lookup via Maya UI: command lines and services resolved correctly. Fixed Arnold license failure behavior ([`02-render-nodes.md` Section 5](02-render-nodes.md#5-invoking-dcc-applications-ocrun), [`notes/sandbox/30`](../sandbox/30-Arnold授權與假成功.md)).

Reference: [`notes/sandbox/25`](../sandbox/25-Maya內投遞.md).

---

## 7. Submitting Directly from Houdini

### Architecture

Employs the same decoupled two-tier architecture as Maya, supplemented by a dedicated frame render script executed on render nodes ([`client/houdini/`](client/houdini/)):

| File | Execution Environment | Role |
|---|---|---|
| `opencue_houdini_launcher.py` | Inside Houdini (Any version) | Uses `hou` to inspect hip files, renderable nodes, frame ranges, and Houdini version |
| `opencue_houdini_submit.py` | `C:\opencue\venv` | CueSubmit submission UI: Node selection, frame ranges, simulation chunk toggles |
| `opencue_houdini_render.py` | Node's `hython` | Opens hip file, executes target node frames; exports USD if in husk mode |
| `opencue_husk_submit.py` (`.bat`) | `C:\opencue\venv` | Submits standalone USD files via husk without launching Houdini |

Dispatched command line:

```
ocrun houdini <version> hython P:/pipeline/opencue/releases/<tool_version>/client/houdini/opencue_houdini_render.py <hip> <node> #FRAMESPEC#
```

- **Supported Nodes**: All ROPs (`hou.RopNode`, e.g. `/out`, SOP ROP Geometry, LOP USD Render ROP), plus whitelisted non-ROP nodes: File Cache SOP (`filecache::2.0`) and Karma LOP (`karma`). Whitelist defined in `_OTHER_RENDER_TYPES` inside `opencue_houdini_launcher.py`.
- Selecting a node automatically populates its frame range and adopts the node path as the layer name. The currently selected node in Houdini is pre-selected upon launch.
- **Service Resolution**: Resolved inversely via version tag `houdini_<version>` (e.g. 22.0.429 -> `houdini2204`). Pre-flight validation confirms service tags match before queuing.
- Submission dialog errors and logs are recorded in `%LOCALAPPDATA%\OpenCue\submit.log`.
- Submits one node per job. For node dependencies (e.g. cache before render), submit separate jobs or configure dependencies in CueGUI.

### Simulations Must Run as Single-Chunk Tasks

The submission dialog provides a **Whole range as one task (simulation)** toggle:

| Toggle | Execution Behavior | Intended Usage |
|---|---|---|
| Disabled | One task per frame, computed in parallel | Standard renders, format-converting File Caches |
| Enabled | Sequential execution of entire frame range in one single task (`chunk = frame_count`) | Dynamic simulations |

Automatically enabled when nodes have **Cache Simulation** (File Cache) or **Initialize Simulation OPs** (ROP) enabled.
**This default is heuristic and not guaranteed**: DOP networks, TOP nodes, and third-party solvers may not be auto-detected; **artists must verify this toggle before submission**.

If a simulation is erroneously split into parallel tasks, output frames remain correct (solvers re-sim from frame 1), but the N-th task must calculate N frames, incurring quadratic $O(n^2/2)$ redundant compute overhead.

### Rendering USD Scenes via Husk

Karma LOP and USD Render ROP (`usdrender` in `/out`, `usdrender_rop` in LOP) support the **Render with husk (export USD first)** option, splitting the job into two dependent layers:

| Layer | Command | Task Breakdown |
|---|---|---|
| `<layer>_usd` | `ocrun houdini <ver> hython opencue_houdini_render.py --export-usd <usd> <hip> <node> #FRAMESPEC#` | Single task exporting the entire frame range to a **single USD stage file** |
| `<layer>` | `ocrun houdini <ver> husk --make-output-path --frame #IFRAME# --frame-count 1 [args] <usd>` | One task per frame, executing sequentially after `<layer>_usd` succeeds |

- Husk render tasks bypass hip file loading, reading pure USD data for fast initialization.
- **USD File**: Defaults to `<hip_dir>/usd/<hip_name>.<node_path_with_underscores>.usd` (e.g. `shot.stage_karma1.usd`) on shared storage. Re-submitting the same node overwrites this file; rename before re-submission if prior jobs are active.
- Export uses USD ROP default flattening (Flatten Implicit Layers).
- Output paths, cameras, and render settings are driven by render settings prims inside the USD. Flags forwarded from Houdini nodes to husk:

  | Node | Forwarded Husk Arguments |
  |---|---|
  | Karma LOP | Engine: CPU -> `--renderer BRAY_HdKarma`, XPU -> `--renderer BRAY_HdKarmaXPU` |
  | USD Render ROP | Render Delegate (`--renderer`), Render Settings (`--settings`), Override Camera (`--camera`), Override Resolution (`--res` or `--res-scale`) |

  Although USD encodes the Karma engine, husk defaults to Karma CPU if `--renderer` is omitted; explicit forwarding is mandatory.
- If USD Render ROP enables **Output Picture** overrides, submission is rejected (overrides are unencoded in USD; husk would render to default paths). Enabling **Render Existing File** is also rejected (use the standalone submission tool below instead).
- Chunk size is locked to 1; simulation chunking is disabled in husk mode.

**Submitting Pre-existing USD Files Standalone**: `opencue_husk_submit.py` executes inside `C:\opencue\venv` from the Houdini release folder. Drag a USD file onto `opencue_husk_submit.bat`, or invoke directly:

```
C:\opencue\venv\Scripts\python.exe P:\pipeline\opencue\releases\<tool_version>\client\houdini\opencue_husk_submit.py [scene.usd]
```

Launching without arguments opens a blank dialog.
- **Houdini Version**: Lists versions mapped to `houdini_<version>` service tags.
- **Renderer**: Select Karma CPU / Karma XPU / Unspecified. (The virtualenv lacks USD bindings and cannot read engine prims; selecting incorrectly renders XPU scenes on CPU).
- Optional override fields (Leave blank to use stage defaults):
  - Render Settings: `--settings` (e.g. `/Render/rendersettings`)
  - Camera: `--camera` (e.g. `/cameras/shotCam`)
  - Output: `--output` (e.g. `P:/projects/show/render/shot.$F4.exr`, using husk `$F4` syntax)
  - Resolution: `--res` (e.g. `1920x1080` or `1920 1080`)
  - Extra husk arguments: Forward custom flags, e.g. `--res-scale 50`
- Both husk workflows support Rez execution by specifying `OCRUN_REZ` in Environment; see [`02-render-nodes.md` "Executing via Rez"](02-render-nodes.md#executing-via-rez-ocrun_rez).

### Deployment

**Render Nodes**: Node `dcc.toml` must declare the Houdini version; see [`02-render-nodes.md` Section 5](02-render-nodes.md#5-invoking-dcc-applications-ocrun). Nodes require access to drive `P:`.

**Server**: Configure corresponding services with tags including `houdini_<version>` (`OPENCUE_INIT_SERVICES`).

**Pipeline Tool Share** (Network storage):
- Place the entire [`client/houdini/`](client/houdini/) directory into a **versioned release directory**: `P:\pipeline\opencue\releases\<version>\client\houdini\` (e.g. `2026.09.25`; spaces prohibited).
- The execution path is resolved relative to the submitter tool location, meaning **jobs permanently bind to the tool release version active at submission time**. Subsequent releases do not mutate running or queued jobs.
- **Release directories must remain immutable post-release**. Updates are published into new versioned directories; see [`04-operations.md` "Pipeline Tool Distribution"](04-operations.md#8-pipeline-tool-distribution).

**Workstations**:
1. Deploy package definition [`client/houdini/opencue.json`](client/houdini/opencue.json) (pointing to the target release directory) to studio `HOUDINI_PACKAGE_DIR` or `%USERPROFILE%\Documents\houdini<ver>\packages\`. This injects the tool directory into `PYTHONPATH` and `HOUDINI_PATH` (the latter allowing TOP networks to discover the OpenCue scheduler).
2. Create a shelf button with Python code:

   ```python
   import opencue_houdini_launcher; opencue_houdini_launcher.submit()
   ```

### Pre-submission Requirements and Constraints

- **Project paths must not contain spaces.**
- Save hip files prior to submission; prompt confirms unsaved changes.
- Frame output paths, cameras, and settings default strictly to node parameters inside the hip file.
- Workstation environment variables do not transfer to frames; configure via the Environment field.

### Verification Status

- Verified under hython: metadata gathering for File Cache (two types), ROP Geometry, Karma LOP, Mantra ROP; simulation heuristics verified.
- Programmatic submission of 4 node types completed successfully; 10-frame simulation chunk processed in a single sequential task.
- Package installation verified via hython import tests.
- Interactive submission validated via Houdini UI across Houdini 21.0.729 and 22.0.429.
- Husk mode verified under Houdini 22.0.429: Karma LOP (CPU) and `/out` USD Render ROP (XPU with explicit render settings) exported USD and rendered sequential frames cleanly.
- Standalone husk submission verified with existing USD files (Karma XPU).
- Rez resolution verified via `OCRUN_REZ` in Environment fields.

Reference: [`notes/sandbox/27`](../sandbox/27-Houdini內投遞.md).

### PDG (TOP Networks)

Installing the package above exposes the **`pdg_opencuescheduler`** node, configurable as the scheduler for TOP networks.

- **Cooks one node per invocation**: If upstream nodes are cooked, all work items on this node batch into an OpenCue job (one work item per frame). If upstream nodes are unbaked, upstream and downstream nodes partition into separate jobs.
- **Keep Houdini open until cook finishes**: Work item status updates (output files, attributes) stream back to the originating Houdini session.
- **Working Directory** (Scheduler Working Directory, default `$HIP`) must reside on shared storage accessible by render nodes.
- **Nodes must communicate back to the workstation**: Work items ping the workstation callback server. Define Callback Port Min/Max ranges on the scheduler and allow this range in workstation firewalls.
- Configure Python Script nodes to **Cook (Out-of-Process)**; In-Process cooks run locally inside Houdini.
- ROP Fetch / ROP Geometry default **Evaluate Using to Single Frame**. Toggle to Frame Range for distributed rendering; ROP Node Configuration batches entire frame ranges into single work items (single frame in OpenCue).
- When Working Directory differs from `$HIP`, PDG duplicates the hip file to the working directory; nodes evaluate the **snapshot copy at cook time**.
- Show defaults to `$PROJECT`; service resolution matches the standard submission tool.
- Failed work items do not auto-retry; failure evaluation is handled by PDG.
- Work item **Output Log** views frame logs identical to CueWeb.

Verification status: Verified locally via hython for 300 work items (single job), downstream cooks, partial failures, killed frames, and cook cancellation across Houdini 21 and 22. Interactive UI cook verified across dependent nodes.
**Cross-machine callback connectivity remains unverified.**
Reference: [`notes/sandbox/34`](../sandbox/34-Houdini-PDG-scheduler設計.md).

---

## 8. Submitting Directly from Nuke

### Architecture

Follows the decoupled two-tier architecture ([`client/nuke/`](client/nuke/)):

| File | Execution Environment | Role |
|---|---|---|
| `opencue_nuke_launcher.py` | Inside Nuke (Any version) | Gathers script path, active Write nodes (including within Groups), frame ranges, and Nuke version |
| `opencue_nuke_submit.py` | `C:\opencue\venv` | CueSubmit UI: Write node selection, frame ranges, chunk sizing |
| `menu.py` | Inside Nuke | Registers menu item: OpenCue > Submit to OpenCue |

Dispatched command line:

```
ocrun nuke <version> Nuke<major.minor> -F #FRAMESPEC# [-X Write1,Write2] -x <script.nk>
```

- **Bypasses upstream CueSubmit Nuke implementation**: Upstream submits `-X [All]` when unselected, `-X a, b` when multi-selected, and hardcodes `-F #IFRAME#` (rendering only the first frame if chunk > 1). We utilize the Shell job type to assemble custom commands.
- All Write nodes are selected by default, omitting `-X` to render all enabled Write nodes.
- Workstation environment variables do not transfer to frames; configure via Environment.
- **Chunk sizes greater than 1 are supported**: `#FRAMESPEC#` expands to the chunk frame sequence (e.g. `1-5x2`), computing all chunk frames in a single Nuke process to minimize script initialization overhead.
- Service resolved inversely via version tag `nuke_<version>` (e.g. 17.0v1 -> `nuke17`).
- Diagnostic logs are written to `%LOCALAPPDATA%\OpenCue\submit.log`.
- Non-blocking execution allows interactive Nuke work to continue.
- Nuke exits with non-zero codes on errors (e.g. invalid Write names, nonexistent output directories exit code 1), requiring no output pattern inspection by `ocrun`.

### Deployment

**Render Nodes**: Node `dcc.toml` must declare the Nuke version; see [`02-render-nodes.md` Section 5](02-render-nodes.md#5-invoking-dcc-applications-ocrun).

**Server**: Configure corresponding services with tags including `nuke_<version>` (`OPENCUE_INIT_SERVICES`).

**Pipeline Tool Share**: Deploy files from [`client/nuke/`](client/nuke/) to `P:\pipeline\opencue\client\nuke\`. Safe to overwrite in place.

**Workstations**: Append this directory to `NUKE_PATH` (environment variable or `nuke.pluginAddPath()` in studio `init.py`). Nuke loads `menu.py` on startup, creating the **OpenCue > Submit to OpenCue** menu entry.

### Verification Status

- Verified under Nuke terminal mode: metadata gathering for multiple Write nodes (including nested `Comp.WriteB`).
- Render farm tests: `-F 1-5x2` (chunk 3) rendered frames 1, 3, 5; `-F 1-2` and `-F 3-4` (chunk 2) rendered 2 frames each; comma-separated `-X` flags functioned properly.
- Programmatic submission for all Write nodes vs. selective Write nodes completed successfully.
- Interactive Nuke UI submission validated; unsaved script prompts verified.
- Verified menu integration via `NUKE_PATH`.

Reference: [`notes/sandbox/31`](../sandbox/31-Nuke內投遞.md).

---

## 9. Pre-submission Checklist

Guidelines for TDs writing custom submission scripts or pipeline integrations:

| Item | Best Practice | Reference |
|---|---|---|
| DCC Version Pinning | Use **Services** (e.g. `houdini2204`); avoid manual per-layer tags | [`sandbox/21`](../sandbox/21-Service與資源模型.md) |
| Command Tokens | Pass command arguments as a **list**, never a raw string, to prevent backslash stripping on Windows | [`sandbox/17` Scenario 6](../sandbox/17-故障排查與常見疏失速查.md#場景-6dcc-算圖報找不到檔案反斜線路徑被吃掉) |
| Paths Containing Spaces | Lists **do not protect spaces**; wrap scene files and output paths in explicit double quotes | [`sandbox/17` Scenario 24](../sandbox/17-故障排查與常見疏失速查.md#場景-24路徑含空白時-frame-失敗) |
| DCC Invocation | Always execute via `ocrun <product> <version> <executable>`; avoid local absolute paths | [`02-render-nodes.md` Section 5](02-render-nodes.md#5-invoking-dcc-applications-ocrun) |
| Operating System | Set `os="Windows"` explicitly to govern dispatch targeting and log path resolution | [`sandbox/17` Scenario 21](../sandbox/17-故障排查與常見疏失速查.md#場景-21混合作業系統農場中job-成功但-log-找不到) |
| Layer Name Length | Must contain at least 3 characters | [`sandbox/21`](../sandbox/21-Service與資源模型.md) |
| Scene File Integrity | Frames evaluate the **live scene file on disk at render time**, not a submission snapshot. Overwriting a scene during rendering affects subsequent frames. Save new versions before queuing | Design Decision (Below) |
| Environment Variables | Workstation environments do not transfer to frames. Supply variables in the **Environment** field (`KEY=VALUE` per line; lines starting with `#` are skipped). Environment settings **override `dcc.toml` `[env]` defaults**. For Rez, populate `OCRUN_REZ` | [`02-render-nodes.md` Section 5](02-render-nodes.md#license-servers-configured-in-dcctoml) |

Reference examples in [`notes/sandbox/lab/submit_dcc.py`](../sandbox/lab/submit_dcc.py), [`submit_houdini_twostage.py`](../sandbox/lab/submit_houdini_twostage.py).

### No Scene Snapshotting (Design Decision)

Submission tools point directly to the active scene file on disk without making redundant copies. This covers typical production workflows cleanly. If snapshotting is required later, it will be added as an optional, opt-in feature.

### CueWeb Submission Constraints

CueWeb supports web-based job submission but exhibits three distinct limitations: no tag selection, no OS selection, and a fixed 256 MB default memory limit. Use desktop utilities or pipeline scripts for production submissions.
Reference: [`notes/sandbox/13`](../sandbox/13-CueWeb與RESTGateway.md).
