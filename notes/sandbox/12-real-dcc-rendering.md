# 12 — Real DCC Rendering Benchmarks (Houdini / Maya / Nuke)

Prior sandbox tests evaluated `/bin/sleep` tasks or lightweight Python routines. This session executes full render pipelines using **commercial DCC applications**, validating key architectural assumptions.

> DCC wrapper scripts (`.bat`) referenced in this note were subsequently replaced by `ocrun`. See [`26-ocrun-wrapper.md`](26-ocrun-wrapper.md).
> Links below point to wrappers prior to retirement.

## Local DCC Environment

DCC installations on this test machine were located on **Drive D:** rather than default program directories.

| Application | Path | Executables |
|---|---|---|
| Houdini 22.0.429 (Also 21.0.700, 21.0.729, 22.0.368) | `D:\programs\Side Effects Software\` | `hython.exe`, `husk.exe`, `hbatch.exe` |
| Maya 2027 | `D:\programs\Autodesk\Maya2027\bin\` | `Render.exe` |
| Nuke 17.0v1 (Also 16.0v8) | `D:\programs\Nuke17.0v1\` | `Nuke17.0.exe` |
| Blender 4.4 / 4.5 / 5.0 | `D:\programs\Blender Foundation\` | `blender.exe` absent; directory structures only |

Houdini License: `licenseCategoryType.Commercial`, Python 3.13.10.

## Renderer Compatibility Evaluation

| Renderer | Result | Notes |
|---|---|---|
| **Karma** (`karma` ROP) | Succeeded (5.8s / 215 KB EXR) | In-process execution; delegates internally to `rop_usdrender` |
| **husk** (Standalone USD Render) | Succeeded (Exit 0 / 916 KB EXR) | Requires scene pre-exported via `usd_rop` |
| **OpenGL ROP** | Succeeded (5.6 KB PNG) | Viewport render; optimal for fast sanity checks |
| **Mantra** (`ifd` ROP) | Failed (License error) | `No licenses could be found to run this application` |

**Mantra requires dedicated render tokens** (spawns separate `mantra` processes requesting render licenses), which standard Houdini interactive Commercial licenses do not supply. Karma runs in-process inside `hython`, reusing the existing token.

**Conclusion**: Studio pipeline focuses primarily on Karma and husk.

## Architecture: Multi-Version DCCs Across Heterogeneous Paths

Production environments face two primary conditions:
- DCC installation paths vary across different render nodes.
- Multiple versions coexist on the same node (e.g., Houdini 21 alongside Houdini 22).
- Different projects require specific DCC releases.

Therefore, **render commands must not hardcode absolute installation paths**. A three-tier design resolves this:

### Tier 1: Consistent Wrapper Scripts Across Nodes

```
C:\opencue\bin\hython-22.0.429.bat
C:\opencue\bin\hython-21.0.729.bat
C:\opencue\bin\Render-2027.bat
```

Script locations are uniform across nodes, while **internal contents resolve to machine-specific installation paths**:

```bat
set HFS=D:\programs\Side Effects Software\Houdini 22.0.429
set HB=%HFS%\bin
if not exist "%HB%\hython.exe" (
    echo [wrapper] hython not found at "%HB%\hython.exe" 1>&2
    exit /b 127
)
"%HB%\hython.exe" %*
exit /b %ERRORLEVEL%
```

Template available at [`notes/deploy/node/hython-22.0.429.bat`](https://github.com/chordee/OpenCue/blob/9229923c/notes/deploy/node/hython-22.0.429.bat). **Must be pure ASCII** (see [`09` Pitfall #13](09-nimby-and-hybrid-fleet.md#pitfall-13-batch-files-must-be-pure-ascii)).

Nodes only maintain wrappers for versions physically installed. Missing executables return explicit exit code 127 rather than failing silently.

#### Cross-Platform Considerations: Command Paths Lack Automated Mapping

While frame log roots provide per-OS mappings, **command strings do not**:

| Entity | Storage | Per-OS Mapping Available |
|---|---|---|
| Frame log root | Cuebot configuration | **Yes** — `log.frame-log-root.<OS>` |
| Layer command string | `layer.str_cmd` (Single column) | **No** |
| Target OS | `job.str_os` (Job level, not layer) | — |

Because `layer` stores a single command string, **one job targets one operating system**. Cross-platform workflows require submitting separate jobs with target `os` declarations matching that platform's path format:

| Platform | Recommended Wrapper Path |
|---|---|
| Windows | `C:\opencue\bin\hython-22.0.429.bat` |
| Linux | `/opt/opencue/bin/hython-22.0.429.sh` |

### Tier 2: Render Nodes Advertise Installed Versions via Tags

`rqd.conf`:

```ini
RQD_TAGS = general houdini22 houdini_22_0_429
```

Tags are space-delimited (`rqmachine.py:599`). Two naming granularities are recommended:

| Format | Purpose |
|---|---|
| `houdini22` | Project allows any compatible Houdini 22 dot-release |
| `houdini_22_0_429` | Project enforces exact build version |

Verified registration:

```
str_tag          | str_tag_type
general          | HARDWARE
houdini22        | HARDWARE
houdini_22_0_429 | HARDWARE
desktop          | ALLOC
windows          | HARDWARE
```

### Tier 3: Jobs Request Versions via Layer Tags

```python
layer = Shell(
    "houdini_render",
    command=[wrapper, script],          # List of arguments, not string
    range="1-4",
    tags=["houdini_22_0_429"],          # Version tag only
    env={"OPENCUE_RENDER_OUT": out, "OPENCUE_RENDERER": "karma"},
)
```

#### Crucial: Tag Matching Evaluates Regex "OR", Not "AND"

Initial assumptions that `tags=["general", "houdini_22_0_429"]` would require hosts to satisfy both conditions were **proven false by empirical testing**.

Cuebot's dispatch SQL (`DispatchQuery.java:296, 363`):

```sql
AND host.str_tags ~* ('(?x)' || layer.str_tags || '\y')
```

`~*` performs regex matching. Layer tags concatenated with ` | ` (e.g., `general | util`) become a regex pattern where `|` denotes OR.

If a host contains **any single matching tag**, the layer matches. Adding `general` causes any general pool worker to match, **rendering DCC version locking ineffective**.

#### Empirical Evidence

Two nodes configured with distinct tags:

```
LAPTOP-ULJICLO8   general houdini22 houdini_22_0_429 maya2027 nuke17 ...
render02          general houdini21 houdini_21_0_729
```

**Round 1 (Incorrect: tags included `general`)**:

| Layer Tags | Expected Node | Actual Dispatch |
|---|---|---|
| `general \| houdini_21_0_729` | render02 | **LAPTOP-ULJICLO8** |
| `general \| houdini_22_0_429` | LAPTOP | LAPTOP-ULJICLO8 |
| `general \| houdini_99_nonexistent` | WAITING | **LAPTOP-ULJICLO8** |

All jobs routed to the same host; even completely nonexistent version requests dispatched improperly because of `general`.

**Round 2 (Correct: version tags only)**:

| Layer Tags | Outcome | Assigned Host |
|---|---|---|
| `houdini_21_0_729` | SUCCEEDED | **render02** |
| `houdini_22_0_429` | SUCCEEDED | **LAPTOP-ULJICLO8** |
| `houdini_99_nonexistent` | **WAITING** | — |

Version locking functions properly when `general` is omitted.

#### Preferred Alternative: Manage Tags and Resources via Services

Defining tags and hardware allocations directly on **Services** centralizes resource definitions:

```python
Shell("svc_render", command=[...], range="1-2", service="houdini2204")
```

Submissions avoid specifying manual tags or memory limits, and **CueWeb provides dropdown Service selectors**. See [`21-service-and-resource-model.md`](21-service-and-resource-model.md).

#### Practical Recommendations

- When locking software versions, **declare version tags only**. Do not mix with `general`.
- Tag matching OR semantics can be intentionally used for multi-version fallback: `tags=["houdini_22_0_429", "houdini_22_0_368"]`.
- Avoid special regex characters (`.`, `*`, `+`) in tag names; use alphanumeric strings and underscores.
- Beware substring collisions (e.g., `houdini2` matching `houdini22`).

### Why Commands Must Be Passed as Lists

In `pyoutline/outline/io.py:53`:

```python
if not isinstance(cmd, (tuple, list, set)):
    cmd = shlex.split(str(cmd))
```

Passing a string invokes `shlex.split()`, which treats Windows backslashes as POSIX escape characters and destroys file paths. Passing lists avoids `shlex` processing.

Submission script available at [`notes/sandbox/lab/submit_houdini.py`](lab/submit_houdini.py).

## Render Script Architecture

In [`notes/sandbox/lab/houdini_render_frame.py`](lab/houdini_render_frame.py):
- Reads target frame number from environment variable **`CUE_IFRAME`** injected by RQD.
- Renderer selected via `OPENCUE_RENDERER` (`karma` / `opengl`).
- Output directory configured via `OPENCUE_RENDER_OUT`.
- Explicitly verifies output existence on disk upon completion, exiting with `sys.exit(1)` if missing to ensure Cuebot registers render failures properly.

## Empirical Benchmark Results

```bash
python submit_houdini.py --frames 1-4
```

Cuebot perspective:

```
                       job                        |      str_name       | str_state | exit
--------------------------------------------------+---------------------+-----------+------
 testing-testshot-chordee_houdini_render_22_0_429 | 0001-houdini_render | SUCCEEDED |  0
 testing-testshot-chordee_houdini_render_22_0_429 | 0002-houdini_render | SUCCEEDED |  0
 testing-testshot-chordee_houdini_render_22_0_429 | 0003-houdini_render | SUCCEEDED |  0
 testing-testshot-chordee_houdini_render_22_0_429 | 0004-houdini_render | SUCCEEDED |  0
```

Disk outputs (file size increases across frames as torus rotates into frame):

```
test.0001.exr  250342 bytes
test.0002.exr  313549 bytes
test.0003.exr  370631 bytes
test.0004.exr  419045 bytes
```

Frame logs confirmed environment variables:

```
Houdini      : 22.0.429
License      : licenseCategoryType.Commercial
Frame        : 1
CUE_JOB      : testing-testshot-chordee_houdini_render_22_0_429
Renderer     : karma
```

**End-to-End Pipeline Verified**: Cuebot on Linux selects Windows node by tag → wrapper resolves Houdini → executes Karma render → writes EXR output → reports SUCCEEDED.

## Verification Note: CueNIMBY Blocks Daytime Testing

Testing at 11:47 fell within the scheduled `09:00-18:00 disabled` window, locking the host and holding jobs in WAITING — validating expected NIMBY behavior.

To test during business hours, temporarily halt CueNIMBY and unlock the host:

```powershell
Stop-Process -Name cuenimby -Force
```
```bash
cueadmin -force -unlock -host <node_name>
```

---

# Sequel: Maya and Nuke Verification

## Summary Results

All three DCC packages executed headless farm renders cleanly:

| Application | Execution | Outcome | Memory |
|---|---|---|---|
| Houdini 22.0.429 | `hython.exe` + Karma ROP | Succeeded (4/4 frames) | ~1.1 GB |
| Maya 2027 | `Render.exe -r sw` | Succeeded (3/3 frames) | ~530 MB |
| Nuke 17.0v1 | `Nuke17.0.exe -t` | Succeeded (3/3 frames, with fixed env) | 0 (Short frames) |

Memory tracking reports actual usage under sustained workloads:

```
 job                           | frame               | state     | exit | mem_kb
-------------------------------+---------------------+-----------+------+---------
 ..._houdini_render_22_0_429   | 0001-houdini_render | SUCCEEDED |    0 | 1145644
 ..._maya_render_2027          | 0001-maya_render    | SUCCEEDED |    0 |  530644
 ..._nuke_render_17_0v1        | 0001-nuke_render    | SUCCEEDED |    0 |       0
```

Nuke reported 0 because frames finished in 0.05s, finishing inside the 10-second sampling window.

## Maya Rendering Details

Scenes generated via `mayapy.exe`; renders executed via `Render.exe`:

```bat
Render.exe -r sw -s %CUE_IFRAME% -e %CUE_IFRAME% -rd "%OUTDIR%" "%SCENE%"
```

Maya Software (`-r sw`) requires no external licensing tokens. Single-frame renders averaged ~18.5 seconds, primarily driven by Maya startup initialization overhead. Production workflows should leverage persistent batch runners or multi-frame task chunking to amortize startup latency.

## Nuke Rendering Details

```bat
Nuke17.0.exe -t <python_script.py>
```

### Pitfall #14: Missing Environment Variables in Subprocess

Initial Nuke farm renders failed completely despite succeeding when invoked manually:

```
ERROR: Unable to create disk cache at C:/temp/nuke.
Please modify the value of DiskCachePath in the preferences17.0.nk file
```

**Root Cause**: RQD passes `TMP` to the frame environment, **but omits `TEMP`**.

Windows applications frequently default to `TEMP`. Missing `TEMP`, Nuke fell back to hardcoded `C:/temp`, which did not exist on the node.

**Takeaway**: DCC applications require specific cache, scratch, and licensing environment variables that RQD does not automatically inherit. **Wrapper scripts must explicitly configure application environment variables.**

Wrapper fix ([`notes/deploy/node/nuke-17.0v1.bat`](https://github.com/chordee/OpenCue/blob/9229923c/notes/deploy/node/nuke-17.0v1.bat)):

```bat
if "%NUKE_DISK_CACHE%"=="" set NUKE_DISK_CACHE=C:\opencue\tmp\nuke
if not exist "%NUKE_DISK_CACHE%" mkdir "%NUKE_DISK_CACHE%"
```

Retried frames completed with 3/3 SUCCEEDED.

### Pitfall #15: Persistent PATH Contamination in Runtime Processes

Checking Nuke frame logs revealed:

```
PATH=C:\Program Files\Git\mingw64\bin;C:\Program Files\Git\usr\bin;...
```

Although system-wide persistent PATH was clean, the interactive session that launched RQD carried contaminated environment variables.

Fix ([`notes/deploy/node/rqd-start.bat`](../deploy/node/rqd-start.bat)): Explicitly declare clean PATH entries:

```bat
set PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem
set PATH=%PATH%;%SystemRoot%\System32\WindowsPowerShell\v1.0

if not exist "%OPENCUE_HOME%\tmp" mkdir "%OPENCUE_HOME%\tmp"
set TEMP=%OPENCUE_HOME%\tmp
set TMP=%OPENCUE_HOME%\tmp
```

## Production DCC Wrapper Inventory

Standardized location on all nodes: `C:\opencue\bin\`

| File | Application | Usage |
|---|---|---|
| `hython-22.0.429.bat` | Houdini 22.0.429 | `hython-22.0.429.bat <script.py>` |
| `maya-render-2027.bat` | Maya 2027 | `maya-render-2027.bat <scene.ma> <outdir> [renderer]` |
| `nuke-17.0v1.bat` | Nuke 17.0v1 | `nuke-17.0v1.bat <script.py>` |

Submission script: [`notes/sandbox/lab/submit_dcc.py`](lab/submit_dcc.py).

---

# Licensing and Husk Two-Stage Rendering

## Declaring License Servers in Wrapper Scripts

Floating licensing requires declaring license endpoints inside wrapper scripts:

```bat
REM --- DCC license servers ---------------------------------------------------
REM set ADSKFLEX_LICENSE_FILE=@license-server.studio.local
REM set foundry_LICENSE=4101@license-server.studio.local
REM set solidangle_LICENSE=5053@license-server.studio.local
REM ---------------------------------------------------------------------------
```

## Solaris / USD: Two-Stage Husk Dispatching

Large-scale Houdini workflows separate caching from rendering:
- Stage 1 (Cache): `hython` generates USD assets.
- Stage 2 (Render): `husk.exe -o out.exr scene.usd`

Husk renders independently:

```
husk.exe --make-output-path -f 1 -o "C:/opencue/render/husk.$F4.exr" scene.usda
-> exit 0, husk.0001.exr 916 KB
```

---

# Multi-Node Simulation via Docker Containers

Additional RQD containers simulate multi-node behavior locally:

```bash
docker run -d --name render02 --hostname render02 --network opencue \
  -e OPENCUE_RQD_CONFIG=/etc/rqd/render02.yaml \
  -v /mnt/c/opencue/nodes:/etc/rqd:ro \
  --entrypoint /bin/sh \
  opencue-rqd:latest \
  -c 'id -u chordee >/dev/null 2>&1 || useradd --uid 2000 --gid 1000 -M chordee; exec /app/openrqd'
```

### Pitfall #16: Rust RQD Tag Lists Cannot Be Configured via Environment Variables

Passing comma-separated tags via `OPENRQD__MACHINE__CUSTOM_TAGS` causes panic (`expected a sequence`). Configuration files must be provided via `OPENCUE_RQD_CONFIG`.

### Pitfall #17: Facility Mismatches Silently Prevent Job Dispatching

Jobs submitted default to `facility = local`. Newly registered RQD nodes default to `facility = cloud`.

Mismatched facilities cause jobs to remain indefinitely in WAITING with zero diagnostic errors.

Resolution:
```bash
cueadmin -force -move local.general -host render02
```
or declare facility explicitly in node configuration.

---

# Heterogeneous Multi-OS Render Farms

OpenCue natively supports concurrent Windows and Linux worker fleets.

## Operating System Filtering via the `os` Parameter

Cuebot dispatching checks `job.str_os` (`DispatchQuery.java:284-287`):
- Unspecified `os` → dispatches to any available platform.
- Explicit `os` → dispatches strictly to matching platforms.

In `outline.cuerun.launch()`:

```python
outline.cuerun.launch(ol, use_pycuerun=False, os="Windows")
```

Comparing submissions targeting identical tasks:
- `os="debian"` → Dispatched to `render02` → SUCCEEDED.
- `os="Windows"` → Dispatched to `LAPTOP-ULJICLO8` → DEAD (`/bin/sleep` not found on Windows).

Failure confirmed OS routing operated correctly.

**Guideline**: Use `os` parameter for OS platform selection; use `tags` for DCC versions and hardware attributes.

## Cross-Platform Frame Log Mapping (`per-OS frame log root`)

When nodes run different operating systems, `CUE_FRAME_LOG_DIR` paths must vary per OS.

In Cuebot parameters:

```yaml
command: >-
  --datasource...
  --log.frame-log-root.Windows=C:/opencue/logs
  --log.frame-log-root.debian=/tmp/rqd/logs
```

Evaluated during testing:
- Job with `os="debian"` logged to `/tmp/rqd/logs/...` on Linux container.
- Job with `os="Windows"` logged to `C:/opencue/logs/...` on Windows node.

Both paths logged to disk and database cleanly.
