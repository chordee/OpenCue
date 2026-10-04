# 28 — Autodesk Error Report Dialog Appearing After Maya Renders

Production configuration is documented in [`notes/deploy/02-render-nodes.md` Section 4](../deploy/02-render-nodes.md#4-configuring-rqdconf); this document details the investigation and root-cause verification.

Environment: Maya 2027, local Windows RQD host, 2026-09-25.

---

## 1. Symptoms

Executing [`lab/check_submit_tools.py`](lab/check_submit_tools.py) `--submit` caused an Autodesk Error Report modal dialog to appear on the desktop. Despite this dialog, both Maya frames completed with status SUCCEEDED, returned exit code 0, and produced valid rendered output images.

Frame log timestamps:

```
01:00:03  Frame execution begins
01:00:08  Scene C:/opencue/scenes/test.ma completed.
01:00:09  (CER dialog launches; see below)
01:00:25  Frame ends, exitStatus 0
```

The process crashed only after rendering finished; collecting crash telemetry extended frame execution by approximately 15 seconds.

---

## 2. Investigation

### 1. Persistent Pattern Across Render Tasks

Inspecting crash reports under `%LOCALAPPDATA%\Autodesk\CER\` for the product revealed timestamps matching every Maya render executed throughout the day:

| Timestamp | Crash Reports | Dispatched Job |
|---|---|---|
| 00:08 | 1 | `maya_render_2027` (Test run in [`26`](26-ocrun-wrapper.md)) |
| 00:10 | 2 | 2 frames submitted via submission GUI |
| 01:00 | 2 | 2 frames submitted via `check_maya` |

**Every Maya frame triggered a crash report.** The Windows Event Log recorded zero application crashes because the unhandled exception was intercepted internally by the CER handler.

### 2. Faulting Component Is Not Core Maya

Inspecting `cer.log` and associated dump metadata:

```
cer.dll Source    C:\Program Files (x86)\Common Files\Autodesk Shared\AdskLicensing\...\AdskLicensingAgent\cer.dll
UPI_PRODUCT       CLIC (Autodesk Licensing Module, CLMV2 6.33.1.911)
Exception Code    0xE06D7363 (Unhandled C++ exception)
Module            KERNELBASE.dll
Temp Directory    C:\opencue\tmp (Frame TMP variable)
```

The fault originated inside the **Autodesk Licensing Module** loaded within Maya's process space, which triggered its own independent CER binary.

### 3. Why `MAYA_DISABLE_CER` Failed

- `ocrun` verified proper injection of `MAYA_DISABLE_CER=1` into Maya (validated via `ocrun maya 2027 mayapy`).
- Within Maya 2027's `bin` directory, this variable is read exclusively by `ExtensionLayer.dll` and ATF-related libraries belonging to Maya core.
- The licensing module CER resides in a separate common runtime directory and ignores Maya-specific configuration flags.

### 4. Pinpointing Missing Environment Variable

RQD isolates frame environments drastically (`__createEnvVariables()` in `rqcore.py`; on Windows providing only `SYSTEMROOT`, `APPDATA`, `TMP`, `COMMONPROGRAMFILES`, `SYSTEMDRIVE`, and PATH). Executing `ocrun maya 2027 Render -r sw -s 1 -e 1 ...` directly while varying environment variables:

| Environment | New Crash Reports Emitted |
|---|---|
| Complete Interactive User Environment | 0 |
| Simulated RQD Baseline Environment | **1** |
| RQD + 16 Common System Variables | 0 |
| RQD + `LOCALAPPDATA`, `USERPROFILE`, `PROGRAMDATA` | 1 |
| RQD + `USERNAME` | 1 |
| RQD + `COMPUTERNAME` | 1 |
| RQD + `USERDOMAIN` | 1 |
| RQD + `PROGRAMFILES`, `ProgramFiles(x86)` | 1 |
| RQD + **`ALLUSERSPROFILE`** | **0** |

**The sole missing dependency was `ALLUSERSPROFILE`.** Providing `PROGRAMDATA` (which evaluates to the exact same path on Windows) was ineffective; the licensing subsystem specifically queries `ALLUSERSPROFILE`.

---

## 3. Resolution

RQD supports forwarding designated host variables to frame child processes via the `[UseHostEnvVar]` section in `rqd.conf` (`rqconstants.py` parses this as `RQD_HOST_ENV_VARS`, replicated by `rqcore.py` during frame environment synthesis):

```ini
[UseHostEnvVar]
ALLUSERSPROFILE
```

This configuration was integrated into [`node/rqd-windows.conf`](../deploy/node/rqd-windows.conf). Handling this at the RQD level rather than inside `ocrun` ensures consistent resolution across all frame jobs using the host's native path without guesswork.

Variables like `USERPROFILE` and `LOCALAPPDATA` were deliberately **omitted**: pointing to interactive user directories exposes frame renders to artist-specific Maya preferences and local plugins, leading to non-deterministic render outputs across workstations.

### Verification

After restarting RQD, dispatched 3 Maya frames ([`lab/submit_dcc.py`](lab/submit_dcc.py) `maya --frames 1-3`):

| Metric | Prior to Resolution | Post Resolution |
|---|---|---|
| Duration per Frame | ~22 seconds | 14–15 seconds |
| Licensing Module Crashes (`launching ... senddmp.exe` in `cer.log`) | 1 per frame | **0** |
| Desktop Crash Dialogs | 1 per frame | None |

Crash detection requires tracking `senddmp` invocations rather than `cer started`: the licensing module initializes CER on load and logs `cer started` unconditionally. Subsequent Arnold renders ([`30`](30-arnold-licensing.md)) log this line per frame without generating exception codes, dump files, or UI prompts.

---

## 4. Relationship with Note 25

The crash dialogs noted in [`25` Section 5](25-maya-submission.md#5-issues-identified-during-manual-testing) were originally attributed entirely to RAM exhaustion. Windows event logs recorded `mayabatch.exe` crash `0xc0000005`, distinct from this document's `0xE06D7363`, confirming memory exhaustion did occur. However, licensing CER logs confirmed that both manual tests also suffered from licensing module crashes:

| Test (Local Time) | Dumps Emitted by Licensing Module |
|---|---|
| ~22:00 (Memory exhaustion scenario) | 17 |
| 22:31 (Event log recorded zero crashes) | 8 |

Both issues coincided. Timestamps in `cer.log` were logged in PDT (because RQD enforced `TZ` on child frames), trailing local time by 15 hours. CLI tests executed outside RQD logged in local host time.

---

## 5. Pending Verification Items

- Additional licensing requirements beyond `ALLUSERSPROFILE` under network floating licenses or server disconnection states.
- Whether `MAYA_DISABLE_CER` successfully suppresses modal UI popups in the event of genuine Maya core crashes.
- Other Autodesk software products (Arnold Standalone) and legacy Maya releases.
