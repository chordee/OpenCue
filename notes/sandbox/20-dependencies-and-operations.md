# 20 — Job Dependencies and Operations

Job dependency is a core scheduling capability in OpenCue essential for production pipelines (e.g., caching before rendering, rendering before compositing, combining multiple AOVs).

Testing environment: Windows worker locked; tasks routed to Linux container node `render02` using simulated workloads.

---

## 1. Dependency State Machine

Frames introduce the **`DEPEND`** state, indicating that dependencies are unresolved and the frame cannot yet queue for resources.

```
DEPEND  ──(Dependencies satisfied)──>  WAITING  ──(Dispatched)──>  RUNNING  ──>  SUCCEEDED / DEAD
```

**Distinction Between `DEPEND` and `WAITING`**:

| State | Definition | Evaluated by Dispatcher |
|---|---|---|
| `WAITING` | Ready to execute, waiting in queue for resources | **Yes** |
| `DEPEND` | Blocked by unresolved dependencies | **No** |

When troubleshooting frames stuck in `DEPEND`, identify **which blocker frame is incomplete**, rather than investigating tags, facilities, or memory allocations.

## 2. Submitting Dependent Jobs in Paused State

In multi-job pipelines, jobs should be **submitted paused**, dependencies wired up, and then resumed.

If jobs dispatch immediately upon creation, initial tasks may complete before downstream dependencies are attached, resulting in dangling dependency linkages.

Initial state after submission (4-stage chain):

```
 job                  | Paused | Frame State
----------------------+--------+-----------
 chain_00             | t      | WAITING     <- No dependency; ready
 chain_01             | t      | DEPEND      <- Waiting for 00
 chain_02             | t      | DEPEND      <- Waiting for 01
 chain_03             | t      | DEPEND      <- Waiting for 02
```

Pipeline submission scripts should always adopt this pattern: submit paused → attach dependencies → resume.

## 3. Empirical Verification Across Three Topologies

### 1. Chain (Linear Dependency)

`load_test_jobs.py chain --chain-length 4`

Each task depends on the preceding task. Sampling sequence after resume:

| Sample | chain_00 | chain_01 | chain_02 | chain_03 |
|---|---|---|---|---|
| 1 | WAITING | DEPEND | DEPEND | DEPEND |
| **2** | **SUCCEEDED** | **RUNNING** | **DEPEND** | **DEPEND** |
| 3 | SUCCEEDED | SUCCEEDED | SUCCEEDED | SUCCEEDED |

Sample 2 demonstrates sequential execution: `01` starts only after `00` completes, while `02` and `03` remain locked in `DEPEND`.

### 2. Diamond (Branching and Merging)

`load_test_jobs.py diamond`

Task A blocks B and C; B and C concurrently block D.

| Sample | a | b | c | d |
|---|---|---|---|---|
| 1 | WAITING | DEPEND | DEPEND | DEPEND |
| **2** | **SUCCEEDED** | **RUNNING** | **RUNNING** | **DEPEND** |
| 3 | SUCCEEDED | SUCCEEDED | SUCCEEDED | SUCCEEDED |

Sample 2 proves:
1. `b` and `c` run **concurrently in parallel** upon `a`'s completion.
2. `d` remains in `DEPEND` until **both** `b` and `c` finish.

### 3. Fan-in (Multiple Blockers, Single Dependent)

`load_test_jobs.py fan-in --blockers 3`

Three parallel blockers gating a single consumer.

| Sample | blocker_00 | blocker_01 | blocker_02 | dependent |
|---|---|---|---|---|
| 1 | WAITING | WAITING | WAITING | DEPEND |
| **3** | **SUCCEEDED** | **SUCCEEDED** | **RUNNING** | **DEPEND** |
| 4 | SUCCEEDED | SUCCEEDED | SUCCEEDED | **SUCCEEDED** |

Sample 3 confirms: two completed blockers are insufficient; `dependent` unlocks only after the third blocker completes.

### Dependency Satisfaction Rules

In `cuebot/src/main/resources/opencue.properties:417`:

```properties
depend.satisfy_only_on_frame_success=true
```

**By default, dependencies clear only when blocker frames succeed.**
- If a blocker frame transitions to `DEAD`, downstream dependent frames remain in `DEPEND` indefinitely.
- If dependent frames are stuck in `DEPEND`, check whether upstream tasks failed.

## 4. Operator Commands: `cueadmin -kill` vs. `cueman -term`

Observed differences when cleaning jobs:
- `cueadmin -force -kill <job>`: Cancels executing frames, but the job remains in the queue.
- `cueman -force -term <job>`: Terminates the job completely and removes it from queue listings.

Standard operational commands:

| Action | Command |
|---|---|
| Pause / Resume job | `cueman -pause <job>` / `cueman -resume <job>` |
| Terminate job (Remove from queue) | `cueman -force -term <job>` |
| Retry failed frames | `cueman -force -retry <job>` |
| Eat (drop) frames without retry | `cueman -force -eat <job>` |
| Kill running frames | `cueman -force -kill <job>` |
| List frames and status | `cueman -lf <job>` |
| Lock / Unlock node | `cueadmin -force -lock -host <name>` / `-unlock` |
| Move node allocation | `cueadmin -force -move <alloc> -host <name>` |

Filter `cueman` operations with `-layer` and `-range` flags:

```bash
cueman -force -retry <job> -range 10-20
```

### Shows Cannot Be Deleted Once Jobs Are Submitted

Attempting to delete a show that has processed jobs:

```
deleteShow("inita")
→ DataIntegrityViolationException: DELETE FROM folder WHERE pk_show=?
```

Job history tables retain foreign key references to folders. Once a show processes jobs, it cannot be deleted. Deactivate it instead:

```python
show = opencue.api.findShow("inita")
for sub in show.getSubscriptions():
    sub.delete()
show.setActive(False)
```

Note: `opencue.api.deleteShow()` accepts the **show name** (despite documentation stating `show_id`). Passing IDs raises `EntityNotFoundException`. Plan show names carefully.

---

# Practical Pipeline Application: Two-Stage Houdini Rendering

A real-world chain dependency pipeline:

```
Stage 1   hython   Builds scene and exports USD       (1 frame)
   │     depend_all (LayerOnLayer)
   ▼
Stage 2   husk     Renders USD directly               (N frames, parallel)
```

Why separate into two stages: `husk` avoids loading full Houdini licenses and GUI dependencies, launching significantly faster than `hython`. Generating the USD scene once amortizes startup overhead across all frames.

## Implementation

### Wrapper Script

[`notes/deploy/node/husk-22.0.429.bat`](https://github.com/chordee/OpenCue/blob/9229923c/notes/deploy/node/husk-22.0.429.bat):

```bat
"%HB%\husk.exe" --make-output-path -f %CUE_IFRAME% -n 1 -o "%OUTPUT%" "%SCENE%"
```

`-f %CUE_IFRAME% -n 1` renders a single frame based on the RQD injected variable.

### Stage 1 Script

[`notes/sandbox/lab/stage1_export_usd.py`](lab/stage1_export_usd.py) creates LOP geometry and exports via `usd_rop`. Crucially, configure `trange=1` with valid `f1` and `f2` frame ranges so the exported USD caches full animated sequences rather than static frames.

### Submission Script

[`notes/sandbox/lab/submit_houdini_twostage.py`](lab/submit_houdini_twostage.py):

```python
stage2.depend_all(stage1)      # LayerOnLayer
```

Submitted in paused state and resumed once wired up.

## Verification Results

Layer structure:

```
 layer       | frame            | State
-------------+------------------+---------
 export_usd  | 0001-export_usd  | WAITING
 husk_render | 0001-husk_render | DEPEND
 husk_render | 0002-husk_render | DEPEND
 husk_render | 0003-husk_render | DEPEND
```

Sampling timeline:

| Sample | export_usd | husk/0001 | husk/0002 | husk/0003 |
|---|---|---|---|---|
| 2 | **RUNNING** | DEPEND | DEPEND | DEPEND |
| **3** | **SUCCEEDED** | **RUNNING** | **WAITING** | **WAITING** |
| 4 | SUCCEEDED | SUCCEEDED | SUCCEEDED | RUNNING |
| 5 | SUCCEEDED | SUCCEEDED | SUCCEEDED | SUCCEEDED |

In Sample 3, completing `export_usd` transitions husk frames from `DEPEND` to `WAITING`, followed by dispatching to `RUNNING`. Frames dispatch in batches according to Cuebot scheduler cycles.

Output verification:
- `twostage.usda`: 105,498 bytes
- `twostage.0001.exr`: 202,525 bytes
- `twostage.0002.exr`: 434,158 bytes
- `twostage.0003.exr`: 1,064,070 bytes

Varying file sizes confirm animated topology across frames.

## Pipeline Extensibility

Supported dependency types in `pyoutline/outline/depend.py:44-48`:
- `LayerOnLayer`: Downstream layer begins after entire upstream layer succeeds.
- `FrameByFrame`: Downstream frame N begins as soon as upstream frame N succeeds.
- `PreviousFrame`: Frame N waits for frame N-1 (Sequential simulation dependencies).
- `LayerOnAny`: Clears when any single upstream frame succeeds.
- `LayerOnSimFrame`: Simulation specialized dependency.

`FrameByFrame` is highly efficient for sequence rendering: frame 1 renders immediately once USD frame 1 finishes caching, overlapping cache and render phases.
