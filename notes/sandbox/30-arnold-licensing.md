# 30 — Arnold License Checkout Failure on Farm Reporting False Success

Production procedures are summarized in [`notes/deploy/02-render-nodes.md` Section 5](../deploy/02-render-nodes.md#5-invoking-dcc-binaries-via-ocrun); this document details the investigation and mitigation.

Environment: Maya 2027, MtoA (Arnold 7.5.1.1), local Windows RQD host, 2026-09-25.

---

## 1. Discovery

Re-submitting 2 frames of `scene_luffy_test.ma` (Arnold) via the updated Maya GUI plugin: both frames completed with status SUCCEEDED and exit code 0. However, frame logs recorded:

```
[clm.v1] generic license checkout error (22)
ERROR   | aborting render because this is a batch render and abort_on_license_fail option is enabled
```

**Arnold aborted without rendering any image data, yet OpenCue registered the frames as successful.**

Auditing past historical logs for this scene:

| Timestamp | Submission Method | Actual Result |
|---|---|---|
| 09-24 22:30 ([`25` Section 5](25-maya-submission.md#5-issues-identified-during-manual-testing), recorded as "3 frames succeeded, 98s each") | `Render-2027.bat` | All failed license checkouts; render aborted |
| 09-25 03:06 (Memory exhaustion test run) | `Render-2027.bat` | Same as above |
| 09-25 03:48 | `ocrun` | Same as above |

The anomaly was unrelated to `ocrun` or `[UseHostEnvVar]`: **Arnold had never actually rendered successfully on the farm from the beginning.**

---

## 2. Root Cause: License Server Environment Variables Missing from Frames

Executing `ocrun maya 2027 Render -r file -s 1 -e 1 -cam persp1 ...` directly while varying environment variables:

| Environment | License Error Present | Output Image Produced |
|---|---|---|
| Complete Interactive User Environment | None | Yes |
| RQD Environment (with `ALLUSERSPROFILE`, empty `TZ`) | **Yes** | No |
| RQD + `LOCALAPPDATA`, `USERPROFILE` | Yes | No |
| RQD + `USERNAME`, `COMPUTERNAME`, `USERDOMAIN`, `PROGRAMDATA`, `HOMEDRIVE`, `HOMEPATH` | Yes | No |
| RQD + `SOLIDANGLE_LICENSE` | None | **Yes** |
| RQD + `RLM_LICENSE` | None | **Yes** |

Arnold on this workstation obtains floating licenses via an RLM license server, designated in user environment variables as `SOLIDANGLE_LICENSE`. While accessible from interactive desktop sessions, it was stripped from child frames launched by RQD.

**Resolution**: Configure license variables in the `[env]` section of `dcc.toml` (anticipated in templates but previously unverified):

```toml
[env]
solidangle_LICENSE = '5053@<license-server>'
```

Rendering 1 frame via the farm post-configuration: completed in 20 seconds, produced valid rendered images, and emitted zero license errors. Prior frame durations of 50–100 seconds were caused by license checkout timeouts.

During the same window at 03:49, a licensing module breakpoint crash (`0x80000003`) occurred along the failure path; it disappeared once valid license configuration was restored.

---

## 3. False Success: Render.exe Returning Exit Code 0 on Arnold Abort

While license resolution fixed the immediate issue, false positive reporting is structurally hazardous: any condition that causes Arnold to abort (license server disconnect, pool exhaustion) would be marked as successful across the farm.

**Mitigation**: `ocrun` inspects Maya frame stdout line-by-line; encountering any of the following substrings (case-insensitive) forces the frame to terminate with exit code 1:

```
aborting render because
license checkout error
```

Output is streamed verbatim to the frame log, followed by an explanatory trailer:

```
[ocrun] failing the frame, the output reported: ... [clm.v1] generic license checkout error (22)
```

If the underlying process exits with a non-zero code, `ocrun` preserves that exit code unchanged.

### Empirical Verification

| Scenario | Result |
|---|---|
| Unit tests (Windows, Linux container) | 7 passed, validating error substring triggers code 1 and non-zero exit codes are preserved |
| Dispatched frame with license temporarily removed from `dcc.toml` | Exited 1; frame entered retry queue; log ended with `[ocrun] failing the frame` |
| Dispatched frame with valid license restored | Exited 0; completed in 20s with valid image output; no false positives |

---

## 4. Pending Verification Items

- Identifying silent failure modes in other DCC engines: Houdini (Karma) and Nuke have not exhibited zero-exit errors on failure, so stdout pattern filtering is currently restricted to Maya.
- Verifying log output patterns when license servers are reachable but all seats are consumed.
- Auditing requirements for `ADSKFLEX_LICENSE_FILE` or `foundry_LICENSE` (Maya and Nuke execute properly inside frames on this node, indicating they are unnecessary here, but general studio deployments should audit these).
