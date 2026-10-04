# 05 — Upstream Issues for Feedback

Issues identified during this deployment process that belong to the upstream OpenCue project rather than our local environment.
Each item includes reproduction steps and identified code locations.

## 1. Incomplete `.gitattributes` Causes Cuebot Build Failure on Windows After Clone

**Severity**: Medium (Blocks all Windows developers)

**Current State**: The repository's `.gitattributes` contains only a single line:

```
*.sh text eol=lf
```

**Issue**: Git for Windows users typically have `core.autocrlf=true`. After cloning, Java source files acquire CRLF line endings. Cuebot's Gradle build includes a `spotless` format check requiring LF line endings, which fails immediately:

```
Execution failed for task ':spotlessJavaCheck'.
> The following files had format violations:
      src/main/java/com/imageworks/common/spring/remoting/CueServerInterceptor.java
          -package com.imageworks.common.spring.remoting;\r\n
```

**Misleading Behavior**: Before failing, Gradle prints an extensive stream of HTTP 401 warnings from `repo.spring.io`, which is easily misdiagnosed as network or repository connectivity issues, though they are purely noise.

**Suggested Fix**: Provide a comprehensive `.gitattributes` covering source files, e.g.:

```
* text=auto eol=lf
*.bat text eol=crlf
*.png binary
```

## 2. Sandbox RQD Reports IPv6 Address, Preventing Cuebot from Dispatching Frames

**Severity**: High (Broken out-of-the-box; the sandbox default configuration cannot execute any frames)

**Reproduction**: Follow [`sandbox/README.md`](../../sandbox/README.md) on Linux (WSL2 Ubuntu 24.04 in this test), run `docker compose up -d`, and submit any job.

**Symptoms**:
- `cueadmin -lh` reports normal host state as UP.
- The host name is reported as an IPv6 address, such as `fdc2:c6c:d60f:9::4`.
- Frames remain stuck in `RUNNING` indefinitely with no log output and no spawned subprocess.
- Cuebot log reports: `failed to obtain status for frame ...`

**Root Cause**: In `docker-compose.yml`, the `rqd` service sets:

```yaml
- OPENRQD__MACHINE__USE_IP_AS_HOSTNAME=true
```

RQD selects an IPv6 address to report, but openrqd's gRPC server only listens on IPv4.
"RQD -> Cuebot" succeeds, but "Cuebot -> RQD" fails.

Verified test (from inside the cuebot container):

```
rqd:8444             → OK
fdc2:c6c:d60f:9::4:8444 → Connection refused
```

**Suggested Fix**: Change the sandbox default to `false` (the Rust RQD source code default is already false; see comments in `rust/config/rqd.yaml`). If IP mode is retained, ensure the selected address matches the address family bound by the gRPC server.

## 3. RQD Unconditionally Creates Users, Failing Entire Frame on UID Conflict

**Severity**: High (Any submitting user whose UID collides with an existing in-container UID fails completely)

**Symptoms**: Frame reports exit status 299 (`EXIT_STATUS_FRAME_CLEARED`), Cuebot log:

```
ABORTED: Not launching, user chordee(1000:0) could not be created.
× Failed to create user chordee: useradd: UID 1000 is not unique
```

**Root Cause**: `rust/crates/rqd/src/frame/manager.rs:84-96`

As long as `run_frame.uid_optional` has a value, it unconditionally calls `create_user_if_unexisting`, **completely ignoring the `runner.run_as_user` setting** (which defaults to false).

Furthermore, `create_user_if_unexisting` (`rust/crates/rqd/src/system/linux.rs:921`) checks existence solely by **username**. If the username does not exist, it runs `useradd --uid <uid>`, which fails if the UID is already in use.

In the sandbox `rqd` container, UID 1000 is already occupied by the `rqd` user, and the first user on a Linux desktop environment conventionally has UID 1000 — resulting in an extremely high collision probability.

**Suggested Fix** (either or combined):
- Create users only when `runner.run_as_user == true`.
- When a UID is already occupied, fall back to `default_uid` and log a warning instead of aborting the entire frame.
- At minimum, ensure error messages indicate that this can be resolved via `run_as_user` or `default_uid`.

## 4. macOS-Specific Path in Compose File

**Severity**: Low (Does not impact functionality, but creates empty directories on Linux host root)

`docker-compose.yml` mounts the following rqd volume:

```yaml
- /var/folders:/var/folders:ro
```

`/var/folders` is a macOS temporary path. On Linux hosts, Docker automatically creates an empty root-owned directory and mounts it.

**Suggested Fix**: Use conditional mounts based on platform, or add comments explaining its purpose.

---

## Locally Resolved Issues

Pitfall #1 (CRLF) was fixed locally in the repo: `git config core.autocrlf false` + re-checkout.

Pitfalls #2 and #3 were bypassed using `docker-compose.override.yml`, **without modifying upstream `docker-compose.yml`**, keeping it clean for future upstream PRs.

---

## 5. Undeclared RQD Dependencies on Windows

**Severity**: Medium (Windows nodes cannot start, but error messages are clear and easy to resolve)

**Reproduction**: Run `rqd` directly on Windows after `pip install ./rqd`.

**Symptoms**:

```
File "rqd/rqmachine.py", line 762, in __updateProcsMappingsFromWindows
    import wmi
ModuleNotFoundError: No module named 'wmi'
```

**Root Cause**: `dependencies` in `rqd/pyproject.toml`:

```toml
dependencies = [
    "opencue_proto",
    "psutil==5.9.8",
    "pynput==1.7.6",
    "future==1.0.0"
]
```

There are no Windows-specific dependencies declared, but `rqd/rqd/rqmachine.py:762` imports `wmi` on Windows execution paths.

**Suggested Fix**: Add environment marker conditional dependencies:

```toml
dependencies = [
    "opencue_proto",
    "psutil==5.9.8",
    "pynput==1.7.6",
    "future==1.0.0",
    "wmi; sys_platform == 'win32'",
    "pywin32; sys_platform == 'win32'",
]
```

## 6. Documentation Lacks Explanation That "Cuebot Must Resolve Short Hostnames of Render Nodes"

**Severity**: Low (Documentation issue, but leads to difficult-to-diagnose failures)

Cuebot truncates the hostname reported by RQD to its first label and uses this short name to connect back to port 8444 on the node.
When Cuebot runs inside a container, the container does not necessarily inherit the host's DNS search domain, causing short-name resolution to fail.

The symptom is frames stuck in RUNNING with no logs, while `cueadmin -lh` reports everything as normal — making diagnosis difficult.

**Recommendation**: Add verification steps in deployment documentation:

```bash
docker exec <cuebot_container> getent hosts <render_node_short_name>
docker exec <cuebot_container> bash -c 'timeout 3 bash -c "</dev/tcp/<node>/8444" && echo OK'
```

## 7. Default Value of `CUE_FRAME_LOG_DIR` Is Invalid for Windows Nodes Without Raising Errors

**Severity**: Medium (Silent failure, logs written to unexpected locations)

The sandbox defaults to `CUE_FRAME_LOG_DIR=/tmp/rqd/logs`. When RQD on Windows receives this path, Python resolves it as an absolute path relative to the current drive (e.g., launching from `D:\` writes to `D:\tmp\rqd\logs`).

**No error is raised**, but Cuebot and CueWeb still record the path as `/tmp/rqd/logs/...`, resulting in a mismatch between the two sides.

Frame logs even show mixed path separators:

```
logDestination  /tmp/rqd/logs/.../<job>--<id>\<job>.<frame>.rqlog
```

**Recommendation**: Deployment documentation for cross-platform render farms should explicitly require setting this to a consistent shared path across all nodes, or have RQD warn when non-native path formats are detected.

## 8. Windows Nodes Without Compiled winps Report Zero Frame Memory Usage

**Severity**: Medium (Silent failure; memory-based throttling/killing mechanisms are completely ineffective on Windows nodes)

**Root Cause**: `rqd/rqd/rqmachine.py:315-322`

```python
def rssUpdate(self, frames):
    if platform.system() == 'Windows' and winpsIsAvailable:
        self.rssUpdateWindows(frames)
        return
    if platform.system() != 'Linux':
        return
```

`winps` is a C++ extension under `rqd/winps/`, **not included in `pip install ./rqd`**. It requires manual compilation with MSVC. Without it, `int_mem_max_used` remains constantly 0 without any warning.

**Suggested Fix** (either option):
- Integrate winps into the Windows build/install workflow, or provide precompiled wheels.
- Log an explicit warning upon startup when Windows is detected and `winpsIsAvailable == False`.
- Clearly document this step in Windows deployment guides.

Note: `rqd/winps/setup.py` uses `from distutils.core import setup`, but `distutils` was removed from the standard library in Python 3.12 (currently functioning via setuptools compatibility layer). Moving to setuptools is recommended long-term.

## 9. Frame Working Directory Does Not Take Effect on Windows

**Severity**: Medium (Jobs relying on relative paths fail; multiple concurrent frames may share directories and overwrite each other)

**Symptom**: JobSpec in frame log declares:

```
cwd  C:\Users\<user>\AppData\Local\Temp/<job>/<frame>
```

However, `os.getcwd()` inside the frame process yields **the RQD process's own working directory**.

**Reproduction**: Launch RQD from different working directories; the frame's cwd mirrors it completely:

| RQD Working Directory | Frame Actual cwd |
|---|---|
| `D:\dev\OpenCue` | `D:\dev\OpenCue` |
| `C:\opencue` | `C:\opencue` |

**Root Cause (Pinpointed in code)**: Among the three platform branches in `rqd/rqd/rqcore.py`, only the Windows branch omits the `cwd` argument to `subprocess.Popen`.

| Method | Line | `cwd` Argument |
|---|---|---|
| `runLinux` | 1038 | `cwd=self.rqCore.machine.getTempPath()` |
| `runDarwin` | 1428 | `cwd=self.rqCore.machine.getTempPath()` |
| `runWindows` | 1364 | **Missing** |

```python
# runWindows (L1364)
frameInfo.forkedCommand = subprocess.Popen(tempCommand,
                                           env=self.frameEnv,
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT)
```

According to Python's `subprocess` documentation, an unspecified `cwd` defaults to `None`, causing child processes to inherit the parent process's working directory — perfectly matching observation.

**Suggested Fix**: Add `cwd=self.rqCore.machine.getTempPath()` to `subprocess.Popen` in `runWindows`, matching the other two platforms.

**Impact**: Scene files and temporary outputs using relative paths land in unexpected directories; concurrent frames sharing the same directory risk race conditions and overwrites.

## 10. CueNIMBY Fails to Launch on Clean Windows Machines Due to Directory Creation Failure

**Severity**: Medium (Encountered on every clean Windows workstation)

**Root Cause**: `cuenimby/cuenimby/config.py:59-61`

```python
config_dir = Path.home() / ".config/opencue"
config_dir.mkdir(exist_ok=True)
```

`mkdir()` does not include `parents=True`. On Linux/macOS, `~/.config` usually already exists, but Windows lacks this convention and clean machines will not have it.

**Verification** (Windows, Python 3.11.9):

```python
target = pathlib.Path(tempfile.mkdtemp()) / '.config/opencue'
target.mkdir(exist_ok=True)
# → FileNotFoundError: [WinError 3] The system cannot find the path specified
```

The test machine happened to have `~/.config` created by other tools, so it was not triggered initially.

**Suggested Fix**:

```python
config_dir.mkdir(parents=True, exist_ok=True)
```

## 11. Documentation Does Not Explain That "Hosts Must Have the `general` Tag to Receive Default Jobs"

**Severity**: Medium (Fails silently without any indication, extremely hard to troubleshoot)

After moving a host into the `local.desktop` allocation, it no longer carries the `general` tag; jobs submitted via pyoutline default their layer tags to `general | util`.
The mismatch means the host will never be dispatched tasks.

**Symptoms**: `cueadmin -lh` shows host `UP` / `OPEN`, job shows `PENDING`, frame remains in `WAITING`, **with zero error messages**.

**Troubleshooting Query** (worth documenting):

```sql
SELECT str_name, str_tags FROM layer;
SELECT ht.str_tag, ht.str_tag_type FROM host h JOIN host_tag ht ON h.pk_host=ht.pk_host;
```

**Solution**: Add `RQD_TAGS = general` in RQD config, or specify matching tags when submitting jobs.

**Recommendation**: Explicitly document this matching rule in allocation/tag guides and add a warning next to instructions on moving hosts between allocations.

## 12. CueNIMBY Scheduler Cannot Handle Windows Across Midnight, and Invalidation Inverts Intended Behavior

**Severity**: High (Fails silently, potentially releasing the machine during explicitly prohibited time windows)

**Root Cause**: `cuenimby/cuenimby/scheduler.py:78-87`

```python
current_time = datetime.now().time()
start_time = self._parse_time(day_schedule["start"])
end_time = self._parse_time(day_schedule["end"])
desired_state = day_schedule["state"]

if start_time <= current_time <= end_time:
    return desired_state

# Outside scheduled period - return opposite state
return "available" if desired_state == "disabled" else "disabled"
```

When a schedule crosses midnight, `start > end`, so `start <= current_time <= end` is **never true**. The check falls through to the return statement returning the inverted state — completely reversing the intended schedule.

**Verification** (using mocked time against real `_check_schedule()`):

Scenario A — No midnight crossing (`09:00-18:00 disabled`): All correct

| Time | Expected | Actual |
|---|---|---|
| 10:00 | disabled | disabled |
| 20:00 | available | available |

Scenario B — Crossing midnight expressed as available window (`18:00-09:00 available`):

| Time | Expected | Actual |
|---|---|---|
| 20:00 | available | **disabled** |
| 02:00 | available | **disabled** |
| 23:00 | available | **disabled** |
| 12:00 | disabled | disabled |

→ Result: The workstation is **never borrowed**, silently reducing farm rendering capacity.

Scenario C — Crossing midnight expressed as disabled window (`22:00-06:00 disabled`):

| Time | Expected | Actual |
|---|---|---|
| 23:00 | disabled | **available** |
| 03:00 | disabled | **available** |
| 14:00 | available | available |

→ Result: The workstation is **loaned out when explicitly prohibited**. This failure mode is considerably more dangerous.

**Suggested Fix**:

```python
if start_time <= end_time:
    in_window = start_time <= current_time <= end_time
else:  # Spans across midnight
    in_window = current_time >= start_time or current_time <= end_time

if in_window:
    return desired_state
return "available" if desired_state == "disabled" else "disabled"
```

**Collateral Issue**: Even with time comparison fixed, date attribution remains an issue.
`_get_current_schedule()` retrieves the schedule for the current day using `datetime.now().strftime("%A")`. A cross-midnight window (e.g., Friday 18:00 to Saturday 09:00) is evaluated against Saturday in the early morning. If Saturday has no schedule configured, it returns None. A comprehensive fix must handle day rollover.

**Workaround**: Express windows using non-crossing disabled intervals.
For example, "borrow after office hours" should be written as `09:00-18:00 disabled` rather than `18:00-09:00 available`, leveraging automatic inversion outside the window.

## 13. CueWeb and REST Gateway Images Declared in Compose Are Not Published

**Severity**: Medium (`cueweb` profile cannot be used without building locally)

`docker-compose.yml` specifies both `image:` and `build:` for these services:

```yaml
rest-gateway:
  image: opencue/rest-gateway:latest
  build:
    context: ./
    dockerfile: rest_gateway/Dockerfile

cueweb:
  image: opencue/cueweb:latest
  build:
    context: ./cueweb
```

However, these repositories **do not exist on Docker Hub**:

```
opencue/cuebot        -> HTTP 200
opencue/rqd           -> HTTP 200
opencue/cueweb        -> HTTP 404
opencue/rest-gateway  -> HTTP 404
```

```
docker pull opencue/cueweb:latest
Error response from daemon: pull access denied for opencue/cueweb,
repository does not exist or may require 'docker login'
```

Searches under organizations like `opencuebuild/`, `academysoftwarefoundation/`, and `aswf/` also yielded nothing.

**Impact**: Anyone attempting to run `--profile cueweb` in environments without build capabilities (such as Portainer without build context) fails directly with misleading authentication errors.

**Recommendation**: Either publish images to Docker Hub or remove the `image:` lines to clarify build requirements.

## 14. Published Cuebot Image Lags Significantly Behind Master

**Severity**: Low (Causes subtle compatibility issues)

Tags for `opencue/cuebot` on Docker Hub:

```
latest, 1.19.1, 1.13.8, 1.13.7, 1.13.6
```

The version built from current master is **1.34.4**.

[`sandbox/README.md`](../../sandbox/README.md) notes this risk:

> The latest version of the OpenCue source code might include changes that are
> incompatible with the prebuilt OpenCue images of Cuebot and RQD on Docker Hub
> used in the sandbox environment.

However, the real divergence is over a dozen minor versions.

**Recommendation**: Update sandbox documentation to state clearly that prebuilt images are for quick evaluation only and development/production should build from source, or resume regular releases.

## 15. Rust RQD List-Type Configuration Cannot Be Specified via Environment Variables

**Severity**: Medium (Forces containerized deployments to mount configuration files for tags)

**Reproduction**:

```bash
docker run -e "OPENRQD__MACHINE__CUSTOM_TAGS=general,houdini21" opencue-rqd
```

```
thread 'main' panicked at crates/rqd/src/config/mod.rs:33:52:
invalid type: string "general,houdini21", expected a sequence
```

**Root Cause**: `rust/crates/rqd/src/config/mod.rs:636-639`

```rust
Environment::with_prefix("OPENRQD")
    .separator("__")
    .list_separator(","),
```

Although `list_separator` is configured, it lacks `with_list_parse_key` to specify which keys should be parsed as sequences. Thus, `Vec<String>` fields cannot be loaded from environment variables.

Affected fields include at least `machine.custom_tags` (`config/mod.rs:126`).

**Impact**: In containerized deployments, environment variables are the standard configuration mechanism, but node-specific tags are forced to use mounted config files.

**Suggested Fix**: Add `with_list_parse_key` for list fields, e.g.:

```rust
Environment::with_prefix("OPENRQD")
    .separator("__")
    .list_separator(",")
    .with_list_parse_key("machine.custom_tags")
    .try_parsing(true),
```

**Workaround**: Provide a configuration file pointed to by `OPENCUE_RQD_CONFIG` (`config/mod.rs:622`).

## 16. Documentation Does Not Clarify That Layer Tag Matching Uses Regex "OR"

**Severity**: Medium (Renders DCC version locking ineffective and hard to detect)

`DispatchQuery.java:296`:

```sql
AND host.str_tags ~* ('(?x)' || layer.str_tags || '\\y')
```

Tags on a layer joined with ` | ` are **evaluated directly as a PostgreSQL regex pattern**. Because `|` is regex OR, specifying multiple tags on a layer means **"match any"**, not intuitive "match all".

Test result: A job tagged `general | houdini_22_0_429` was dispatched to a node with only `general` and without Houdini 22.

**Impact**: Users attempting DCC version locking write `tags=["general", "houdini_22_0_429"]` (expecting "in dispatch pool AND has this version"), but version constraints are bypassed and jobs run on incompatible hosts.

**Two Derivative Issues**:

1. Tag strings are parsed as regex; characters like `.`, `*`, `+` cause unexpected matching.
2. `DispatchQuery.java:296` omits word boundary `\\y`, unlike lines 363, 555, and 642, risking substring false positives.

**Recommendation**: Document matching semantics clearly and caution against special regex characters.

## 17. Default Facility for Both RQDs Is `cloud`, Inconsistent with Client Default

**Severity**: Medium (New nodes receive no jobs by default, with no error messages)

| Component | Default Facility | Location |
|---|---|---|
| Rust RQD | `cloud` | `rust/crates/rqd/src/config/mod.rs:162` |
| Python RQD | `cloud` | `rqd/rqd/rqconstants.py:44` |
| pycue (Submitting side) | **`local`** | `cuebot.facility_default` in `pycue/opencue/default.yaml` |

**Result**: A brand-new render node registers into `cloud.general`, while client jobs target `local`. Both sides never match, and the node remains permanently idle.

**Symptoms Are Hard to Diagnose**: host shows `UP` / `OPEN`, job shows `PENDING`, frame remains in `WAITING`, with zero error messages — identical to tag mismatches.

**Recommendation**:
- Align default values across RQD and pycue, or
- Document this disparity and `cueadmin -force -move` clearly in sandbox docs, or
- Have Cuebot log a warning when dispatchable jobs exist alongside idle nodes matching tags but differing in facility.

## 18. Python RQD Reads `rqd.conf` Without Specifying Encoding

**Severity**: Medium (RQD crashes on startup on non-UTF-8 systems when config contains non-ASCII characters)

`rqd/rqd/rqconstants.py` reads configuration using `config.read(CONFIG_FILE)` without an `encoding` parameter, defaulting to the system ANSI code page.

- Traditional Chinese Windows uses ANSI code page cp950.
- A single UTF-8 Chinese character (even within comments) causes startup crash:

  ```
  UnicodeDecodeError: 'cp950' codec can't decode byte 0xae in position 18: illegal multibyte sequence
  ```

In contrast, other components across the repo explicitly specify UTF-8:

| Component | File Reading |
|---|---|
| pycue | `open(..., encoding="utf-8")` (`pycue/opencue/config.py:73, 93`) |
| CueNIMBY | `open(..., encoding='utf-8')` (`cuenimby/cuenimby/config.py:31, 70`) |
| **RQD** | `config.read(CONFIG_FILE)`, **unspecified** |

The sandbox machine did not trigger this because Windows happened to have "Beta: Use Unicode UTF-8 for worldwide language support" enabled (ACP = 65001).

**Suggested Fix**:

```python
config.read(CONFIG_FILE, encoding="utf-8")
```

## 19. Upstream Cuebot Grafana Dashboard Is Outdated

**Severity**: Low (Dashboard mostly blank, leading users to assume monitoring is broken)

`sandbox/config/grafana/dashboards/cuebot.json` was last modified in 2021 (`d84a10ff`).
Among the 27 referenced metrics:

- **9 no longer exist in current Cuebot source code**: `cue_booked_procs`, `cue_booking_errors`,
  `cue_booking_retries`, `cue_cleared_procs`, `cue_host_balance_failed`,
  `cue_host_balance_success`, `cue_killed_offender_procs`, `cue_killed_oom_procs`, `cue_req_errors`
- The remaining 18 are gauges, yet the dashboard applies `rate()`
- Furthermore, these 18 require `metrics.prometheus.collector=true` (disabled by default), with no indication in dashboard or config

Additionally, label names are inconsistent: base metrics use `cuebot_host`, whereas queue metrics use `cuebot_hosts`.

**Recommendation**: Rebuild dashboard for current metrics; display gauges directly without `rate()`; note collector requirements in dashboard descriptions.

## 20. RQD Loki Dependency Listed Only Under Test Dependencies

**Severity**: Medium (Standard RQD install cannot log to Loki when enabled)

`rqd/pyproject.toml` places `loki-urllib3-client` under `[project.optional-dependencies]` `test`.
Standard `pip install ./rqd` will not install it.

In `rqd/rqlogging.py:124-130`, `LokiLogger.__init__` silently returns on `ImportError` without logging errors, leaving the object uninitialized and causing subsequent errors when accessing `self.client`.

**Recommendation**: Add a dedicated `loki` optional dependency group (`pip install ./rqd[loki]`), and log explicit errors or raise exceptions on `ImportError`.

## 21. pyoutline Joins Command Lists with Spaces Without Quotes

**Severity**: Medium (Windows paths frequently contain spaces, e.g., `C:\Program Files`)

`pyoutline/outline/backend/cue.py:325`:

```python
sub_element(spec_layer, "cmd", " ".join(cmd))
```

List elements containing spaces lose argument boundaries. In real testing, `D:/programs/Side Effects Software/.../hython.exe` on Windows was split into `D:/programs/Side`, immediately causing frame DEAD (see [`17` Scenario 24](17-troubleshooting.md#scenario-24-frame-fails-when-path-contains-spaces)).

CueSubmit exhibits a more direct issue: `cuesubmit/Submission.py` joins arguments into a string and then calls `command.split()`, which breaks even user-provided quotes.

**Suggested Fix**: Use `subprocess.list2cmdline(cmd)` on Windows and `shlex.join(cmd)` on POSIX. CueSubmit should build argument lists directly rather than splitting joined strings.

## 22. CueSubmit Maya Camera Selection Sends Invalid `-cam`

**Severity**: High (Submitting without selecting a camera causes all frames to fail)

`cuesubmit/ui/SettingsWidgets.py` `InMayaSettings.getCommandData()` returns `self.cameraSelector.text()`, which is the dropdown button label text:

| Selection | Button Text | Generated Command |
|---|---|---|
| None selected | `[None]` | `-cam [None]` → Maya: `Camera [None] does not exist`, exit 210 |
| Two selected | `a, b` | `-cam a, b` → Split by `split()`, cannot be parsed |

`Submission.buildMayaCmd()` checks only `if camera:`, and `[None]` is truthy, so `-cam` is always appended.

**Suggested Fix**: Use `getChecked()`; omit `-cam` when unselected; restrict camera selection to single-choice, or create a separate layer for each camera when multiple are selected.

## 23. Windows RQD Omits `ALLUSERSPROFILE` in Frame Environment

**Severity**: Medium (Maya frames succeed but trigger Autodesk Crash Error Report window every frame, adding ~15s per frame)

`rqd/rqd/rqcore.py` `__createEnvVariables()` on Windows copies only `SYSTEMROOT`, `APPDATA`, `TMP`, `COMMONPROGRAMFILES`, and `SYSTEMDRIVE` from the host.
Maya 2027's CLIC licensing module requires `ALLUSERSPROFILE` upon shutdown. Missing it throws an unhandled C++ exception (`0xE06D7363`), triggering the CER crash window.

Verified test (same host, same scene, changing only environment variables): full environment does not crash; simulated RQD environment crashes; restoring only `ALLUSERSPROFILE` stops crashes (see [`28`](28-maya-crash-reporting.md)).

**Workaround**: Add `ALLUSERSPROFILE` to `[UseHostEnvVar]` in `rqd.conf`.

**Suggested Fix**: Copy `ALLUSERSPROFILE`, `PROGRAMDATA`, and other machine-wide system variables by default on Windows.

## 24. RQD Hardcodes Frame Timezone to `PST8PDT`

**Severity**: Medium (Local time inside frame is incorrect; date-named outputs land in wrong paths)

`rqd/rqd/rqmachine.py` `getTimezone()` hardcodes `PST8PDT` for non-IST machines, and `rqcore.py` sets `TZ` on every frame without consulting the host OS.
On Windows nodes in Taiwan, frame local time is 15 hours behind the host (see [`29`](29-frame-timezone.md)).

**Workaround**: Add `TZ` to `[UseHostEnvVar]` in `rqd.conf`.

**Suggested Fix**: Omit setting `TZ` by default and inherit from RQD process environment; allow sites requiring fixed timezones to configure it explicitly.

## 25. CueSubmit Nuke Submission Sends Invalid `-X`, Drops Frames When Chunk > 1

**Severity**: High (Submitting without selecting Write node fails; multi-frame chunks drop renders)

Belongs to the same category as issue #22. `cuesubmit/ui/SettingsWidgets.py` `InNukeSettings.getCommandData()` returns `self.writeNodeSelector.text()`: returns `[All]` when unselected, or `a, b` when multiple are selected, generating `-X [All]` or `-X a, b`.

The same function hardcodes `-F #IFRAME#`, which Cuebot replaces with the first frame of the task. When chunk > 1, each task renders only the first frame, skipping the rest while marking them completed.

**Suggested Fix**: Retrieve Write nodes using `getChecked()`, joined by commas without spaces; omit `-X` when empty; replace frame parameter with `#FRAMESPEC#` (Nuke `-F` supports `1-10`, `1-9x2`; see [`31`](31-nuke-submission.md)).

## 26. Clean Deployments Duplicate `task_lock` Insertions Between Seed Data and Migrations

**Severity**: Low (Does not break functionality, but shows `ERROR` during initial deployment)

Migrations `V35`, `V38`, and `V46` already insert `task_lock` records 6, 7, and 8.
`cuebot/src/main/resources/conf/ddl/postgres/seed_data.sql` attempts to insert the same primary keys. When deploying on a fresh database, Flyway logs show:

```
psql:/opt/scripts/seed_data.sql:86: ERROR:  duplicate key value violates unique constraint "c_task_lock_pk"
DETAIL:  Key (pk_task_lock)=(00000000-0000-0000-0000-000000000006) already exists.
(records 7 and 8 report the same)
```

Other seed data (show `testing`, allocations) are created normally, and the container exits with 0.

**Suggested Fix**: Remove `task_lock` records already created by migrations from `seed_data.sql`, or use `ON CONFLICT DO NOTHING`.

## 27. Total Node Tag Length Capped at 128 Characters, Silently Failing Registration

**Severity**: High (Nodes with multiple DCC versions cannot join farm; zero error logged on RQD)

`host.str_tags` is `VARCHAR(128)`, and `recalculate_tags()` concatenates `host_tag` entries separated by spaces.
Tags reported by nodes include `RQD_TAGS`, `rqdv-*`, `windows`, `desktop` (repeated on workstations), and the hostname. With each DCC version tag spanning 10–16 characters, 128 characters is easily exceeded. When exceeded, Cuebot records `value too long for type character varying(128)` in its log, and the node never appears in the host list.

**Suggested Fix**: Increase `host.str_tags` to `VARCHAR(4000)` matching `layer.str_tags`, enlarge temporary variables in `recalculate_tags()`, and return errors to RQD upon registration failure. See [`32`](32-node-tag-limit.md).
