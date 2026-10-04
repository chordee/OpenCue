# 04 — Deployment Process Execution Log

Executed entirely inside WSL2 Ubuntu 24.04; repository path located at `/mnt/d/dev/OpenCue`.

## Step 1: Create Mandatory Directories

```bash
mkdir -p /tmp/rqd/logs /tmp/rqd/shots /tmp/opencue ~/.opencue/sessions
```

## Step 2: Build Container Images

```bash
cd /mnt/d/dev/OpenCue
docker compose build cuebot flyway rqd
```

Outcome: `rqd` and `flyway` builds succeeded; **`cuebot` build failed**.

### Pitfall #1: CRLF Line Endings Breaking Cuebot Build

Initial build logs appeared to fail with `repo.spring.io` HTTP 401 warnings:

```
Failed to get resource: GET. [HTTP HTTP/1.1 401 :
https://repo.spring.io/plugins-snapshot/...]
```

**These errors were benign noise**; Gradle fell back to secondary mirrors. The root failure occurred downstream in the log:

```
* What went wrong:
Execution failed for task ':spotlessJavaCheck'.
> The following files had format violations:
      src/main/java/com/imageworks/common/spring/remoting/CueServerInterceptor.java
          -package com.imageworks.common.spring.remoting;\r\n
```

**Root Cause**: The repository was cloned on Windows with global git config `core.autocrlf=true`, converting Java source files to CRLF. Gradle's `spotless` linter enforces strict LF formatting and rejected the build.

The upstream `.gitattributes` contained only `*.sh text eol=lf`, omitting Java source definitions.

**Resolution** (Scoped to this repository clone):

```bash
git config core.autocrlf false
git rm --cached -r -q .
git reset --hard -q
```

Verification:

```bash
file cuebot/src/main/java/com/imageworks/common/spring/remoting/CueServerInterceptor.java
# Before: ASCII text, with CRLF line terminators
# After:  Java source, ASCII text
```

**Production Context**: Linux hosts cloning repositories do not encounter this issue. However, developers modifying code on Windows will trigger this failure.
**Recommended Upstream Contribution**: Add comprehensive `.gitattributes` to the root repository.

Rebuilding succeeded.

### Build Artifact Inventory

| Image | Size |
|---|---|
| `opencue-cuebot:latest` | 1.06 GB |
| `opencue-flyway:latest` | 2.15 GB |
| `opencue-rqd:latest` | 152 MB |

`flyway` weighs 2.15 GB (built upon AlmaLinux 9 + JDK). For a one-shot container that exits immediately, this image is relatively bloated.

## Step 3: Launch Core Services

Verify port availability on host interfaces:

```bash
docker ps --format "{{.Names}}\t{{.Ports}}" | grep -E "5432|8443|8444|3000|8448"
```

(Ports were unassigned locally. **Always execute this check on multi-tenant production hosts**).

```bash
docker compose up -d
```

Startup sequence proceeded as expected with functional `depends_on` barriers:

```
db Started -> db Healthy -> flyway Started -> flyway Exited(0)
-> cuebot Started -> cuebot Healthy -> rqd Started
```

Status verification:

```
NAME               STATUS                    PORTS
opencue-cuebot-1   Up (healthy)   0.0.0.0:8443->8443/tcp
opencue-db-1       Up (healthy)   0.0.0.0:5432->5432/tcp
opencue-rqd-1      Up             0.0.0.0:8444->8444/tcp
```

RQD logs confirmed active gRPC(h2) connections to Cuebot.

## Step 4: Install Client Packages

### Pitfall #2: Ubuntu Lacks `python3-venv` and Requires Password for Sudo

```bash
python3 -m venv ~/opencue-venv
# -> You may need to use sudo with that command. After installing the
#    python3-venv package, recreate your virtual environment.
```

Ubuntu isolates `ensurepip` into the separate `python3-venv` package, and Ubuntu 24.04 enforces PEP 668 managed environment restrictions.

**Workaround** (Using pre-installed `uv` without root privileges):

```bash
export PATH=$HOME/.local/bin:$PATH
uv venv ~/opencue-venv --seed --python 3.12
```

`--seed` injects `pip` and `setuptools`.

**Production Context**: Client packages are **not needed** on the server host; clients run on artist workstations (`cuegui`, `cuesubmit`, `cueadmin`). Installing locally was strictly for sandbox validation.

### Installation Execution

```bash
cd /mnt/d/dev/OpenCue
source ~/opencue-venv/bin/activate
./sandbox/install-client-sources.sh
```

Installs sequentially: `proto/`, `pycue/`, `pyoutline/`, `cueadmin/`, `cueman/`, `cuesubmit/`, `cuegui/`, `cuecmd/`, and `cuenimby/`.

## Step 5: Verify Connectivity

```bash
source ~/opencue-venv/bin/activate
export CUEBOT_HOSTS=localhost
cueadmin -lh
```

Initial response:

```
Host                Cores  Mem     State  Alloc          Thread
fdc2:c6c:d60f:9::4  8.0    18.5G   UP     local.general  AUTO
```

**Connected successfully, but the reported hostname was an IPv6 address**—an anomaly that subsequently blocked frame dispatching.

## Step 6: End-to-End Test Job Submission

```bash
python sandbox/load_test_jobs.py simple -n 2 --sleep-seconds 1-2 --unique
```

Jobs queued successfully, but all frames stalled permanently in `RUNNING`: `/bin/sleep 1` hung past 1 minute, memory read 0 KB, `/tmp/rqd/logs` remained empty, and container inspection revealed zero child processes (`/proc` listed only `/app/openrqd`).

### Pitfall #3: RQD Reports IPv6 Address; Cuebot Fails to Connect Back

Diagnostics:

1. RQD output showed only `Sending host report` with **zero task execution activity** -> RQD never received `RunFrame` calls.
2. Cuebot logs showed critical warnings:

```
Launch of frame 0003-test_layer on fdc2:c6c:d60f:9::4 failed and the frame's state
could not be confirmed (RqdClientException: failed to obtain status for frame ...).
Keeping the booking to avoid double-booking; the orphaned-proc reaper will reclaim it
```

3. Direct gRPC probe from inside the Cuebot container confirmed:

```
rqd:8444 (service name)                   -> OK
fdc2:c6c:d60f:9::4:8444 (reported by RQD) -> Connection refused
```

**Root Cause**: Upstream compose sets `OPENRQD__MACHINE__USE_IP_AS_HOSTNAME=true`. RQD selected an **IPv6** interface to report to Cuebot, but OpenRQD's gRPC server bound strictly to IPv4. Outbound "RQD -> Cuebot" heartbeats reached Cuebot, but inbound "Cuebot -> RQD" task dispatches failed on every attempt.

This unidirectional failure easily deceives operators because `cueadmin -lh` reports the host as healthy and `UP`. **Always check Cuebot WARN logs rather than trusting host status lists.**

Resolution: Apply `docker-compose.override.yml`:

```yaml
services:
  rqd:
    environment:
      - OPENRQD__GRPC__CUEBOT_ENDPOINTS=cuebot:8443
      - OPENRQD__MACHINE__USE_IP_AS_HOSTNAME=false
    hostname: rqd
```

With this override, the node registers as `rqd`, and Cuebot establishes callbacks via Docker internal DNS.

**Collateral Impact**: Orphaned bookings accumulate, eventually triggering `trigger__verify_host_resources()` with `unable to allocate additional memory` errors. In sandboxes, reset cleanly via `docker compose down -v`.

### Pitfall #4: RQD User Provisioning Failure (UID Collision)

Once Pitfall #3 was resolved, frames dispatched but aborted immediately with exit status `299` (`Dispatcher.java:68` -> `EXIT_STATUS_FRAME_CLEARED`).

Cuebot log diagnostics:

```
ABORTED: Not launching, user chordee(1000:0) could not be created.
x Failed to create user chordee: useradd: UID 1000 is not unique
```

**Root Cause** (`rust/crates/rqd/src/frame/manager.rs:84-96`):
Whenever `RunFrame` carries a UID, RQD **unconditionally** calls `create_user_if_unexisting`, regardless of `runner.run_as_user` settings (defaulting to false).

`create_user_if_unexisting` (`rust/crates/rqd/src/system/linux.rs:921`):
1. Queries by **name**; returns the UID if found.
2. If absent, executes `useradd --uid <uid>`.

The submitting user `chordee` carried UID 1000, which collided with pre-existing user `rqd` inside the container -> `useradd` aborted -> frame failed.

Workaround: Exploit the "query by name first" heuristic by provisioning user `chordee` with an alternate UID before RQD starts:

```yaml
services:
  rqd:
    entrypoint:
      - /bin/sh
      - -c
      - 'id -u chordee >/dev/null 2>&1 || useradd --uid 2000 --gid 1000 -M chordee; exec /app/openrqd'
```

### Verification Results

```
    str_name     | str_state | int_exit_status
-----------------+-----------+-----------------
 0001-test_layer | SUCCEEDED |               0
 0002-test_layer | SUCCEEDED |               0
 0003-test_layer | SUCCEEDED |               0
(6 frames across 2 jobs completed with SUCCEEDED)
```

**End-to-End Sandbox Lifecycle Verified**: Job Submission -> Cuebot Scheduling -> RQD Dispatch -> Frame Execution -> Log Capture -> Status Reporting.

## Empirical Finding: Concrete Frame Log Directory Hierarchy

`CUE_FRAME_LOG_DIR=/tmp/rqd/logs` is the **root path**, expanded dynamically into:

```
/tmp/rqd/logs/<show>/<shot>/logs/<job_name>--<job_id>/<job_name>.<frame_name>.rqlog
```

Log headers embed full task metadata:

```
command      /bin/sleep 2
uid          2000
gid          20
log_path     /tmp/rqd/logs/testing/testshot/logs/.../....rqlog
render_host  rqd
```

**Implications for Windows Render Nodes**: Paths are constructed using Cuebot's root path setting, but filesystem directories are created by **RQD**. The root setting must target a shared storage path writable by all nodes. Linux local `/tmp/rqd/logs` paths fail on Windows worker nodes. **Frame log roots require forward-slash UNC syntax** (to ensure CueWeb inside Linux containers can read logs); other asset paths can use drive letters; see [`11-production-risks-and-todos.md` Section 2](11-production-risks-and-todos.md#2-network-drive-letters-are-supported-with-one-exception).
