# 21 — Services and OpenCue Resource Model

Form parameters in submission tools (Layer, Username, Facility, Service, Dependency Type) represent distinct facets of OpenCue's unified resource model. This guide outlines their mechanics and demonstrates centralized service configuration as a superior alternative to manual tag management.

---

## 1. Hierarchy: Job → Layer → Frame

```
Job    testing-testshot-chordee_houdini_render        Submitted unit of work
 ├─ Layer  export_usd     range 1-1    Command A      Task group sharing command & resources
 └─ Layer  husk_render    range 1-3    Command B
     ├─ Frame 0001   <- Smallest unit of execution dispatched to a host
     ├─ Frame 0002
     ├─ Frame 0003
```

**A Layer groups frames sharing identical command syntax and hardware requirements.**
- Multi-stage pipelines (USD caching → husk rendering) use separate layers.
- Multi-AOV rendering divides across layers.
- Dependencies are declared between layers.

**Layer Name** appears in frame log directory paths and CueGUI listings. Names must contain **at least 3 characters**; shorter names are rejected by Cuebot (`The layer name must be at least 3 characters`).

## 2. Username

Stored in `job.str_user`, serving three purposes:
1. Linux RQD uses it to execute frames under matching system users (see UID collision in [`04` Pitfall #4](04-deployment-process.md#pitfall-4-rqd-fails-to-create-user-uid-collision)).
2. CueGUI uses it for `selectMine` filtering.
3. Accounting and auditing.

Submitting unrecognized usernames to Linux nodes triggers `useradd` failures and frame aborts.

## 3. Facility

Represents physical site infrastructure (e.g., `local`, `cloud`, `dev`). Allocation names prefix facility names: `local.general`, `cloud.general`.

Facility constraints are strictly enforced; mismatches fail silently without diagnostic errors (see [`12` Pitfall #17](12-real-dcc-rendering.md#pitfall-17-facility-mismatches-silently-prevent-job-dispatching) and [`17` Scenario 20](17-troubleshooting.md#scenario-20-newly-joined-node-never-receives-work)).

## 4. Services: Resource and Tag Templates

**Services define default resource allocations and dispatch tags for classes of work.** OpenCue includes 10 default services:

```
 service     | cores_min | mem_mb |      str_tags
-------------+-----------+--------+--------------------------
 arnold      |       100 |   3276 | general | desktop
 default     |       100 |   3276 | general | desktop
 houdini     |       100 |   3276 | general | desktop
 katana      |       100 |   2048 | general | desktop | util
 maya        |       100 |   2048 | general | desktop
 nuke        |       100 |   2048 | general | desktop
 postprocess |        10 |    512 | util
 preprocess  |        10 |    384 | util
 prman       |       100 |   3276 | general | desktop
 shell       |       100 |   3276 | general | util
```

(`cores_min = 100` represents 100% of a core, or 1 core).

### Origin of Default Layer Tags

`layer.str_tags` inherits default values from assigned services:

| Submission Method | Assigned Service | Inherited Tags |
|---|---|---|
| pyoutline `Shell` | `shell` | `general \| util` |
| CueWeb Form | `default` | `general \| desktop` |

Explicit `tags=[...]` definitions in submissions override service defaults.

## 5. Custom Services: Centralized Configuration Over Manual Tags

Specifying version tags manually per submission script scatters memory and core configurations across pipeline tools. Furthermore, **CueWeb submission forms lack tag inputs**.

Defining custom services solves these challenges centrally.

### Programmatic Creation

```python
import opencue
from opencue_proto import service_pb2

opencue.api.createService(service_pb2.Service(
    name="houdini2204",
    threadable=False,
    min_cores=100,                     # 100 = 1 Core
    max_cores=0,                       # 0 = Unlimited
    min_memory=4 * 1024 * 1024,        # 4 GB (expressed in KB)
    min_gpu_memory=0,
    tags=["houdini_22_0_429"],
    timeout=0, timeout_llu=0,
    min_memory_increase=2 * 1024 * 1024,   # Mandatory: Must be > 0
))
```

Services can also be managed visually in CueGUI or CueWeb.

### API Specifics

1. **`min_memory_increase` is mandatory and must be > 0**, otherwise raising `ValueError: Minimum memory increase must be > 0`.
2. **`opencue.api.getService(name)` returns `None` for missing entities rather than raising exceptions**. Verify existence using:
   ```python
   if opencue.api.getService(name) is not None:
   ```

### Verification: Layer Inheritance

Created three test services: `houdini2204` (4096 MB), `maya2027` (2048 MB), `nuke17` (2048 MB).

Submitted jobs specifying service names only, without tags or memory parameters:

```python
Shell("svc_render",
      command=[...],
      range="1-2",
      service="houdini2204")
```

Outcome:
- Frames inherited `tags = ["houdini_22_0_429"]` and `memory = 4096 MB`.
- Tasks dispatched exclusively to Windows nodes carrying `houdini_22_0_429`.

### Recommended Studio Service Blueprint

| Service | Tags | Memory | Purpose |
|---|---|---|---|
| `houdini2204` | `houdini_22_0_429` | 4 GB | Houdini 22.0.429 renders |
| `houdini2107` | `houdini_21_0_729` | 4 GB | Houdini 21.0.729 legacy jobs |
| `maya2027` | `maya_2027` | 2 GB | Maya 2027 renders |
| `nuke17` | `nuke_17_0v1` | 2 GB | Nuke 17 compositing |
| `husk2204` | `houdini_22_0_429` | 3 GB | Standalone husk USD renders |

Benefits:
- Centralized resource sizing (adjust memory in one location).
- Simplified submissions (artists select services rather than memorizing tags).
- Unlocks browser-based CueWeb submissions via service dropdowns.

## 6. Dependency Types Summary

In `pyoutline/outline/depend.py:44-48`:
- `LayerOnLayer`: Complete layer blocks complete downstream layer.
- `FrameByFrame`: Downstream frame N unblocks upon upstream frame N completion.
- `PreviousFrame`: Frame N waits for frame N-1 (simulation dependencies).
- `LayerOnAny`: Clears when any frame in upstream layer succeeds.
- `LayerOnSimFrame`: Simulation specialized dependency.

## 7. Unified Dispatching Architecture

```
Facility  ──Constraint──> Dispatches exclusively to nodes in matching facility
   │
Service   ──Supplies────> Default tags / cores / memory
   │                            │
   │                      (Overridable at submission)
   ▼                            ▼
  Job ── os ──Constraint──> Dispatches exclusively to target operating system
   └─ Layer ── tags ──Match───> Evaluates host.str_tags via regex OR
        └─ Frame ──Dispatch─> Assigned to node satisfying all criteria
```

**Dispatching requires simultaneous satisfaction of**: matching facility, matching OS, at least one matching tag, sufficient memory and cores, and unlocked host state.

Unsatisfied constraints fail silently without error output.
