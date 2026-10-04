# 11 — Production Deployment Risks and TODOs

The initial verification was conducted under "single node, local loopback, lab environment" conditions. Scaling out to a production environment introduces considerations that do not surface in lab testing but inevitably occur in deployment.

## 1. Multi-Node DNS Resolution: Avoid Hardcoded `extra_hosts`

[Pitfall #6 in `08-windows-node-log.md`](08-windows-node-log.md#pitfall-6-cuebot-truncates-hostnames-to-first-label-and-requires-in-container-resolution) observed: Cuebot truncates render node hostnames to their first label and connects back to port 8444 using that short name. Therefore, that short name **must resolve inside the Cuebot container**.

During initial testing, this was bypassed via hardcoded compose entries:

```yaml
extra_hosts:
  - "${RENDER_NODE_NAME}:${RENDER_NODE_ADDR}"
```

**This does not scale.** Maintaining dozens of individual entries for 10 or 30 Windows render nodes is operationally unmanageable.

### Recommended Approach: Direct Containers to Studio DNS and Search Domains

```yaml
cuebot:
  dns:
    - 192.168.1.1        # Internal studio DNS server
  dns_search:
    - studio.local       # Studio domain search suffix
```

When the container resolves short name `RENDER01`, it automatically queries `RENDER01.studio.local`, eliminating the need to maintain `extra_hosts`.

**Pre-Deployment Verification Commands**:

```bash
docker exec opencue-cuebot getent hosts RENDER01
docker exec opencue-cuebot bash -c 'timeout 3 bash -c "</dev/tcp/RENDER01/8444" && echo OK || echo FAIL'
```

[`notes/deploy/server/opencue.portainer.yml`](../deploy/server/opencue.portainer.yml) omits explicit DNS configurations by default: containers inherit host search domains. If the host resolves node short names natively, no configuration is needed. When host inheritance fails, overlay [`notes/deploy/server/site.example.yml`](../deploy/server/site.example.yml). (An empty `dns_search` strips inherited search domains, so it cannot be placed as a defaulted variable in the primary stack; see [`22` Section 6](22-two-deployment-routes.md#6-what-changed-in-the-primary-stack-for-environment-only-deployment).)

## 2. Network Drive Letters Are Supported, with One Exception

### Production Environment Baseline (Confirmed)

- Workstations and render nodes **run Windows exclusively**.
- All nodes share **synchronized drive letter mappings** (e.g., identical drive letters target identical SMB shares).
- **Existing studio scene files embed drive-letter paths directly**.

Under these conditions, mandating an absolute transition to UNC paths would require rewriting legacy production assets, which is impractical. Empirical testing confirms this transition is unnecessary.

### Empirical Testing: RQD in User Sessions Supports All Three Path Syntaxes

A render frame dispatched to a Windows node tested writing across three distinct path formats:

```
host   : LAPTOP-ULJICLO8
user   : chordee

Drive letter     H:\opencue-drivetest                        -> Write successful (34 bytes)
UNC backslash    \\192.168.0.107\chordee\opencue-drivetest    -> Write successful (34 bytes)
UNC slash        //192.168.0.107/chordee/opencue-drivetest    -> Write successful (34 bytes)

Result: All succeeded
```

**Conclusion: Scene files, render outputs, and scratch paths can safely retain existing drive letter conventions.**

### Exception 1: RQD Executing as a Windows Service (Pending Verification)

Mapped drive letters are **scoped to interactive user logon sessions**. As established in [`09-nimby-and-hybrid-fleet.md`](09-nimby-and-hybrid-fleet.md):

| Node Type | RQD Launch Method | Drive Letter Support |
|---|---|---|
| Artist Workstation | Logon trigger, running in user session | **Supported** (Empirically verified) |
| Dedicated Render Node | Windows Service, running in Session 0 | **Pending verification** |

Windows Services in Session 0 do not inherit interactive mapped drives. Standard studio remedies include executing `net use` under the service account upon startup, or configuring persistent GPO drive mappings for the service account.

**Testing service scenarios requires administrator privileges.** Before deploying dedicated headless nodes, confirm:

1. Whether RQD runs as a service or inside an autologon user session.
2. If running as a service, whether the service account can access required drive letters.

Verify by running a test job writing to `H:\...` under the target service account.

### Exception 2: `CUE_FRAME_LOG_DIR` Requires Forward-Slash UNC Format

This requirement is an **independent technical constraint unrelated to Windows session permissions**.

`CUE_FRAME_LOG_DIR` is read by **CueWeb running inside a Linux container**, in addition to render nodes writing to it.

| Syntax | Windows RQD | Linux CueWeb Container |
|---|---|---|
| `L:/opencue/logs` | Writable | **Unparseable**; `path.isAbsolute()` returns false → HTTP 400 |
| `//fileserver/opencue/logs` | Writable (UNC) | **Parseable**; `//` represents a valid absolute path in POSIX |

Empirical tests are documented in [`13-cueweb-and-rest-gateway.md`](13-cueweb-and-rest-gateway.md). Therefore:

> **Root directory for frame logs must use forward-slash UNC syntax; asset paths can freely retain drive letters.**

If CueWeb web log viewing is not deployed, this constraint does not apply, and `CUE_FRAME_LOG_DIR` can use drive letters as well.

### Summary

| Target | Recommendation | Rationale |
|---|---|---|
| Scene files, textures, render outputs | **Drive letters** (Retain conventions) | Validated empirically; legacy project files already use this syntax |
| Command-line arguments | Drive letters, **backslashes** | Prevents DCC CLI parsers from interpreting forward slashes as option flags |
| `CUE_FRAME_LOG_DIR` | **Forward-slash UNC** | Required for concurrent parsing by CueWeb in Linux containers |
| Dedicated render nodes (Service mode) | **Verify first** | Ensure service accounts resolve drive mappings |

## 3. Network Communication Matrix and Firewall Requirements

| Source | Destination | Port | Protocol | Purpose |
|---|---|---|---|---|
| Windows Node | Linux Host | **8443** | TCP | RQD registers, heartbeats, and reports frame results to Cuebot |
| Linux Host | Windows Node | **8444** | TCP | Cuebot dispatches frames, checks status, and kills frames on RQD |
| Artist Workstation | Linux Host | **8443** | TCP | Client utilities: cueadmin / cuegui / cuesubmit / cuenimby |
| Web Browser | Linux Host | 3000 | TCP | CueWeb UI (if deployed) |
| Nodes / Workstations | File Server | 445 | TCP | SMB shared storage |

**Inbound port 8444 is frequently overlooked**: Windows Defender Firewall blocks inbound connections by default. When blocked, symptoms mirror [Pitfall #3 in `04-deployment-process.md`](04-deployment-process.md#pitfall-3-rqd-reports-ipv6-address-cuebot-cannot-connect-back) ("host appears UP, frames stuck indefinitely in RUNNING").

### Security Exposure: gRPC Lacks Authentication

Observed behavior: Pointing `cueadmin` to `localhost:8443` allows unrestricted control over hosts and jobs (including kill, delete-host, etc.) **without requiring passwords, tokens, or TLS certificates**.

Implications:
- Any network client reaching port 8443 can manipulate the entire farm via `cueadmin`.
- Job commands are arbitrary strings submitted by users, equivalent to arbitrary remote code execution on worker nodes.
- Transport is unencrypted plain text.

**Because the Linux server may host other studio services**, port 8443 must be strictly isolated to internal VLANs. If exposed, CueWeb should sit behind a reverse proxy with TLS and authentication.

## 4. Fresh Environment Initialization (Administrative Bootstrap)

> **Note**: Flyway's `migrate.sh` automatically seeds `seed_data.sql` if no shows exist in the database. When deploying with this stack, show `testing`, facilities `local` / `cloud`, and allocations `local.general` / `local.desktop` / `cloud.general` **already exist out of the box**. Show and subscription creation is handled automatically by the `init` container; see [`22` Section 5](22-two-deployment-routes.md#5-initialization-container-init) and [`notes/deploy/01` Section 4](../deploy/01-server.md#4-initialize-show-subscription-and-services). The commands below are preserved for manual reference.

```bash
# 1. Create production show
cueadmin -create-show <show_name>

# 2. Create allocations (facility / name / tag)
cueadmin -create-alloc local render general
cueadmin -create-alloc local workstation desktop

# 3. Subscribe show to allocation (size = guaranteed cores, burst = max cores)
cueadmin -create-sub <show_name> local.render 100 200
cueadmin -create-sub <show_name> local.workstation 50 100

# 4. Move registered hosts to target allocation
cueadmin -force -move local.render -host RENDER01 RENDER02
cueadmin -force -move local.workstation -host ARTIST01

# 5. Verify configuration
cueadmin -la          # List allocations
cueadmin -lb <show>   # List show subscriptions
cueadmin -lh          # List hosts and assigned allocations
```

**Tag matching notice**: When moving hosts into non-general allocations, remember to configure `RQD_TAGS = general` on RQD to continue receiving pyoutline default `general | util` jobs (see [`09` Pitfall #10](09-nimby-and-hybrid-fleet.md#pitfall-10-moving-to-desktop-allocation-blocks-default-jobs)).

## 5. Antivirus / EDR May Flag NIMBY as Spyware

[Note `09-nimby-and-hybrid-fleet.md`](09-nimby-and-hybrid-fleet.md) notes that RQD NIMBY uses `pynput` to detect keyboard and mouse activity.

**Risk**: `pynput` installs low-level global OS hooks (`SetWindowsHookEx`). Enterprise endpoint protection (Defender ASR, CrowdStrike, SentinelOne) regularly flags Python processes installing global hooks as keyloggers, terminating processes or stripping hooks.

**Consequence**: RQD crashes on launch, or NIMBY silently fails (preemption fails during artist usage).

**Action**: Coordinate with IT to whitelist `C:\opencue\...\python.exe` and `rqd.exe` before deployment.

Note: Adopting the recommendation in [`09-nimby-and-hybrid-fleet.md`](09-nimby-and-hybrid-fleet.md) — using CueNIMBY schedule gating and disabling RQD NIMBY (`OVERRIDE_NIMBY = False`) — avoids installing input hooks entirely, bypassing EDR conflicts.

## 6. PostgreSQL Data Retention and Backups

[`06-resource-usage.md`](06-resource-usage.md) highlighted storage growth. The underlying database mechanics are as follows:

### Cuebot Archiving Mechanism

In `cuebot/src/main/resources/opencue.properties:419`:

```properties
# Jobs will be archived to the history tables after being completed for this long.
history.archive_jobs_cutoff_hours=72
```

`HistoricalManagerService.transferJob()` relocates jobs completed for over 72 hours into historical tables: `job_history`, `layer_history`, `frame_history`.

**Crucial Point: This is a table move, NOT a deletion.**

OpenCue source code contains **zero automated purging routines for historical tables**. Active transactional tables remain lean, but **PostgreSQL disk consumption grows unbounded over time**.

### Purge Query (With Mandatory Guard Condition)

Foreign key constraints have cascade deletion enabled:

```
frame_history | c_frame_history_pk_job | CASCADE | job_history
layer_history | c_layer_history_pk_job | CASCADE | job_history
```

Deleting rows from `job_history` cascades into `layer_history` and `frame_history`.

**Common Pitfall**:

```sql
-- INCORRECT: DO NOT RUN THIS
DELETE FROM job_history
WHERE int_ts_stopped < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');
```

The column `job_history.int_ts_stopped` defaults to `0`. Unfinished or running jobs evaluate to `0`, and `0 < past epoch` is unconditionally true. This unintentionally deletes active jobs and their cascades!

Empirical test on test database:
- Without guard: Deletes 2 active jobs where `int_ts_stopped = 0`.
- With `int_ts_stopped > 0`: Correctly deletes 0 records.

**Correct Query**:

```sql
DELETE FROM job_history
WHERE int_ts_stopped > 0
  AND int_ts_stopped < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');
```

Always execute `SELECT count(*)` with identical predicates prior to running deletions.

### Backups

If named volume `opencue-db-data` corrupts, the farm loses all state and allocations. Establish regular logical backups:

```bash
# Backup
docker exec opencue-db pg_dump -U cuebot -d cuebot -Fc -f /tmp/cuebot.dump
docker cp opencue-db:/tmp/cuebot.dump ./cuebot-$(date +%Y%m%d).dump

# Restore (into clean database)
docker cp ./cuebot-YYYYMMDD.dump opencue-db:/tmp/restore.dump
docker exec opencue-db pg_restore -U cuebot -d cuebot --clean --if-exists /tmp/restore.dump
```

`-Fc` outputs custom binary format supporting selective and parallel restores.

**Restore Testing Results**:
- Using `--clean` alone on clean database outputs exit code 1 with 474 errors (attempting to DROP non-existent objects).
- Appending `--clean --if-exists` outputs exit code 0 with 0 errors across both populated and blank databases.

Always include `--if-exists` as documented in [`notes/deploy/04-operations.md`](../deploy/04-operations.md).

## 7. Additional Pending Items

| Item | Notes |
|---|---|
| `maintenance.auto_delete_down_hosts` | Defaults to `false`. Workstations transition online/offline regularly; evaluate whether to enable auto-deletion to avoid stale host accumulation |
| ~~Cross-midnight CueNIMBY schedules~~ | **Confirmed broken**. See [`09` Pitfall #11](09-nimby-and-hybrid-fleet.md#pitfall-11-schedules-crossing-midnight-fail-completely) and [`05` Issue #12](05-upstream-issues.md#12-cuenimby-scheduler-cannot-handle-windows-across-midnight-and-invalidation-inverts-intended-behavior). Express schedules using non-crossing disabled windows |
| Registry pipeline | Build → push → Portainer pull sequence. **Confirmed mandatory, not optional** (see below) |
| Cuebot High Availability | Single-node Cuebot creates single point of failure; evaluate HA requirements for studio scale |

## 8. Building Images and Private Registry Is Mandatory, Not Optional

Initial assumptions that prebuilt images could be pulled directly from Docker Hub proved unviable.

### CueWeb and REST Gateway Images Are Not Published

```
opencue/cuebot        -> HTTP 200
opencue/rqd           -> HTTP 200
opencue/cueweb        -> HTTP 404
opencue/rest-gateway  -> HTTP 404
```

`image: opencue/cueweb:latest` in upstream compose fails to pull. Running the web UI requires building images locally.

### Published Cuebot Images Lag Severely Behind Master

Docker Hub's `opencue/cuebot` tags stop at `1.19.1`, while current master builds `1.34.4`.

### Production Build & Delivery Workflow

```
Build Machine                         Internal Registry            Linux Host
  git clone
  docker compose build   ──push──>  registry.example.com  ──pull──>  Portainer
    cuebot                            /opencue/cuebot:1.34.4          stack
    flyway                            /opencue/flyway:1.34.4
    rest-gateway                      /opencue/rest-gateway:1.34.4
    cueweb                            /opencue/cueweb:1.34.4
```

Required infrastructure:
- **Build Server**: Sufficient RAM required. CueWeb uses Next.js; Node compilation consumes multiple gigabytes of memory.
- **Internal Registry**: Or secure cloud registry accessible by Portainer.
- **Tagging Strategy**: Avoid `latest`. Use explicit semantic versioning or commit SHAs for rollback capabilities.
- **Authentication Build Args**: `NEXT_PUBLIC_AUTH_PROVIDER` in CueWeb is a build argument; authentication providers must be declared at build time.

Benefits of internal builds:
- Strict version alignment across Cuebot, RQD, and client libraries.
- Ability to bake in custom viewers, log paths, and progress bar configurations.
- Enterprise security compliance and base image patching.
