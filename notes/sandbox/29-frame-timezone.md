# 29 — Frame Timezone Hardcoded to US Pacific Time (PST/PDT)

Production configuration is documented in [`notes/deploy/02-render-nodes.md` Section 4](../deploy/02-render-nodes.md#4-configuring-rqdconf); this document details the investigation and verification.

Environment: Local Windows RQD host, 2026-09-25.

---

## 1. Discovery

While auditing crash telemetry for [`28`](28-maya-crash-reporting.md), CER log timestamps inside child frames trailed host local time by 15 hours, whereas tests executed directly from the terminal matched local time.

The root cause was located in RQD (`__createEnvVariables()` in `rqd/rqd/rqcore.py`):

```python
self.frameEnv["TZ"] = self.rqCore.machine.getTimezone()
```

```python
# rqd/rqd/rqmachine.py
def getTimezone(self):
    if time.tzname[0] == 'IST':
        return 'IST'
    return 'PST8PDT'
```

Except on hosts whose timezone resolves to `IST`, **all frames are unconditionally assigned `TZ=PST8PDT`**, ignoring host OS timezone configurations.

---

## 2. Empirical Verification

Executing a Python script (`C:\opencue\tmp\tzcheck.py`) via hython inside an active frame to inspect `TZ` and local system time:

| State | `TZ` Value | Local Time Inside Frame | Host System Time |
|---|---|---|---|
| Prior to Fix | `'PST8PDT'` | **2026-09-24 10:22** | 2026-09-25 01:22 |
| Post Fix | `''` | 2026-09-25 01:22 | 2026-09-25 01:22 |

Prior to the fix, the reported calendar date itself was offset. Impact scope:

- Render scripts generating filenames or directory hierarchies based on local time (e.g., date-stamped output folders).
- Timestamps logged by DCC engines and plugins mismatched against host OS and Cuebot log timelines.
- File modification timestamps on disk remain unaffected (Windows records timestamps in UTC).

---

## 3. Resolution

Add `TZ` to the `[UseHostEnvVar]` section of `rqd.conf`:

```ini
[UseHostEnvVar]
ALLUSERSPROFILE
TZ
```

`rqcore.py` sets `PST8PDT` initially, but subsequently overrides it when merging variables defined under `[UseHostEnvVar]`. Windows hosts typically do not define a `TZ` variable, causing RQD to assign an empty string (`os.environ.get(variable, '')`); an empty `TZ` prompts applications on Windows to inherit host system timezone settings.

Dispatched a Maya frame (`-r sw`) post-fix: completed in 13 seconds with no adverse side effects.

---

## 4. Pending Verification Items

- Internal timestamp reporting inside Maya and Nuke (verified via hython standard library Python).
- Ensuring headless Windows service execution environments for RQD similarly omit `TZ`.
- Linux render nodes: on Linux, an empty `TZ` evaluates to UTC rather than system local time. This configuration **cannot be applied identically to Linux**; Linux environments require setting explicit timezone strings (e.g., `Asia/Taipei`) in RQD's launch environment prior to including `TZ` in `[UseHostEnvVar]`.
