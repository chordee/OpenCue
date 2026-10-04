# 09 — NIMBY and Hybrid Fleet Operations

Operational Baseline:
- Render nodes encompass **two distinct roles**: artist workstations and dedicated headless render nodes.
- Workstation policy enforces **after-hours harvesting only**, without preemption during working hours.

## What is NIMBY?

**N**ot **I**n **M**y **B**ack **Y**ard — Named from the user's perspective: "When I am actively using my workstation, dispatch render jobs elsewhere."

Enables studios to harvest desktop workstation computing power while protecting interactive artist responsiveness.

OpenCue provides two **distinct and independent** components:

### RQD NIMBY (Automated, Real-Time Input Detection)

Built directly into RQD, using `pynput` to monitor keyboard and mouse events:
- Detects user input → locks host immediately.
- Idles beyond `MINIMUM_IDLE` → unlocks host automatically.
- **Terminates currently running frames immediately upon input detection.**

The third item is the trade-off: The moment an artist moves the mouse, running frames are killed and requeued, **wasting rendered compute**.

### CueNIMBY (Manual Control, Scheduling & Desktop Notifications)

An independent Qt system tray application communicating directly with the Cuebot API without touching RQD:
- System tray icon showing availability status.
- Manual toggle ("Disable rendering while I run local simulations").
- Desktop notifications.
- **Time-based scheduling**.

## Why CueNIMBY Scheduling Is Preferred Over RQD NIMBY for "After-Hours Harvesting"

RQD NIMBY is **reactive**: During the workday, frames are repeatedly scheduled and killed as artists interact, degrading efficiency and potentially disrupting workstations.

CueNIMBY scheduling provides **time-window gating**: Workstations are disabled throughout office hours, leaving artists undisturbed. Workstations join the render pool only after business hours.

Configuration file location: `~/.config/opencue/cuenimby.json` (on Windows: `C:\Users\<user>\.config\opencue\cuenimby.json`).

Template available at [`notes/deploy/node/cuenimby-workstation.json`](../deploy/node/cuenimby-workstation.json):

```json
{
  "cuebot_host": "localhost",
  "cuebot_port": 8443,
  "hostname": "LAPTOP-ULJICLO8",
  "poll_interval": 5,
  "scheduler_enabled": true,
  "schedule": {
    "monday":    { "start": "09:00", "end": "18:00", "state": "disabled" },
    ...
  }
}
```

### Scheduling Evaluation Logic (`cuenimby/scheduler.py:66-87`)

```python
if start_time <= current_time <= end_time:
    return desired_state
# Outside scheduled period - return opposite state
return "available" if desired_state == "disabled" else "disabled"
```

Key principles:

1. **Applies specified state during scheduled window; inverts state outside window.**
   Therefore, `09:00-18:00 disabled` automatically implies available outside business hours.
2. **Returns None when no schedule is defined for the day.**
   Omitting weekends causes the scheduler to remain passive — maintaining Friday evening's available state through Monday morning.
3. **Cross-midnight intervals fail completely** — see Pitfall #11 below.
   Express schedules using non-crossing disabled windows (`09:00-18:00 disabled`) rather than `18:00-09:00 available`.

## Empirical Verification

Test execution: Wednesday 10:06 (within the 09:00-18:00 window).

### 1. Working Hours → Automated Lock

Launched CueNIMBY:

```
cuenimby.scheduler - INFO - Scheduler changing state to: disabled
cuenimby.monitor   - INFO - State changed: Available -> 🔒 Host locked
cuenimby.monitor   - INFO - Host locked
```

Cuebot perspective:

```
Host             ... State  Locked    Alloc
LAPTOP-ULJICLO8  ... UP     LOCKED    local.desktop
```

Submitted job → **3 frames remained in WAITING, with zero dispatches**. Working as designed.

### 2. After Hours → Automated Unlock

Adjusted Wednesday window to `01:00-09:00`; current time 10:06 fell outside the window:

```
cuenimby.scheduler - INFO - Scheduler changing state to: available
cuenimby.monitor   - INFO - State changed: 🔒 Host locked -> Available
cuenimby.monitor   - INFO - Host unlocked
```

Cuebot `Locked` status reverted to `OPEN`.

## Pitfall #10: Moving to `desktop` Allocation Blocks Default Jobs

After unlocking, frames **still remained in WAITING**. Investigation revealed this was caused by **tag mismatches** rather than NIMBY:

Cuebot matches layer tags against host tags:

```sql
-- layer
str_name   | str_tags
test_layer | general | util      ← pyoutline default

-- host (after moving to local.desktop)
str_tag     | str_tag_type
desktop     | ALLOC
rqdv-dev    | HARDWARE
desktop     | HARDWARE
windows     | HARDWARE
```

The host lacked both `general` and `util` tags → never dispatched tasks.

**This is a critical matching rule in hybrid fleets that fails with zero diagnostic output** — host displays UP / OPEN, job shows PENDING, yet frames remain static.

### Solution

Append tags in RQD configuration:

```ini
RQD_TAGS = general
```

After restarting RQD:

```
str_tag     | str_tag_type
general     | HARDWARE      ← Added
desktop     | ALLOC
...
```

The 3 pending frames immediately transitioned to RUNNING and finished with SUCCEEDED.

### Two Design Strategies

| Strategy | Implementation | Use Case |
|---|---|---|
| **Workstations join general pool** | Workstations configure `RQD_TAGS = general`, relying entirely on CueNIMBY scheduling | After-hours harvesting — expands farm capacity overnight for all standard jobs |
| **Workstations dedicated to specific jobs** | Workstations omit `general`; jobs submitted must explicitly require `desktop` tag | Isolates risk of workstation interruption to low-priority batches |

**The first strategy was adopted**, as after-hours workstations are completely offline during daytime and fully available at night.

## Configuration Comparison Across Node Roles

| Setting | Artist Workstation | Dedicated Render Node |
|---|---|---|
| `OVERRIDE_NIMBY` | `False` (Controlled by CueNIMBY schedule) | `False` |
| `OVERRIDE_IS_DESKTOP` | `True` | `False` |
| `RQD_TAGS` | `general` | `general` |
| Allocation | `local.desktop` | `local.general` |
| CueNIMBY | **Installed**, manages schedules & tray UI | Not needed |
| Startup Mechanism | User logon trigger, **must run in user session** | **Windows Service** (runs headless) |
| `OVERRIDE_CORES` | Reserve cores for artist if needed | Maximum cores |

**Regarding `OVERRIDE_NIMBY`**: With time-window harvesting, built-in RQD NIMBY can be disabled since workstations are empty after hours. If overtime work occurs, both can run concurrently (CueNIMBY manages schedule, RQD NIMBY acts as fail-safe), accepting frame terminations.

**Dedicated render nodes are straightforward**: Free from Session 0 limitations, they run as native Windows Services.

## Unverified Items at Initial Testing

> **Note**: This section reflects findings at the time of initial testing. Several items have since been validated.
> **Refer to [`19-verification-summary.md`](19-verification-summary.md) for the definitive status matrix.**

| Item | Notes |
|---|---|
| System tray UI | CueNIMBY ran in hidden window; visual tray behavior requires manual inspection |
| Manual user toggles | Validated automated scheduling; manual user overrides require testing |
| RQD NIMBY input detection | Real-time keyboard/mouse termination behavior under `OVERRIDE_NIMBY = True` |
| Multi-role dispatching | Dual-role concurrent dispatching with dedicated render nodes |

## Pitfall #11: Schedules Crossing Midnight Fail Completely

**Schedule rules must avoid spanning across midnight.** This is an empirical limitation.

`scheduler.py:83` performs standard range comparison:

```python
if start_time <= current_time <= end_time:
    return desired_state
return "available" if desired_state == "disabled" else "disabled"
```

When spanning midnight, `start > end`, making the condition **impossible to satisfy**. The check falls through to the opposite return value 24 hours a day.

Empirical verification (mocked timestamps against real `_check_schedule()`):

| Specification | Time | Expected | Actual |
|---|---|---|---|
| `09:00-18:00 disabled` | 10:00 | disabled | disabled |
| `09:00-18:00 disabled` | 20:00 | available | available |
| `18:00-09:00 available` | 20:00 | available | **disabled** |
| `18:00-09:00 available` | 02:00 | available | **disabled** |
| `22:00-06:00 disabled` | 23:00 | disabled | **available** |
| `22:00-06:00 disabled` | 03:00 | disabled | **available** |

Both error modes produce critical failures:
- `18:00-09:00 available` → Workstation is **never borrowed**, quietly reducing capacity.
- `22:00-06:00 disabled` → Workstation **opens for rendering when explicitly forbidden**.

### Correct Specification

Leverage state inversion outside defined windows using **non-crossing disabled intervals**:

| Requirement | Correct Specification | Incorrect Specification |
|---|---|---|
| Harvest after hours | `09:00-18:00 disabled` | `18:00-09:00 available` |
| Prohibit overnight harvesting | Cannot be expressed in a single rule | `22:00-06:00 disabled` |

Root cause and suggested fixes detailed in [`05-upstream-issues.md` Issue #12](05-upstream-issues.md#12-cuenimby-scheduler-cannot-handle-windows-across-midnight-and-invalidation-inverts-intended-behavior).

## Workstation Startup Scripts Must Launch Both RQD and CueNIMBY

[`notes/deploy/node/rqd-start.bat`](../deploy/node/rqd-start.bat) originally launched only `rqd.exe`. On workstations, omitting CueNIMBY leaves machines open 24 hours without scheduling.

The script supports role switching via `NODE_ROLE`:

```bat
set NODE_ROLE=workstation    REM or render

start "OpenCue RQD" /B "%OPENCUE_VENV%\Scripts\rqd.exe" >> ... 2>&1

if /I "%NODE_ROLE%"=="workstation" (
    ping -n 21 127.0.0.1 > nul
    start "CueNIMBY" /B "%OPENCUE_VENV%\Scripts\cuenimby.exe" >> ... 2>&1
)
```

### Pitfall #12: Startup Sequencing — RQD Must Be Ready First

Placing CueNIMBY before RQD caused:

```
failed to lock host: LAPTOP-ULJICLO8
RqdClientException: failed to lock host
```

**Reason**: Host locking is executed by **Cuebot calling back to RQD on port 8444**. If RQD is not yet listening, CueNIMBY's schedule application fails immediately.

Correct sequence: Launch RQD → wait for registration → launch CueNIMBY.

The script uses `ping -n 21 127.0.0.1` as a delay rather than `timeout`, which fails under redirected standard input in scheduled tasks.

### Pitfall #13: Batch Files Must Be Pure ASCII

Original scripts included UTF-8 comments. **`cmd.exe` parses batch files using the system OEM code page** (CP950 in Traditional Chinese environments). Interpreting UTF-8 as Big5 corrupted script syntax:

```
'tlocal' is not recognized as an internal or external command,
'workstation" (' is not recognized as an internal or external command,
```

Corrupted multi-byte characters broke parenthesis matching in `if (...)` blocks.

**Rule**: All batch scripts deployed to Windows nodes must strictly contain pure ASCII characters. Comments should reside in Markdown documentation. Verify using `file <path>` to confirm `ASCII text`.
