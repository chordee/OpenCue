# 26 — Replacing DCC Wrappers with ocrun

Production procedures are summarized in [`notes/deploy/02-render-nodes.md` Section 5](../deploy/02-render-nodes.md#5-invoking-dcc-applications-ocrun); this document records the architectural motivation, design, and empirical verification.

---

## 1. Motivation

Historically, every DCC version required a dedicated `.bat` script on every render node (`C:\opencue\bin\hython-22.0.429.bat`, etc.):

- Introducing a new version required adding script files and manually updating installation paths across all render hosts.
- Introducing Linux nodes required maintaining parallel shell script implementations for every tool.
- Command argument formats were inconsistent: `maya-render-2027.bat` accepted custom arguments (scene, output directory, renderer), whereas `Render-2027.bat` forwarded native flags verbatim to `Render.exe`, creating naming ambiguities and configuration errors.

In practice, wrappers perform three basic tasks: resolving local executable paths, configuring environment variables, and forwarding command arguments. Implementing this logic in Python provides seamless cross-platform execution across Windows and Linux.

---

## 2. Architecture & Design

```
ocrun <dcc> <version> <executable> [args...]
ocrun maya 2027 Render -r file -s #IFRAME# -e #IFRAME# P:/proj/scene.ma
```

| Component | Location | Host Specific |
|---|---|---|
| Resolution and execution logic | [`node/ocrun/ocrun.py`](../deploy/node/ocrun/ocrun.py), installed into venv via pip | No (Identical) |
| Common DCC environment settings (`MAYA_DISABLE_CER`, `TEMP`, `NUKE_DISK_CACHE`) | `ocrun.py` | No (Identical) |
| Version to installation path mapping, license servers | `dcc.toml` (Template: [`node/dcc-windows.toml`](../deploy/node/dcc-windows.toml)) | Yes (Node-specific) |

Key design decisions:

- **Frame numbers resolve via Cuebot dispatch tokens**: Legacy wrappers read `CUE_IFRAME` and assembled arguments manually, requiring custom CLI schemas for every DCC. Cuebot automatically substitutes `#IFRAME#` with the dispatched frame number during task dispatch (`DispatchSupportService.java:718`). Consequently, `ocrun` does not need to parse DCC arguments; it forwards tokens verbatim.
- **Path discovery for `ocrun` inside frames**: When `rqd.conf` configures `RQD_USE_PATH_ENV_VAR = 1`, the child frame inherits RQD's host PATH (`rqmachine.py:571`). By prepending the venv `Scripts` directory to PATH in `rqd-start.bat`, job commands invoke `ocrun` directly without hardcoding Windows-specific absolute paths like `C:\...`.
- **Configuration file path**: Defaults to `C:\opencue\dcc.toml` on Windows and `/opt/opencue/dcc.toml` on Linux; can be overridden via the `OPENCUE_DCC_CONFIG` environment variable (which can be passed in job-level environment variables).
- **Standard library only**: Uses Python 3.11's built-in `tomllib` without third-party dependencies.
- **Fail-fast on missing versions or binaries**: Exits with return code 127 and logs descriptive error details to the frame log. Executing `ocrun` without arguments lists all configured DCCs on the local host.

Comparison with legacy wrappers:

| Legacy Wrapper | `ocrun` Equivalent |
|---|---|
| `hython-22.0.429.bat script.py` | `ocrun houdini 22.0.429 hython script.py` |
| `husk-22.0.429.bat scene.usd out.$F4.exr` | `ocrun houdini 22.0.429 husk --make-output-path -f #IFRAME# -n 1 -o out.$F4.exr scene.usd` |
| `maya-render-2027.bat scene.ma outdir sw` | `ocrun maya 2027 Render -r sw -s #IFRAME# -e #IFRAME# -rd outdir scene.ma` |
| `Render-2027.bat -r file ...` (Maya submission) | `ocrun maya 2027 Render -r file ...` |
| `nuke-17.0v1.bat script.py` | `ocrun nuke 17.0v1 Nuke17.0 -t script.py` |

---

## 3. Empirical Verification (2026-09-25)

### 1. Unit Tests

[`node/ocrun/test_ocrun.py`](../deploy/node/ocrun/test_ocrun.py) covers: exit code propagation, environment variable injection, arguments containing whitespace, missing versions/binaries, and entry-point execution after packaging.

| Environment | Test Result |
|---|---|
| Windows venv (Python 3.11.9) | 5 passed |
| Linux container (`python:3.11-slim`), executed post `pip install` | 5 passed; `ocrun` entry point located at `/usr/local/bin/ocrun` |

### 2. Direct CLI Execution

```
> ocrun
configured in C:\opencue\dcc.toml:
  maya 2027  D:\programs\Autodesk\Maya2027\bin
  houdini 22.0.429  D:\programs\Side Effects Software\Houdini 22.0.429\bin
  nuke 17.0v1  D:\programs\Nuke17.0v1

> ocrun houdini 22.0.429 hython -c "import hou; print(hou.applicationVersionString())"
22.0.429
```

Installation paths containing spaces (`Side Effects Software`) parsed and executed cleanly.

### 3. Rendering via RQD

Jobs submitted via [`lab/submit_dcc.py`](lab/submit_dcc.py) and [`lab/submit_houdini_twostage.py`](lab/submit_houdini_twostage.py) (migrated to `ocrun`):

| Job | Binary | Frame Range | Outcome |
|---|---|---|---|
| `houdini_render_22_0_429` | hython (Karma) | 1-2 | All SUCCEEDED |
| `maya_render_2027` | Render (`-r sw`) | 1-2 | All SUCCEEDED |
| `nuke_render_17_0v1` | Nuke17.0 `-t` | 1-2 | All SUCCEEDED |
| `houdini_twostage` | hython USD export → husk | 1 + 2 | All SUCCEEDED |

All jobs returned exit code 0 without retries, updating output files successfully. The initial line of each frame log was emitted by `ocrun`, confirming `#IFRAME#` substitution:

```
[ocrun] maya 2027: D:\programs\Autodesk\Maya2027\bin\Render.EXE -r sw -s 2 -e 2 -rd C:/opencue/render/maya C:/opencue/scenes/test.ma
[ocrun] houdini 22.0.429: D:\programs\Side Effects Software\Houdini 22.0.429\bin\husk.EXE --make-output-path -f 1 -n 1 -o C:/opencue/render/twostage.$F4.exr C:/opencue/render/twostage.usda
```

Nuke executed successfully without custom `NUKE_DISK_CACHE` definitions, validating that `TEMP` fallback injection in `ocrun` operates as designed (for failure profiles without these variables, see [`17` Scenario 7](17-troubleshooting.md#scenario-7-nuke-render-fails-with-unable-to-create-disk-cache)).

### 4. Submission from Maya

The Maya submission tool command was converted to `ocrun maya <version> Render` ([`client/maya/opencue_maya_submit.py`](../deploy/client/maya/opencue_maya_submit.py)), submitted programmatically through the submission GUI (procedure matching [`25` Section 4](25-maya-submission.md#4-empirical-verification)):

```
built : ocrun maya 2027 Render -r file -s #FRAME_START# -e #FRAME_END# -cam renderCam1 C:/opencue/scenes/test.ma
```

CueSubmit tokenizes commands by whitespace; `ocrun maya 2027 Render` naturally constitutes four distinct arguments and remains unaffected. Both frames succeeded.

### 5. Killing Frames

Dispatched a hython frame set to execute for 600 seconds, then killed the job mid-execution:

| Timestamp | `ocrun.exe` Count | `hython.exe` Count |
|---|---|---|
| During Execution | 1 | 1 |
| 15 Seconds Post-Kill | 0 | 0 |

RQD on Windows terminates entire process trees using `taskkill /F /T /PID` (`rqnetwork.py:172`); adding an intermediary `ocrun` layer produces zero orphaned child processes.

During the initial kill test, the job failed to respond: invoking `job.kill()` without providing a reason caused Cuebot to log `**Invalid Job Kill Request**` and ignore the request while returning a success response to the client. Supplying an explicit `reason` resolved the issue. See [`17` Scenario 26](17-troubleshooting.md#scenario-26-killing-job-via-api-silently-fails-while-job-keeps-running).

### 6. Arguments Containing Whitespace

Command string: `["ocrun", "houdini", "22.0.429", "hython", '"C:/opencue/tmp/a b/t.py"', '"x y"']`; `sys.argv` received inside the script:

```
['C:/opencue/tmp/a b/t.py', 'x y']
```

Explicitly quoted arguments passed through RQD batch wrappers and `ocrun` reached the target DCC intact with surrounding quotes stripped. Unquoted arguments continue to be split by whitespace ([`17` Scenario 24](17-troubleshooting.md#scenario-24-frame-fails-when-path-contains-spaces)).

---

## 4. Pending Tasks for Adding Linux Nodes

`ocrun` and job commands are cross-platform. Adding Linux render nodes requires the following configuration steps:

- Install RQD and `ocrun` in a dedicated venv, placing configuration at `/opt/opencue/dcc.toml`.
- Configure systemd service units for RQD, prepending the venv `bin` to PATH and setting `RQD_USE_PATH_ENV_VAR = 1`.
- Adjust `TZ` handling: an empty `TZ` on Linux evaluates to UTC instead of host local time; see [`29`](29-frame-timezone.md).

The following architectural items are not automatically resolved by Python and **remain pending**:

| Requirement | Implementation Strategy |
|---|---|
| Drive Letter Mapping | Linux lacks `P:\`. Command-line arguments can be translated via `ocrun`; paths embedded inside scene assets require native DCC translation features (Maya dirmap, `HOUDINI_PATHMAP`, Nuke filename filters). |
| Dispatch Filtering | Cuebot matches OS tags between jobs and nodes (`str_os` in `DispatchQuery.java`). Current submission rules explicitly pass `os="Windows"` ([`deploy/03` Section 9](../deploy/03-workstations.md#9-pre-submission-checklist)). |
| Frame Log Storage | Dual-platform farms require separate log root configurations ([`17` Scenario 21](17-troubleshooting.md#scenario-21-in-multi-os-farms-jobs-succeed-but-logs-cannot-be-found)). |
| DCC Application Environments | Linux DCC binaries, plugins, and license server configurations must be audited and verified independently. |

---

## 5. Pending Verification Items

- **Execution across multiple machines with divergent DCC install paths**: Host tests performed on a single Windows machine.
- **Physical Linux render node execution**: `ocrun` verified only within containerized test environments; full DCC stack untested on Linux.
- Effectiveness of `MAYA_DISABLE_CER` during genuine Maya application crashes. The Autodesk licensing module error dialog cannot be suppressed by this flag; see [`28`](28-maya-crash-reporting.md).
