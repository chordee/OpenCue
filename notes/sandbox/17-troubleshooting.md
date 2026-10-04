# 17 — Troubleshooting and Common Pitfalls Field Manual

When installing, deploying, or operating OpenCue, engineers most frequently ask: **"The job is stuck or throwing an error; exactly which file or configuration do I need to fix?"**

This guide indexes by **observed symptoms and error keywords**, addressing 29 verified pitfalls encountered during testing, mapped directly to actionable diagnostic commands and configuration fixes.

---

## Quick Reference Diagnostic Matrix

| Symptom / Error Keyword | Root Cause | Most Likely Configuration Error | Quick Resolution |
|---|---|---|---|
| **Frames stuck in WAITING**<br>`Host UP / OPEN, Job PENDING` | Tag mismatch | Host lost `general` tag after moving to `local.desktop` | See [Scenario 1](#scenario-1-job-stuck-in-pending-all-frames-waiting-host-displays-up--open) |
| **Host displays LOCKED**<br>`Jobs not dispatched` | CueNIMBY schedule lock, or inverted cross-midnight schedule | Within office hours lock window; or inverted schedule like `18:00-09:00 available` | Use **non-crossing disabled intervals**, e.g., `09:00-18:00 disabled`. See [Scenario 2](#scenario-2-host-status-displays-locked-jobs-not-dispatched) |
| **Frames stuck in RUNNING**<br>`No logs, no subprocess` | Cuebot cannot reach RQD on port 8444 | Short hostname unresolvable, or local firewall blocks 8444 | See [Scenario 3](#scenario-3-frames-stuck-in-running-indefinitely-with-no-logs-or-subprocess) |
| **Exit Status 299**<br>`UID is not unique` | In-container UID collision in Linux RQD | Submitting user UID 1000 collides with container `rqd` user | See [Scenario 4](#scenario-4-frame-crashes-immediately-reporting-exit-status-299) |
| **No module named 'wmi'**<br>`rqmachine.py crash` | Windows RQD missing dependencies | Ran `pip install ./rqd` only, omitting Windows extensions | See [Scenario 5](#scenario-5-windows-rqd-crashes-on-startup-with-modulenotfounderror-wmi) |
| **Path backslashes stripped**<br>`\\server\share` becomes `servershare` | POSIX shlex strips backslashes | Job submission script passed command as a string instead of a list | See [Scenario 6](#scenario-6-dcc-render-fails-to-find-files-backslash-paths-stripped) |
| **Unable to create disk cache**<br>`Nuke render failure` | RQD environment passes `TMP` but omits `TEMP` | Launched Nuke without `ocrun`, missing `TEMP` and cache paths | See [Scenario 7](#scenario-7-nuke-render-fails-with-unable-to-create-disk-cache) |
| **'tlocal' is not recognized**<br>`.bat syntax parse error` | cmd.exe OEM code page encoding mismatch | Batch script saved as UTF-8 with non-ASCII comments | See [Scenario 8](#scenario-8-windows-wrapper-script-reports-tlocal-is-not-recognized-or-syntax-errors) |
| **HTTP 400 Query param required**<br>`CueWeb cannot open log` | Linux CueWeb rejects Windows drive letters | `CUE_FRAME_LOG_DIR` configured with `C:/...` or `L:/...` | See [Scenario 9](#scenario-9-cueweb-frame-log-inspection-returns-http-400-query-parameter-path-is-required) |
| **HTTP 403 Outside allowed roots**<br>`CueWeb log access rejected` | Allowlist variable mismatch or misconfiguration | Misconfigured `CUEWEB_PREVIEW_ROOTS` or unconfigured `CUEWEB_LOG_ROOTS` | See [Scenario 10](#scenario-10-cueweb-log-read-returns-http-403-path-is-outside-the-allowed-log-roots) |
| **failed to lock host**<br>`CueNIMBY throws RqdClientException` | Inverted startup sequence; RQD not yet ready | Script launched CueNIMBY before RQD finished initialization | See [Scenario 11](#scenario-11-cuenimby-startup-throws-rqdclientexception-failed-to-lock-host) |
| **History purge query deletes active tasks**<br>`In-flight job history wiped` | Default value of `int_ts_stopped` is 0 | Purge SQL omitted `int_ts_stopped > 0` guard condition | See [Scenario 12](#scenario-12-manual-database-purge-accidentally-deletes-active-or-running-job-history) |
| **Windows commands invoke Linux tools**<br>`timeout: invalid time interval '/t'` | RQD PATH polluted by developer shell | Launched RQD from Git Bash; Unix utilities override Windows commands | See [Scenario 13](#scenario-13-render-command-behaves-erratically-windows-built-in-commands-overridden) |
| **Frame logs missing**<br>`Directory exists but is empty` | Linux path resolves relative to current working drive on Windows | `CUE_FRAME_LOG_DIR` left at default `/tmp/rqd/logs` | See [Scenario 14](#scenario-14-frame-log-files-vanish-or-land-on-unexpected-drives) |
| **pull access denied**<br>`repository does not exist` | Official upstream images were never published | Misdiagnosed as auth issue; `cueweb` and `rest-gateway` have no public images | See [Scenario 15](#scenario-15-docker-pull-fails-during-deployment-repository-does-not-exist) |
| **Mounted volume empty inside container**<br>`Deployment healthy but files unreadable` | Portainer lacks WSL path translation (Docker Desktop only) | Bind mount specified `/mnt/c/...` instead of daemon path `/run/desktop/mnt/host/c/...` | See [Scenario 16](#scenario-16-mounted-directory-is-empty-inside-container-after-portainer-deployment) |
| **CueWeb thumbnail cannot open EXR**<br>(**Expected Behavior**) | Web browsers lack native EXR decoders | Assumed preview failure; requires separate PNG proxy generation | See [Scenario 17](#scenario-17-cueweb-thumbnail-preview-cannot-display-exr-not-a-bug) |
| **Memory shows 0**<br>`MaxRss / int_mem_max_used = 0` (**Expected Behavior**) | 10-second sampling window did not sample short frame | Assumed winps failure; misleading metric for capacity planning | See [Scenario 18](#scenario-18-frame-memory-usage-reports-0-not-a-bug) |
| **Version pinning fails**<br>`Job dispatches to node without that DCC` | Tag matching evaluates regex OR, not AND | Layer tags mixed `general` with specific version tags | See [Scenario 19](#scenario-19-job-dispatches-to-node-lacking-required-dcc-version) |
| **New node never receives jobs**<br>`Host UP/OPEN but frames WAITING` | Facility mismatch | New node defaulted to `cloud`, while jobs defaulted to `local` | See [Scenario 20](#scenario-20-newly-joined-node-never-receives-work) |
| **Job succeeds but log missing**<br>`Heterogeneous multi-OS farm` | Entire farm shares single log root | Missing `log.frame-log-root.<OS>`; Linux node receives Windows path | See [Scenario 21](#scenario-21-in-multi-os-farms-jobs-succeed-but-logs-cannot-be-found) |
| **New show jobs stuck in WAITING**<br>`Testing show works, new show static` | Show lacks subscription to node's allocation | Created show without subscriptions, or omitted `local.desktop` | See [Scenario 22](#scenario-22-jobs-submitted-to-newly-created-show-stuck-in-waiting) |
| **RQD crashes on launch**<br>`UnicodeDecodeError: 'cp950'` | RQD reads config without explicit encoding | `rqd.conf` contains non-ASCII characters (including comments) | See [Scenario 23](#scenario-23-rqd-crashes-immediately-on-launch-with-unicodedecodeerror) |
| **Paths with spaces fail**<br>`'D:/programs/Side' is not recognized` | pyoutline concatenates command list with spaces without quotes | Spaces in scene paths, output directories, or executable paths | See [Scenario 24](#scenario-24-frame-fails-when-path-contains-spaces) |
| **Autodesk CER crash window pops up on worker**<br>`cer_dialog.exe` | Frame missing `ALLUSERSPROFILE`; license module crashes on exit | `rqd.conf` missing `[UseHostEnvVar]` section | See [Scenario 25](#scenario-25-autodesk-crash-error-report-window-pops-up-on-render-node) |
| **API job kill has no effect**<br>`Invalid Job Kill Request` | Cuebot rejects job kill without reason, while returning success | Called `job.kill()` without supplying `reason` argument | See [Scenario 26](#scenario-26-killing-job-via-api-silently-fails-while-job-keeps-running) |
| **Frame timestamps or date-named files off by 15 hours**<br>`TZ=PST8PDT` | RQD hardcodes frame timezone to US Pacific time | `rqd.conf` `[UseHostEnvVar]` section does not include `TZ` | See [Scenario 27](#scenario-27-frame-output-filenames-or-log-timestamps-offset-by-15-hours) |
| **Frame reports success but produces no output images**<br>`license checkout error` | Arnold aborts on missing license, yet `Render.exe` returns 0 | `dcc.toml` missing `solidangle_LICENSE`; not executed via `ocrun` | See [Scenario 28](#scenario-28-frame-reports-success-but-no-output-images-are-written) |
| **New node never registers; RQD logs no errors**<br>`value too long for type character varying(128)` | Total concatenated node tags exceed upstream limit | Using upstream flyway image; database missing studio migration | See [Scenario 29](#scenario-29-new-node-never-registers-with-zero-errors-on-rqd) |

---

## Detailed Troubleshooting Procedures

### Scenario 1: Job Stuck in PENDING, All Frames WAITING, Host Displays UP / OPEN

- **Symptoms**: `cueadmin -lh` reports Windows nodes as healthy (`UP`, `OPEN`), jobs enter queue, but frames remain static.
- **Root Cause & Misconfiguration**:
  1. Inspect [`notes/deploy/node/rqd-windows.conf`](../deploy/node/rqd-windows.conf) to verify if `RQD_TAGS` omits `general`.
  2. When hosts are moved into custom allocations (such as `local.desktop`), host tags are reset. Default pyoutline jobs request `general | util`, causing a tag mismatch.
- **Verification Query**:
  ```bash
  docker exec -it opencue-db psql -U cuebot -c "
  SELECT str_name, str_tags FROM layer WHERE str_state='PENDING';
  SELECT h.str_name, ht.str_tag FROM host h JOIN host_tag ht ON h.pk_host=ht.pk_host;"
  ```
- **Resolution**: Add `RQD_TAGS = general` to `rqd.conf` on Windows nodes and restart RQD.

---

### Scenario 2: Host Status Displays LOCKED, Jobs Not Dispatched

- **Symptoms**: `cueadmin -lh` reports node status as `LOCKED`, even when interactive workstations are idle.
- **Root Cause & Misconfiguration**:
  1. Current time falls within office hours lock intervals defined in `cuenimby.json` (e.g., Mon–Fri 09:00–18:00).
  2. `cuenimby.json` contains cross-midnight intervals (such as `18:00-09:00 available` or `22:00-06:00 disabled`), triggering an upstream bug that inverts states 24 hours a day!
- **Verification**:
  ```powershell
  Get-Content C:\opencue\cuenimby.log -Tail 20
  ```
- **Resolution**:
  1. Manual unlock during testing:
     ```bash
     cueadmin -force -unlock -host <node_name>
     ```
  2. Production schedules must be defined using non-crossing disabled intervals (e.g., `09:00-18:00 disabled`).

---

### Scenario 3: Frames Stuck in RUNNING Indefinitely with No Logs or Subprocess

- **Symptoms**: Frame displays yellow `RUNNING` in CueGUI, but Task Manager reveals no spawned DCC processes, and no `.rqlog` files are created.
- **Root Cause & Misconfiguration**:
  1. **One-way network partition**: RQD connects to Cuebot (8443), but Cuebot fails when attempting to call back to RQD (8444).
  2. Windows Defender Firewall blocks inbound TCP 8444 on worker nodes.
  3. Cuebot truncates hostnames to their first label, and in-container DNS cannot resolve that short hostname.
- **Verification**:
  ```bash
  docker logs opencue-cuebot | grep "RqdClientException"
  docker exec opencue-cuebot getent hosts <node_short_name>
  docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/<node_short_name>/8444" && echo OK || echo FAIL'
  ```
- **Resolution**:
  1. Allow inbound TCP 8444 on Windows Firewall.
  2. Configure `dns` and `dns_search` in `opencue.portainer.yml`, or declare `extra_hosts`.

---

### Scenario 4: Frame Crashes Immediately Reporting Exit Status 299

- **Symptoms**: Dispatched job immediately turns red with exit code `299`.
- **Understanding Exit Code 299**: Defined in `Dispatcher.java:68` as `EXIT_STATUS_FRAME_CLEARED`. **It is a generic cancellation code that indicates no specific failure cause.** Inspect Cuebot logs to determine root cause.
- **Root Cause & Misconfiguration**: Specific to Linux container RQD. Submitting user UID 1000 collides with in-container `rqd` user UID 1000. RQD unconditionally executes `useradd` and crashes.
- **Verification**:
  ```bash
  docker logs opencue-cuebot | grep ABORTED
  # Output: ABORTED: Not launching, user xxx(1000:0) could not be created.
  ```
- **Resolution**: In containerized RQD, override the entrypoint to create the user with a distinct UID before launch, or set `runner.default_uid`.

---

### Scenario 5: Windows RQD Crashes on Startup with ModuleNotFoundError: 'wmi'

- **Symptoms**: Windows RQD crashes upon launch with `ModuleNotFoundError: No module named 'wmi'`.
- **Root Cause & Misconfiguration**: `rqd/pyproject.toml` omits Windows dependencies. `rqmachine.py` unconditionally imports `wmi` on Windows platforms.
- **Resolution**:
  ```bash
  pip install wmi pywin32
  ```

---

### Scenario 6: DCC Render Fails to Find Files; Backslash Paths Stripped

- **Symptoms**: DCC commands fail reporting paths like `servershareproject` instead of `\\server\share\project`.
- **Root Cause & Misconfiguration**: Submission script passed commands as a single concatenated string. `pyoutline/outline/io.py` invokes POSIX `shlex.split()`, which treats Windows backslashes as escape characters.
- **Resolution**: Pass command arguments as Python lists:
  ```python
  command = ["ocrun", "maya", "2027", "Render", scene_path]
  ```

---

### Scenario 7: Nuke Render Fails with Unable to Create Disk Cache

- **Symptoms**: Nuke frames fail with `ERROR: Unable to create disk cache at C:/temp/nuke`.
- **Root Cause & Misconfiguration**: RQD subprocess environment passes `TMP` but omits `TEMP`. Nuke falls back to hardcoded `C:/temp`, which does not exist.
- **Resolution**: Ensure Nuke runs via `ocrun` (which injects `TEMP` and default disk cache paths), or configure `NUKE_DISK_CACHE` explicitly in wrapper scripts.

---

### Scenario 8: Windows Wrapper Script Reports 'tlocal' Is Not Recognized or Syntax Errors

- **Symptoms**: Batch file prints syntax errors and terminates unexpectedly:
  ```
  'tlocal' is not recognized as an internal or external command
  ```
- **Root Cause & Misconfiguration**: Batch script was saved as UTF-8 containing Chinese comments. `cmd.exe` parses batch scripts using the system OEM code page (CP950 in Traditional Chinese environments), breaking block parenthesis matching.
- **Resolution**: Batch scripts deployed to Windows nodes must strictly use **pure ASCII text**.

---

### Scenario 9: CueWeb Frame Log Inspection Returns HTTP 400: Query Parameter 'path' Is Required

- **Symptoms**: Clicking frame logs in CueWeb returns HTTP 400.
- **Root Cause & Misconfiguration**: Cuebot passed Windows drive letter paths (e.g. `C:/opencue/logs/...`). CueWeb runs in Linux where drive letters fail `path.isAbsolute()`.
- **Resolution**: Configure `CUE_FRAME_LOG_DIR` using forward-slash UNC syntax (`//fileserver/opencue/logs`), which is valid across both Windows and POSIX systems.

---

### Scenario 10: CueWeb Log Read Returns HTTP 403: Path Is Outside the Allowed Log Roots

- **Symptoms**: CueWeb log viewing returns HTTP 403.
- **Root Cause & Misconfiguration**: Path requested is not covered by `CUEWEB_LOG_ROOTS`, or log roots were confused with `CUEWEB_PREVIEW_ROOTS`.
- **Resolution**: Configure `CUEWEB_LOG_ROOTS` in the CueWeb environment to include the mounted log directory (e.g., `/mnt/logs`).

---

### Scenario 11: CueNIMBY Startup Throws RqdClientException: Failed to Lock Host

- **Symptoms**: CueNIMBY logs `RqdClientException: failed to lock host`.
- **Root Cause & Misconfiguration**: Startup script launched CueNIMBY before RQD was fully initialized. Host locking requires Cuebot to call back to RQD on port 8444.
- **Resolution**: Enforce startup sequencing: launch RQD first, pause briefly, then launch CueNIMBY.

---

### Scenario 12: Manual Database Purge Accidentally Deletes Active or Running Job History

- **Symptoms**: Active or running jobs disappear from CueGUI after executing maintenance SQL.
- **Root Cause & Misconfiguration**: `job_history.int_ts_stopped` defaults to 0 for unfinished jobs. A query like `WHERE int_ts_stopped < ...` matches 0 and purges active tasks via cascading delete.
- **Resolution**: Always include the guard condition `int_ts_stopped > 0`:
  ```sql
  DELETE FROM job_history
  WHERE int_ts_stopped > 0
    AND int_ts_stopped < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');
  ```

---

### Scenario 13: Render Command Behaves Erratically; Windows Built-in Commands Overridden

- **Symptoms**: Windows commands fail with Linux error messages:
  ```
  timeout: invalid time interval '/t'
  ```
- **Root Cause & Misconfiguration**: RQD was launched from an interactive Git Bash session, inheriting `C:\Program Files\Git\usr\bin` in PATH and passing Unix utilities to child frames.
- **Resolution**: Explicitly declare clean system PATH in `rqd-start.bat`:
  ```bat
  set PATH=%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem
  set PATH=%PATH%;%SystemRoot%\System32\WindowsPowerShell\v1.0
  ```

---

### Scenario 14: Frame Log Files Vanish or Land on Unexpected Drives

- **Symptoms**: Jobs finish successfully, but logs are missing from expected paths.
- **Root Cause & Misconfiguration**: `CUE_FRAME_LOG_DIR` left at default `/tmp/rqd/logs`. Python on Windows resolves this relative to the current working drive (e.g. `D:\tmp\rqd\logs`).
- **Resolution**: Configure `CUE_FRAME_LOG_DIR` to a shared forward-slash UNC path (`//fileserver/opencue/logs`).

---

### Scenario 15: Docker Pull Fails During Deployment (Repository Does Not Exist)

- **Symptoms**: `docker pull opencue/cueweb:latest` returns `repository does not exist or may require 'docker login'`.
- **Root Cause & Misconfiguration**: `opencue/cueweb` and `opencue/rest-gateway` were never published to Docker Hub.
- **Resolution**: Build images locally and push to an internal private registry (see [`14-registry-workflow.md`](14-registry-workflow.md)).

---

### Scenario 16: Mounted Directory Is Empty Inside Container After Portainer Deployment

- **Symptoms**: Container starts healthy, but volume mount `/mnt/logs` is completely empty.
- **Root Cause & Misconfiguration** (Docker Desktop environments): Portainer talks directly to the Docker daemon and does not perform WSL path translations (`/mnt/c/...`).
- **Resolution**: Use the daemon mount path `/run/desktop/mnt/host/c/...` in Docker Desktop testing environments. Production Linux hosts do not experience this issue.

---

### Scenario 17: CueWeb Thumbnail Preview Cannot Display EXR (Not a Bug)

- **Symptoms**: EXR frames display placeholder icons in CueWeb preview.
- **Root Cause**: Web browsers do not have native EXR decoders. CueWeb explicitly supports web formats only (`png`, `jpeg`, `webp`, `bmp`, `avif`).
- **Resolution**: Configure external viewer integration (`NEXT_PUBLIC_PREVIEW_COMMAND='rv {paths}'`), or generate 8-bit PNG proxies during rendering.

---

### Scenario 18: Frame Memory Usage Reports 0 (Not a Bug)

- **Symptoms**: Frame `MaxRss` reports 0 despite heavy DCC rendering.
- **Root Cause**: RQD samples memory usage every 10 seconds (`RSS_UPDATE_INTERVAL = 10`). Short tasks finishing between sampling boundaries report 0.
- **Resolution**: Not a bug. When calculating memory requirements from historical jobs, filter out frames reporting 0.

---

### Scenario 19: Job Dispatches to Node Lacking Required DCC Version

- **Symptoms**: Job tagged with `houdini_22_0_429` dispatches to a node with only Houdini 21 and fails with exit code 127.
- **Root Cause**: Tag matching in Cuebot evaluates PostgreSQL regex OR (`~*`). Setting `tags=["general", "houdini_22_0_429"]` matches any host carrying `general`.
- **Resolution**: Omit `general` when specifying version tags: `tags=["houdini_22_0_429"]`.

---

### Scenario 20: Newly Joined Node Never Receives Work

- **Symptoms**: Host shows UP / OPEN and tags match, but frames remain stuck in WAITING.
- **Root Cause**: Facility mismatch. RQD defaults to `facility = cloud`, while submitting clients default to `facility = local`.
- **Resolution**: Move host to the active facility:
  ```bash
  cueadmin -force -move local.general -host <node_name>
  ```
  or configure `DEFAULT_FACILITY = local` in `rqd.conf`.

---

### Scenario 21: In Multi-OS Farms, Jobs Succeed but Logs Cannot Be Found

- **Symptoms**: In heterogeneous farms, Linux nodes create literal directories named `/app/C:` to store logs.
- **Root Cause**: Single `CUE_FRAME_LOG_DIR` shared across all operating systems.
- **Resolution**: Configure per-OS log roots in Cuebot:
  ```
  --log.frame-log-root.Windows=//fileserver/opencue/logs
  --log.frame-log-root.debian=/tmp/rqd/logs
  ```
  Submitting jobs must specify target `os` (e.g. `os="Windows"`).

---

### Scenario 22: Jobs Submitted to Newly Created Show Stuck in WAITING

- **Symptoms**: Jobs submitted to `testing` execute normally, but jobs submitted to newly created shows remain static in WAITING.
- **Root Cause**: Newly created shows have zero subscriptions by default. Cuebot dispatches work only if a show subscribes to the host's allocation.
- **Resolution**: Subscribe the show to target allocations:
  ```bash
  cueadmin -create-sub <show_name> local.general 100 200
  cueadmin -create-sub <show_name> local.desktop 50 100
  ```

---

### Scenario 23: RQD Crashes Immediately on Launch with UnicodeDecodeError

- **Symptoms**: RQD crashes with `UnicodeDecodeError: 'cp950' codec can't decode byte...`.
- **Root Cause**: RQD reads `rqd.conf` using default system ANSI code page without explicit UTF-8 encoding.
- **Resolution**: Ensure all `.conf` and `.bat` files contain **pure ASCII characters only**.

---

### Scenario 24: Frame Fails When Path Contains Spaces

- **Symptoms**: Frame fails immediately with command truncated at spaces:
  ```
  'D:/programs/Side' is not recognized as an internal or external command
  ```
- **Root Cause**: pyoutline joins command arguments with spaces without wrapping arguments in quotes (`" ".join(cmd)`).
- **Resolution**:
  1. Route DCC executions through `ocrun` (which manages executable paths internally).
  2. Wrap path arguments containing spaces in double quotes within submission scripts.

---

### Scenario 25: Autodesk Crash Error Report Window Pops Up on Render Node

- **Symptoms**: Autodesk CER dialog appears on workstation screen after Maya renders, adding ~15 seconds per frame.
- **Root Cause**: Frame environment missing `ALLUSERSPROFILE`. Autodesk CLIC licensing module throws exception `0xE06D7363` upon exit.
- **Resolution**: Add `ALLUSERSPROFILE` under `[UseHostEnvVar]` in `rqd.conf`.

---

### Scenario 26: Killing Job via API Silently Fails While Job Keeps Running

- **Symptoms**: Calling `job.kill()` raises no errors, but the job remains active.
- **Root Cause**: Cuebot requires an explicit reason string for manual job cancellations (`JobManagerSupport.java:100`).
- **Resolution**: Always provide a cancellation reason:
  ```python
  job.kill(reason="Cancelled by pipeline")
  ```

---

### Scenario 27: Frame Output Filenames or Log Timestamps Offset by 15 Hours

- **Symptoms**: Output directories or log timestamps use US Pacific time instead of local time.
- **Root Cause**: RQD hardcodes frame environment variable `TZ=PST8PDT`.
- **Resolution**: Add `TZ` to `[UseHostEnvVar]` in `rqd.conf`.

---

### Scenario 28: Frame Reports Success but No Output Images Are Written

- **Symptoms**: Maya Arnold frames report SUCCEEDED with exit code 0, but no images are generated. Frame logs report `license checkout error`.
- **Root Cause**: Missing `solidangle_LICENSE` in frame environment, and `Render.exe` returns 0 despite license checkout failures.
- **Resolution**: Declare `solidangle_LICENSE` in `dcc.toml` under `[env]`, and execute renders via `ocrun` (which detects license failures and forces exit code 1).

---

### Scenario 29: New Node Never Registers with Zero Errors on RQD

- **Symptoms**: RQD starts normally, but the host never appears in `cueadmin -lh`. Cuebot logs report:
  `ERROR: value too long for type character varying(128)`.
- **Root Cause**: Total concatenated tags exceed upstream `host.str_tags VARCHAR(128)` cap.
- **Resolution**: Deploy studio Flyway migration `R__Studio_widen_host_tags.sql` to widen column to `VARCHAR(4000)`. See [`32-node-tag-limit.md`](32-node-tag-limit.md).
