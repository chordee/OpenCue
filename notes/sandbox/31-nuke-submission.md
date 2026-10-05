# 31 — Direct Submission from Nuke

Production procedures are summarized in [`notes/deploy/03-workstations.md` Section 8](../deploy/03-workstations.md#8-submitting-directly-from-nuke); this document records the architectural design and empirical testing.

Environment: Nuke 17.0v1 (Python 3.11.11), OpenCue venv (Python 3.11.9), 2026-09-25.

---

## 1. Existing In-Repo Implementation Issues

| Component | Defect |
|---|---|
| In-repo plugin `cuesubmit/plugins/nuke/` | Decoupled architecture, but invokes `communicate()` to **block until submission GUI closes**, freezing Nuke interactive sessions; requires `CUE_PYTHON_BIN` or system `python` on PATH |
| CueSubmit Nuke job type | Submits `-X [All]` when no Write node is selected; emits `-X a, b` when multiple nodes selected (matching the camera defect documented in [`05` Issue #22](05-upstream-issues.md#22-cuesubmit-maya-camera-selection-sends-invalid--cam)) |
| CueSubmit Nuke job type | Hardcodes `-F #IFRAME#`; when chunk size > 1, renders only the initial frame of each task |

Verification of the chunking defect (`-F #IFRAME#`, range `1-4`, chunk size 2):

```
frames: 1 SUCCEEDED, 3 SUCCEEDED
output: a.0001.png, a.0003.png          ← Frames 2 and 4 skipped entirely yet marked completed
```

See [`05` Issue #25](05-upstream-issues.md#25-cuesubmit-nuke-submission-sends-invalid--x-drops-frames-when-chunk--1).

---

## 2. Architecture & Design

Following the model established in [`27`](27-houdini-submission.md): the launcher inside Nuke uses only the internal `nuke` module to gather scene metadata and write temporary JSON; the submission GUI in the venv leverages the generic Shell type to assemble the complete command:

```
ocrun nuke <version> Nuke<major.minor> -F #FRAMESPEC# [-X Write1,Write2] -x <script.nk>
```

- Binary name derived deterministically from version string: `17.0v1` → `Nuke17.0`
- Write nodes default to select-all; when all nodes selected, `-X` is omitted, prompting Nuke to render all active Write nodes.
- Service queried via version tag `nuke_17_0v1`, resolving to `nuke17`.
- `menu.py` appends OpenCue > Submit to OpenCue to the main menu bar; deployment requires adding the tool directory to `NUKE_PATH`.
- Nuke batch frames read only `.nk` scene files and invoke `ocrun`; tool scripts can be updated in-place without versioned directory hierarchies.

---

## 3. Empirical Verification

### 1. Nuke CLI Behavior

Test script `C:\opencue\scenes\nuke_submit_test.nk` generated via [`lab/make_nuke_submit_scene.py`](lab/make_nuke_submit_scene.py): CheckerBoard feeding two Write nodes (`WriteA` at root, `WriteB` inside Group `Comp`).

Farm submission testing (`-X WriteA,Comp.WriteB`):

| Layer Configuration | Range / Chunk | Emitted `-F` Argument | Result |
|---|---|---|---|
| Stepped | `1-5x2` / 3 | `1-5x2` | 1 task, evaluated frames 1, 3, and 5 |
| Chunked | `1-4` / 2 | `1-2`, `3-4` | 2 tasks, evaluating 2 frames each |

- Nuke's `-F` flag accepts Cuebot's `#FRAMESPEC#` format (`1-2`, `1-5x2`).
- `-X` accepts comma-separated node lists; nested nodes reference parent groups via dot notation (`Comp.WriteB`).
- Nuke licensing checks succeed within frame execution environments.

Exit code behavior on failure (direct execution):

| Failure Mode | Exit Code | Stdout Message |
|---|---|---|
| `-X Nope` (Missing node) | 1 | `Nothing is named "Nope"` |
| Non-existent output directory | 1 | `WriteA: Can't write, no such directory` |

Nuke returns non-zero exit codes on failure (unlike Maya in [`30`](30-arnold-licensing.md)); stdout filtering inside `ocrun` is unnecessary.

### 2. Launcher Verification (Nuke Terminal Mode)

```
GUI False, modified after open False
info: script C:/opencue/scenes/nuke_submit_test.nk, version 17.0v1,
      writes [WriteA, Comp.WriteB], range 1-5
removed env: PYSIDE63_OPTION_PYTHON_ENUM, PYTHONPATH
```

`nuke.modified()` evaluates to False immediately upon opening, avoiding the persistent unsaved-state defect seen in hython.

### 3. Submission GUI & Render Execution

Integrated Nuke validation into [`lab/check_submit_tools.py`](lab/check_submit_tools.py):

```
PASS  service: ['nuke17']
PASS  range: '1-5'
PASS  command, all writes: ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -x C:/opencue/scenes/nuke_submit_test.nk
PASS  command, one write:  ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -X WriteA -x C:/opencue/scenes/nuke_submit_test.nk
```

Submitted jobs with `--submit`: both 5-frame jobs succeeded completely, outputting `a.0001`–`0005` and `b.0001`–`0005`.

### 4. Submission from Interactive Nuke GUI

Opening the test script, invoking `submit()` from the Script Editor, and submitting frames 1-5 (all Write nodes selected):

```
ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -x C:/opencue/scenes/nuke_submit_test.nk   service nuke17
```

Submitted during daytime hours while CueNIMBY schedule locked the node: frames paused in WAITING state as expected. Unlocking temporarily resulted in all 5 frames succeeding (Frame 1 took 40s for cold Nuke launch; subsequent frames took ~3s each), producing complete image sets for `a` and `b`, after which NIMBY re-locked.

De-selecting `Comp.WriteB` in the submission GUI and re-submitting: command updated to `-X WriteA`; all 5 frames succeeded, outputting solely `a.0001`–`0005`. Executing with an unsaved modified script prompted the artist to save.

Adding the tools folder to `NUKE_PATH` registered **OpenCue > Submit to OpenCue** in the main menu bar upon restart.

---

## 4. Pending Verification Items

- Disabled Write nodes exclusion (implemented in code, not empirically verified).
- Other Nuke versions and Python 2.7 legacy releases.
- NukeX and Nuke Studio licensing variants and binary naming conventions.
