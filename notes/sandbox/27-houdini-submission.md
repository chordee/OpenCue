# 27 — Direct Submission from Houdini

Production procedures are summarized in [`notes/deploy/03-workstations.md` Section 7](../deploy/03-workstations.md#7-submitting-directly-from-houdini); this document records the architectural design and empirical testing results.

Environment: Houdini 22.0.429 (Python 3.13), OpenCue venv (Python 3.11.9), 2026-09-25.

---

## 1. Implementation Architecture

The repository lacks a native Houdini submission plugin. Following the two-stage model in [`25`](25-maya-submission.md), a third dedicated execution script was introduced to run on render nodes:

| Script | Execution Context | Responsibility |
|---|---|---|
| [`opencue_houdini_launcher.py`](../deploy/client/houdini/opencue_houdini_launcher.py) | Inside Houdini | Uses only `hou`: extracts hip path, renderable nodes, frame range, simulation flags, and version; dumps JSON and launches submission GUI |
| [`opencue_houdini_submit.py`](../deploy/client/houdini/opencue_houdini_submit.py) | `C:\opencue\venv` | CueSubmit GUI; Houdini settings panel constructs complete command line |
| [`opencue_houdini_render.py`](../deploy/client/houdini/opencue_houdini_render.py) | Render node hython | Opens hip file; renders designated node for the task frame range |

Key architectural decisions:

- **Metadata serialized via JSON**: Node hierarchies can be extensive; serializing metadata to temporary JSON avoids Windows CLI character limits.
- **Bypassing Houdini's bundled `hrender.py`**: Bundled utilities reside in versioned installation paths that vary across render hosts. `ocrun` resolves only core executables, so the custom render script resides at a fixed shared network storage path.
- **CueSubmit lacks a native Houdini job type**: Utilizes the generic `Shell` type. A Shell layer submits the contents of `commandTextBox` verbatim, allowing the custom panel to construct complete CLI instructions. Jobs therefore display as type `Shell` in GUI tools.
- **Frame numbering uses `#FRAMESPEC#`**: Cuebot substitutes this token with the task's frame specification (e.g., `7`, `1-10`, `1-9x2`) (`DispatchSupportService.java:687`), ensuring correct resolution when stepping frames.
- **Service resolution via tags**: The Cuebot service for version 22.0.429 is named `houdini2204`, which cannot be derived deterministically from the version string; resolution queries services whose tags include `houdini_22_0_429`.

### Renderable Node Classification

Inspecting Houdini 22.0.429 via hython:

| Node Type | Base Class | Rendering Method |
|---|---|---|
| ROP Geometry (SOP), `/out` geometry / usdrender / karma, USD Render ROP (LOP) | `hou.RopNode` | `render(frame_range=...)` |
| File Cache (SOP, `filecache::2.0`) | `hou.SopNode` | Set `trange`, `f` parameters, then trigger `execute` |
| Karma (LOP) | `hou.LopNode` | Same as above |

The launcher collects **all instances of `hou.RopNode`**, supplemented by whitelisted non-ROP types (`filecache::2.0`, `karma`) that expose `trange` and `f1` parameters (used by the render script to set frame intervals). Locked HDA internals are skipped (e.g., `rop_usdrender` inside `/out/karma1`).

The initial prototype matched nodes exposing `execute`, `trange`, and `f1`, which proved overly broad: any HDA bearing those parameter names was collected. Re-evaluating under the refined rules via hython:

| Node | Initial Rule | Refined Rule |
|---|---|---|
| Standard targets (File Cache ×2, ROP Geometry, Karma LOP) | Collected | Collected |
| `/out` Mantra ROP (`ifd`) | Collected | Collected |
| Generic null node with `execute`, `trange`, `f1` added | **Collected** | Ignored |
| `/out` merge ROP (lacks `trange`) | Ignored | Ignored |

### Simulation Detection

When a File Cache node enables **Cache Simulation** (`cachesim`) or a ROP node enables **Initialize Simulation OPs** (`initsim`), the job defaults to chunking the **entire frame range into a single task**. Format-conversion caches can be evaluated in parallel per-frame, so node type alone cannot govern chunking. This setting serves as a default; dynamic DOP, TOP, and third-party simulation nodes cannot be determined statically and require confirmation by the artist in the submission GUI.

---

## 2. Empirical Verification

### 1. Test Scene Setup

Generated via [`lab/make_houdini_submit_scene.py`](lab/make_houdini_submit_scene.py) and saved to `C:\opencue\scenes\hou_submit_test.hip`:

| Node Path | Description | Frame Range |
|---|---|---|
| `/obj/geo1/convert_cache` | File Cache: box converted to bgeo, `cachesim` disabled | 1-4 |
| `/obj/geo1/sim_cache` | File Cache: Solver SOP (y +0.5 per frame), `cachesim` enabled | 1-10 |
| `/obj/geo1/rop_out` | ROP Geometry | 1-3 |
| `/stage/karma_render` | Karma LOP, 160×90 | 1-3 |

### 2. Launcher Verification (hython)

```
nodes: convert_cache  1-4   simulation false
       sim_cache      1-10  simulation true
       rop_out        1-3   simulation false
       karma_render   1-3   simulation false
removed env: PYSIDE6_OPTION_PYTHON_ENUM, PYTHONHOME, PYTHONPATH, PYTHONUNBUFFERED
```

Houdini injects `PYTHONHOME`; failure to strip this variable causes venv Python to load Houdini's standard libraries instead of its own.

In hython, `hou.hipFile.hasUnsavedChanges()` **evaluates to True unconditionally**, even immediately after saving; the prompt regarding unsaved changes is restricted to interactive UI sessions.

### 3. Submission GUI & Render Execution

Operating the submission GUI programmatically (offscreen), submitting the four nodes sequentially:

```
convert_cache  services ['houdini2204']  range 1-4   chunk 1
sim_cache      services ['houdini2204']  range 1-10  chunk 10
rop_out        services ['houdini2204']  range 1-3   chunk 1
karma_render   services ['houdini2204']  range 1-3   chunk 1

built: ocrun houdini 22.0.429 hython .../opencue_houdini_render.py
       C:/opencue/scenes/hou_submit_test.hip /obj/geo1/sim_cache #FRAMESPEC#
```

| Job Name | Tasks | Status | Output Files |
|---|---|---|---|
| `hou_convert_cache` | 4 | All SUCCEEDED | `convert.0001` – `0004.bgeo.sc` |
| `hou_sim_cache` | **1** | SUCCEEDED | `sim.0001` – `0010.bgeo.sc` |
| `hou_rop_out` | 3 | All SUCCEEDED | `rop.0001` – `0003.bgeo.sc` |
| `hou_karma_render` | 3 | All SUCCEEDED | `karma.0001` – `0003.exr` |

Simulation cache frame log: `[opencue] /obj/geo1/sim_cache frames 1-10 step 1`. Reading centroid y values per frame: `0.5, 1.0, ... 5.0`, accumulating predictably and accurately.

### 4. Impact of Splitting Simulation Tasks

Rendering solely frame 8 of `sim_cache` in a fresh hython process exited 0, computing y = 4.0 correctly and writing only `sim.0008`. Lacking prior cached frames, Solver SOP recalculates state from the start frame; while **numerical results remain correct, calculating frame N requires computing N frames**, increasing total computation complexity to approximately n²/2. This underscores the necessity of bundling simulations into a single monolithic task.

### 5. Auxiliary Verification

| Scenario | Result |
|---|---|
| Frame spec `1-5x2` | Emitted only frames 1, 3, and 5 |
| Non-existent node | Exited 1 with error log: `RuntimeError: node not found: /obj/geo1/nope` |
| Houdini package (`PYTHONPATH` append) | Launcher cleanly imported in hython |

During testing, Git Bash automatically translated `/obj/geo1/...` arguments into `C:/Program Files/Git/obj/...`. When executing directly from Git Bash, set `MSYS_NO_PATHCONV=1`.

---

### 6. Manual Testing in Houdini GUI

Opening the test scene, calling `submit()` from Python Shell, and submitting the four nodes in sequence resulted in all four jobs succeeding, with the simulation cache executing as 1 task with chunk size 10.

A minor bug was discovered: when switching nodes, the layer name field failed to update, causing subsequent jobs to inherit `convert_cache` from the initial selection. The logic was updated to auto-populate layer names upon node selection and integrated into [`lab/check_submit_tools.py`](lab/check_submit_tools.py).

---

## 3. Pending Verification Items

- Physical shelf tool buttons (manual tests were triggered via Python Shell executing identical code); unsaved scene prompts in GUI.
- Alternative Houdini versions and Python 2.7 legacy builds.
- Third-party render engine ROPs (Redshift, Arnold; neither installed on the test workstation).
- Complex dynamic DOP simulations (Pyro, Vellum; verified using Solver SOP proxy).
