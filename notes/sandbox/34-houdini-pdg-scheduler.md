# 34 — OpenCue Scheduler Architecture for Houdini PDG

Executing Houdini TOP network work items across an OpenCue render farm. Architecture design, implementation, and local empirical verification. Conducted 2026-09-25.

---

## 1. Goals & Scope

**Operational Workflow**: A dedicated OpenCue scheduler node is placed within the TOP network; artists **cook one TOP node at a time**. Once upstream nodes finish cooking, all work items for the active node become runnable simultaneously and are bundled into **a single OpenCue job**, where each work item corresponds to one frame. Upon job completion, the artist cooks subsequent nodes.

Work item results (output files, attributes) are reported back to PDG via callbacks, remaining accessible to downstream nodes identically to local cooks.

**Explicitly Excluded from Initial Release**:

| Feature | Rationale |
|---|---|
| Submit Graph As Job (Unattended background graph cook) | Artists agreed to keep Houdini interactive sessions open until cook completes |
| PDG MQ | Telemetry reports directly back to the submitting Houdini process; see Section 4 |
| Static Cooking (`onScheduleStatic`) | Omitted by native commercial farm schedulers; see Section 2 |
| Multi-node graph coalescing into single jobs | Render-per-node workflow makes this redundant |

---

## 2. Reference: Houdini Built-in Schedulers

Source implementations located in `$HFS/houdini/pdg/types/schedulers/`: `tbdeadline.py` (Deadline), `prtractor.py` (Tractor), `local.py` (Local), `pythonscheduler.py` (Python Scheduler); HQueue located at `$HFS/houdini/pdg/types/houdini/hqueue.py`.

| Feature | Deadline | Tractor | OpenCue Architecture Limits |
|---|---|---|---|
| Work Item Mapping | Single root job; incoming items **appended as frames**, each reading distinct task files | Single job; work items **added dynamically as tasks** | OpenCue jobs **cannot append frames or layers post-submission** (`proto/src/job.proto` lacks append APIs); batches must map 1:1 to jobs |
| Telemetry Callbacks | Dedicated PDG MQ daemon (`pdgmq.py`) on farm; submitting client polls MQ | Same as left | Direct TCP callbacks in initial release |
| `onScheduleStatic` | Empty `pass` | Empty `pass` | Not implemented |

Even when work items are generated statically, standard cook workflows invoke `onSchedule` incrementally as upstream dependencies resolve.

---

## 3. System Architecture

Comprises three scripts adhering to the core principle: "Inside DCC run DCC APIs only; OpenCue logic executes in venv Python": Houdini 22 bundles Python 3.13, the venv runs Python 3.11, and `opencue` requires binary gRPC.

| Component | Execution Context | Responsibility |
|---|---|---|
| `opencuescheduler.py` | Submitting Houdini session | Subclass of `PyScheduler`, registered as a native PDG scheduler type |
| `opencue_pdg_helper.py` | Submitting host venv (Subprocess communicating via JSON) | Dispatches jobs, queries frame states, cancels jobs or frames |
| `opencue_pdg_task.py` | Render farm node (`ocrun houdini <version> hython`) | Reads task file for target frame, applies environment variables, executes work item command |

Installed into the Houdini tools release directory (`releases\<version>\client\houdini\`), with `opencuescheduler.py` residing under `pdg/types/` and added to `HOUDINI_PATH` via package definition.

### Execution Flow

1. **`onSchedule(work_item)`**: Resolves command tokens, generates item environment variables, serializes work item (`createJobDirsAndSerializeWorkItems`), writes commands and variables to task files, and queues items for submission.
2. **`onTick()`**:
   - When the pending queue remains stable without new additions for a threshold duration (e.g., 3s), generates job specifications and invokes helper to dispatch a job: frames `1..N` map to queued work items.
   - Periodically queries frame states via helper (e.g., every 10s). If frames transition to DEAD without reporting work item status (e.g., hard process crash), marks work items as failed.
3. **Status Reporting**: Work item tasks report completion and status back to the submitting callback server using PDG's `pdgcmd`.
4. **`onStopCook(cancel)` / `onCancelWorkItems`**: Cancels corresponding jobs or frames via helper.

Frame execution command format:

```
ocrun houdini <version> hython <release_dir>/opencue_pdg_task.py <task_dir> #IFRAME#
```

---

## 4. Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| **Each frame reads an independent task file** | OpenCue scopes environment variables to layers, whereas PDG scopes variables to individual work items (`PDG_ITEM_NAME`, `PDG_ITEM_ID`). A single layer cannot host divergent item variables. Matches Deadline's design. |
| **Pending submission debounce delay** | Work items for a single node may emit across multiple clock ticks; dispatching immediately would fragment a node across numerous jobs. |
| **Direct callback to submitting Houdini session** (`CallbackServerMixin`) | Simplest operational model. Requires render nodes to reach the artist workstation: callback server binds to a defined port range (`custom_port_range`) permitted through firewalls; workstation hostnames must resolve across the farm network. |
| **Shared storage workspace** (defaults to `$HIP`) | Task files, serialized work items, and PDG support scripts must be accessible across render nodes. Standardized drive letters across Windows workstations eliminate path mapping overhead. |
| **Workstation environment isolation** | The Local scheduler duplicates the host Houdini environment. The OpenCue scheduler intentionally passes only PDG-specific variables and work item variables, adhering to farm isolation standards ([`02` Section 4](../deploy/02-render-nodes.md#host-environment-variables-forwarded-to-frames)). |
| **Service resolution via version tags** | Rejects cooks if matching tags cannot be resolved, ensuring version parity. |
| **Job naming schema incorporates hip name, TOP node name, and batch counter** | A single cook can trigger multiple jobs; clear names facilitate tracking in CueGUI. |

---

## 5. Implementation Verification Details

| Technical Challenge | Resolution |
|---|---|
| Custom Scheduler HDA Requirement | Not required. Placing Python files under `pdg/types/` registers the `pdg_opencuescheduler` node type in TOP networks automatically, exposing standard parameters like `pdg_workingdir` and RPC settings. |
| `__PDG_HYTHON__` Token Substitution | ROP node commands emit `"__PDG_HYTHON__" "__PDG_SCRIPTDIR__/rop.py" json`: outer quotes prevent substituting with multi-token `ocrun ...` strings. Retained `__PDG_HYTHON__`, `__PDG_PYTHON__`, and `__PDG_HFS__` tokens; `opencue_pdg_task.py` resolves paths dynamically via node `dcc.toml` and applies `[env]` configurations. |
| PDG Runtime Scripts (`pdgcmd.py`, etc.) | `onStartCook` invokes `_copyJobSupportFiles()`, copying runtime scripts to `scripts/` in the shared working directory for direct farm execution. |
| Success Criteria Evaluation | Evaluated via frame state: `SUCCEEDED` reports success; `DEAD` or `EATEN` reports failure (matching Local scheduler exit-code semantics). Output files and attributes are transmitted via callback server prior to frame termination. |
| Disabling OpenCue Automatic Retries | **Disabled** (`maxretries=0`). Pyoutline defaults to 2 retries; retrying causes output artifacts to be registered multiple times and delays failure reporting. |
| Callback Server Address Binding | Binds to `0.0.0.0`, publishing the workstation's FQDN; ports restricted via scheduler Callback Port settings. |
| Querying Frame Limits | Pycue frame queries default to 500 items; helper specifies limits dynamically based on total task count. |
| Frame Log Links (`getLogURI`) | Formatted via `urllib.parse.urlunparse`, matching Local scheduler conventions. For UNC log paths, standard `file://host/...` URLs render blank in the Work Item Output Log panel; `file:////host/...` renders correctly. |

---

## 6. Verification Results

Test scene generated via [`lab/make_pdg_test_scene.py`](lab/make_pdg_test_scene.py): Generic Generator → `work` (Python Script, external process, Hython) → `collect` (Python Script, external process, PDG Python). Cooked via hython using [`lab/cook_pdg_node.py`](lab/cook_pdg_node.py) and [`lab/cancel_pdg_cook.py`](lab/cancel_pdg_cook.py). Tested with Houdini 22.0.429 on local 8-core node.

| Test Scenario | Result |
|---|---|
| Cook Initial Node (5 items) | Dispatched 5-frame job; all succeeded; output file paths and attribute `square` returned to PDG |
| Cook Downstream Node | `collect` inherited upstream attributes and output paths; `__PDG_PYTHON__` resolved to node's `python313\python.exe` |
| Partial Work Item Failures (Exit 1) | Only failed items marked red; surviving items succeeded |
| Frame Terminated Prior to Callback | Item evaluated as failed immediately without waiting for 90s timeout |
| Mid-Cook Cancellation | PDG reflected cancellation; OpenCue job was killed cleanly; zero orphaned processes on node |
| **300 Work Items** | **Single 300-frame job**; all succeeded in 820s (~22s per frame, dominated by hython startup overhead) |
| Houdini 21.0.729 via Package (`2026.09.25.3`) | All 5 succeeded; service automatically resolved to `houdini2107` |
| **Interactive Houdini GUI** (21 & 22 cooking `work` and `collect` sequentially) | Dispatched 1 job per node (20 frames, 5 frames); all succeeded; upstream nodes avoided re-cooking in active session |
| Work Item Output Log Panel | Displayed active RQD frame log (following URI formatting correction) |
| Simultaneous Runnable Nodes (Merge branching) | Dispatches independent jobs per node (fixed earlier bug where items merged into single malformed job) |
| Job Killed from OpenCue Dashboard | Unfinished frames halted in WAITING; helper reported remaining frames as `KILLED`; cook completed cleanly with failed items |

### Physical Render Node Execution

Test scene generated via [`lab/make_pdg_rop_scene.py`](lab/make_pdg_rop_scene.py) based on `hou_submit_test.hip`. Tested on Houdini 22.0.429.

| Node Setup | Configuration | Outcome |
|---|---|---|
| ROP Geometry TOP → `/obj/geo1/box1` | Frame Range 1-5 | 5 work items, 5-frame job; output files verified |
| ROP Fetch → `/obj/geo1/rop_out` (SOP ROP Geometry) | ROP Node Configuration | **Single** work item evaluated all 3 frames in 1 task, emitting 3 files |
| ROP Fetch → `/stage/karma_render/rop_usdrender` (Karma) | Frame Range 1-3 | 3 work items, 3-frame job; emitted 3 EXR files |

Key PDG operational characteristics (native behaviors independent of scheduler):

- ROP TOP nodes default to **Evaluate Using: Single Frame** (renders 1 frame only). To distribute frames across the farm, set to Frame Range.
- **ROP Node Configuration collapses frame ranges into a single work item**, occupying 1 frame task without distributing across nodes.
- Karma (USD Render ROP) work items report output paths as `__render__.usd` rather than image files; downstream nodes must reference rendered images directly.
- When working directories diverge from `$HIP`, PDG **copies the hip file into the working directory**; farm nodes execute this copy, freezing scene state at cook time. This differs from standard submission tools that read live scene files directly.

Cooking downstream nodes in a fresh hython process triggers an upstream re-cook (dispatching extra jobs); cooking sequentially within an active interactive session does not.

### Pending Verification Items

- Callback server connectivity and firewall traversal when render nodes and artist workstations reside on distinct physical subnets.
