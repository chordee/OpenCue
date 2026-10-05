# 25 — Direct Submission from Maya

Production procedures are summarized in [`notes/deploy/03-workstations.md` Section 6](../deploy/03-workstations.md#6-submitting-directly-from-maya); this document serves as the architectural evaluation and testing log.

> The transitional adapter wrapper `Render-<version>.bat` described in this document was subsequently superseded by `ocrun maya <version> Render`; see [`26`](26-ocrun-wrapper.md).

---

## 1. Existing In-Repo Plugins

| DCC | Location | Execution Mode |
|---|---|---|
| Maya | `cuesubmit/plugins/maya/` | Shelf button; runs the CueSubmit GUI **inside Maya's internal Python runtime** |
| Nuke | `cuesubmit/plugins/nuke/` | Nuke collects scene filename and Write nodes, launching an external Python process via `CUE_PYTHON_BIN` to render the GUI |
| Houdini / Blender | None | — |

The rationale for Nuke using an external Python runtime is documented in comments within `CueNukeSubmitLauncher.py`: Nuke's bundled gRPC version conflicts with OpenCue.

### Render Command Construction (`cuesubmit/Submission.py`)

```
Maya: {MAYA_RENDER_CMD} -r file -s #FRAME_START# -e #FRAME_END# [-cam camera] scene
Nuke: {NUKE_RENDER_CMD} -F #IFRAME# [-X WriteNode] -x scene
```

`MAYA_RENDER_CMD` defaults to `Render` and can be configured in `cuesubmit.yaml` (`CUESUBMIT_CONFIG_FILE` or `%APPDATA%\opencue\cuesubmit.yaml`). A configuration file can only specify a single value.

The command string is constructed first and then tokenized into a list using `command.split()`; **wrapping paths containing spaces in double quotes is ineffective** ([`17` Scenario 24](17-troubleshooting.md#scenario-24-frame-fails-when-path-contains-spaces)).

---

## 2. Gaps with Current Architecture

### 1. DCC Bundled Python Versions

| DCC | Bundled Python (Verified) |
|---|---|
| Maya 2027 | **3.13.9** |
| Houdini 22.0.429 | **3.13.10** |
| Nuke 17.0v1 | 3.11.11 |
| OpenCue venv | 3.11.9 (grpcio 1.84.0) |

The repository's Maya plugin requires the `opencue` library (including binary-compiled `grpcio`) to be imported inside Maya's internal Python interpreter. Because Maya 2027 differs from the OpenCue venv Python version, **a separate compiled installation is required**; when multiple Maya versions coexist, each version requires a separate package installation, and older versions are increasingly prone to binary compatibility issues with grpcio.

### 2. Command Format Divergence from Existing Wrappers

`maya-render-2027.bat` expects `scene output_directory renderer`, taking the frame number from `CUE_IFRAME`; CueSubmit emits native `Render.exe` flags. Consequently, a separate transition wrapper `Render-2027.bat` was created to forward CLI arguments verbatim to `Render.exe`.

### 3. Built-in `maya` Service in Cuebot

```
maya          tags=general | desktop
maya2027      tags=maya_2027
```

If an artist selects the built-in `maya` service in the GUI, version binding is bypassed (tag matching uses OR logic; `general` matches any host node).

---

## 3. Implementation: Two-Stage Architecture

Following the design pattern established by the Nuke plugin, decouple metadata collection from the submission interface:

| File | Execution Context | Responsibility |
|---|---|---|
| `opencue_maya_launcher.py` | Inside Maya, any version | Uses only `maya.cmds` and `subprocess`: scene, camera, frame range, `about -version` |
| `opencue_maya_submit.py` | `C:\opencue\venv` | CueSubmit GUI; configures `Render-<version>.bat` and service `maya<version>` based on version |

Key design details:

- CueSubmit's `InMayaSettings` (the settings panel displayed inside Maya) **does not use the Maya API at all**; it is purely a Qt widget receiving file paths and camera lists, allowing it to execute outside Maya.
- `Constants.MAYA_RENDER_CMD` is evaluated only at submission time; monkey-patching it after startup allows dynamic version targeting.
- Launching child processes from Maya inherits Maya's environment variables. Empirically, `mayapy` injects `PYTHONPATH` and `QT_PLUGIN_PATH` pointing to Maya's internal Python 3.13 and Qt runtimes, causing venv crashes. Strip all variables starting with `PYTHON*`, `QT_*`, `QTDIR`, and `PYSIDE*` prior to launch.
- Launch via `Popen` **without waiting (`wait()`)**, preventing the host DCC from freezing (unlike the upstream Nuke plugin behavior).
- Launcher syntax remains backward compatible with Python 2.7 (avoiding f-strings) to support legacy Maya versions.

---

## 4. Empirical Verification

### 1. Maya Environment Independent of opencue Package

Opening `C:\opencue\scenes\test.ma` in `mayapy` 2027:

```
opencue importable in mayapy: NO
version: 2027
range: 1-10
command: [...pythonw.exe, ...opencue_maya_submit.py, --file, C:/opencue/scenes/test.ma,
          --version, 2027, --range, 1-10, --cameras, front, persp, renderCam1, side, top]
env removed: ['PYTHONPATH', 'QT_PLUGIN_PATH']
```

Even though `opencue` **cannot be imported inside mayapy**, the launcher functions properly.

### 2. Launching Submission Interface from Maya and Submitting

Launching venv Python from `mayapy` with a sanitized environment using Qt offscreen mode, populating job name, shot, layer name, and camera programmatically, then submitting (simulating artist interaction):

```
show     : testing                     ← Extracted from PROJECT environment variable
services : ['maya2027']                ← Automatically selected based on version
range    : 1-10
built    : C:/opencue/bin/Render-2027.bat -r file -s #FRAME_START# -e #FRAME_END#
           -cam renderCam1 C:/opencue/scenes/test.ma
submitted
```

### 3. Render Output Results

| Metric | Result |
|---|---|
| Frames | 10 / 10 SUCCEEDED |
| Dispatch Host | All executed on LAPTOP (layer tag `maya_2027` resolved from service) |
| Duration per Frame | Average 34.5 seconds |
| Frame Numbers | Correctly substituted; e.g., frame 5 evaluated to `-s 5 -e 5` |

### 4. Output Destination

```
Finished Rendering C:/Users/chordee/Documents/maya/projects/default/images/test.0005.png.
```

The CLI command omitted `-rd`, leaving output resolution to the scene's associated Maya project workspace. Because the test scene did not reside within an active project directory, rendered images fell back to the **local default project on the render node**. Production scenes must always reside within structured project directories containing `workspace.mel`.

---

## 5. Issues Identified During Manual Testing

### 1. Submitting `-cam [None]` When No Camera Is Selected

Submitting via the Maya GUI without selecting a camera caused all 10 frames to fail:

```
Render-2027.bat -r file -s #FRAME_START# -e #FRAME_END# -cam [None] scene_luffy_test.ma

Error: makeCameraRenderable.mel line 34: Camera [None] does not exist.
// Maya exited with status 210
```

When no camera is selected in CueSubmit's dropdown menu, the button text displays `[None]`, and `InMayaSettings.getCommandData()` literally evaluates button text as the camera name. Selecting multiple cameras emits `-cam a, b`, which fails parsing. Programmatic test cases previously pre-selected cameras, leaving this undetected. See [`05` Issue #22](05-upstream-issues.md#22-cuesubmit-maya-camera-selection-sends-invalid--cam).

**Fix** (`MayaSettings` in `opencue_maya_submit.py`):

| Condition | Emitted Command Token |
|---|---|
| Scene has exactly one renderable camera | Pre-selected upon launch: `-cam <camera>` |
| No camera selected | Omit `-cam` entirely; Maya renders all renderable cameras in the scene |
| Multiple cameras selected | Enforce single selection; retain only the most recently selected camera |

All three conditions verified.

### 2. Workstation Running Maya While Processing Renders: Memory Exhaustion

The host machine operated simultaneously as an artist workstation and a render node. Submitting a job from an active Maya session caused frames to dispatch back to the same machine, launching multiple concurrent instances of `Render.exe` (~1 GB each, plus Arnold memory footprints):

```
MemTotal 40 GB, MemFree ~4 GB, Paging file in use ~14 GB
PowerShell failed to launch: The paging file is too small for this operation to complete
```

Two frames aborted within 1 second with exit status 304 without generating logs, consistent with process launch failure due to RAM exhaustion.

**Visual Crash Phenomenon Reported**: A crash report dialog appeared on screen. Windows Application Event Log (around 22:00):

| Timestamp | Faulting Process | Exception Code |
|---|---|---|
| 22:00:04, 22:00:13 | `mayabatch.exe` (Render process spawned by `Render.exe`) | 0xc0000005 |
| 22:00:01 – 22:00:48 | `cer_dialog.exe` (Autodesk Customer Error Reporting) | 0xc0000005, 0xc0000409, 0xc00000fd |

The error reporting dialog was **spawned by Autodesk Customer Error Reporting after the rendering Maya batch process crashed**; neither the submission GUI (`pythonw.exe` recorded zero crashes) nor the interactive Maya session was compromised. A subsequent test run (22:31) produced zero crash events in the Windows log.

This presents a production challenge: when rendering batch processes crash on render nodes, modal crash report dialogs block desktops—interrupting artists on workstations or idling indefinitely on headless dedicated nodes. Maya 2027 binaries support the `MAYA_DISABLE_CER` environment variable, which was integrated into both Maya wrappers. Rendering continued normally; **suppression behavior under true crashes remains to be verified empirically**.

> Clarification: Retrospective log investigation revealed that Maya actually spawned crash reporting dialogs upon completion during every frame of both test runs (although Windows event logs were empty at 22:31, licensing module CER logs recorded 8 crash dumps). The underlying cause was missing `ALLUSERSPROFILE` environment variables in frame execution, causing the licensing module—not Maya itself—to crash. `MAYA_DISABLE_CER` cannot suppress licensing CER dialogs. See [`28`](28-maya-crash-reporting.md).

In production, workstation nodes are locked by CueNIMBY during working hours and do not accept render dispatches while artists are active, preventing concurrency exhaustion. During local testing, increasing the Cores requirement in the submission GUI (e.g., to 4) throttles the number of concurrent frames dispatched to the host.

### 3. Re-Testing After Fixes

Opening `scene_luffy_test.ma` (Arnold) in Maya 2027 and invoking `opencue_maya_launcher.submit()` from the Script Editor opened the submission GUI normally, dispatching frames 1-3:

```
Render-2027.bat -r file -s #FRAME_START# -e #FRAME_END# -cam persp .../scene_luffy_test.ma
tags=maya_2027

0001  SUCCEEDED  98 s  1164 MB
0002  SUCCEEDED  98 s  1164 MB
0003  SUCCEEDED  98 s  1150 MB
```

Three frames executed concurrently on the local machine with minimum available memory stabilizing around 3.3 GB without incident.

> **Correction**: These 3 frames were actually **false successes**. Frame logs contained `license checkout error` and `aborting render because this is a batch render and abort_on_license_fail option is enabled`. Arnold rendered zero images, but `Render.exe` returned exit code 0, causing frames to be recorded as successful. See [`30`](30-arnold-licensing.md).

### 4. Jobs Not Visible in CueWeb

CueWeb's "Autoload Mine" filter determines job ownership using the authenticated user identity (`cueweb/app/page.tsx`: `getServerSession()` retrieving email or name). In unauthenticated configurations, user identity defaults to `unknown`, rendering automated views empty. Users must manually enter the show or job name into the search bar and click Load.

---

## 6. Pending Verification Items

| Item | Details |
|---|---|
| Legacy Maya Versions | Host only equipped with 2027; Python 2.7 syntax verified statically but not executed in older engines |
| Nuke Plugin | Not yet installed |
| Houdini Plugin | Implemented following this architecture; see [`27`](27-houdini-submission.md) |
