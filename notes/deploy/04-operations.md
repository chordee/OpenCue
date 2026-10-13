# 04 — Operations and Maintenance

---

## 1. Upgrades and Rollbacks

### 1.0 Updating Stack Configuration (Compose YAML)

Production Portainer tracks the `studio/deploy` branch, which a workflow regenerates from `studio/release` on every push ([`01-server.md` Section 3.2](01-server.md#32-create-the-stack-in-portainer)).
Daily iterative commits are pushed to `studio/main`, **leaving production unaffected**.

Before releasing, open a Pull Request to run CodeRabbit automated review (configured in `.coderabbit.yaml` at repo root, targeting PRs into `studio/release` while excluding `notes/sandbox/`):

```bash
gh pr create --repo chordee/OpenCue --base studio/release --head studio/main
```

**Always specify `--repo chordee/OpenCue`**: Because this repository is a fork, omitting `--repo` can accidentally open a PR against upstream OpenCue.

Address all review comments: implement accepted suggestions on `studio/main` and push (updating the PR automatically); reply with technical rationale if declining a suggestion. Once approved, **do not click the GitHub Merge button**; perform a fast-forward merge locally:

```bash
git checkout studio/release
git merge --ff-only studio/main
git push origin studio/release
```

GitHub recognizes that `studio/release` contains all commits in the PR and automatically marks it as Merged.
Rationale for avoiding GitHub UI merge buttons: Merge commits, squashes, and rebases inject foreign commits into `studio/release` absent from `studio/main`, preventing future fast-forward merges.

The **Studio deploy branch** workflow then updates `studio/deploy`, and Portainer deploys it within its polling cycle (5–15 minutes), recreating only services whose definitions have changed. Do not push to `studio/deploy` directly; the next push to `studio/release` overwrites it.

CodeRabbit integration requires installing its GitHub App and granting access to the repo (process workflow remains in pilot verification).

To rollback stack YAML definitions to an earlier commit:

```bash
git checkout studio/release
git reset --hard <previous_commit_sha>
git push --force-with-lease origin studio/release
```

Container image versions are governed by environment variables rather than the YAML file; **this step does not alter container image versions**. For image upgrades, see Sections 1.1–1.3 below.

### 1.1 Building New Container Images

1. Modify source code or merge upstream `master` releases into your development branch; commit and push.
2. In GitHub -> Actions -> **Sandbox images** -> Click **Run workflow**
   (or CLI: `gh workflow run sandbox-images.yml --ref <branch>`).
3. Upon workflow completion, the Summary tab outputs new image tags formatted as `<version>-<short_commit_sha>` (e.g. `1.34.5-abcd1234`).

- Historical version tags persist on GHCR without in-place overwriting, guaranteeing reproducible rollbacks.
- Tag `latest` continuously mutates to point to the newest build; **do not use `latest` in production**.
- **Re-running the workflow without new commits** generates an identical tag and overwrites the existing image. Every distinct image release requires a distinct commit SHA.
- After releasing new tags, update default references in [`README.md`](README.md) and [`server/env.example`](server/env.example).

Reference: [`notes/sandbox/22` Section 8](../sandbox/22-two-deployment-routes.md#8-publishing-images-to-github-container-registry-ghcr).

### 1.2 Pre-upgrade: Check DB Migrations and Create Backup

**PostgreSQL Flyway migrations move forward only.** If an image release introduces new migration scripts, database schemas migrate irrevocably; downgrading Cuebot may fail if legacy code is incompatible with the updated schema.

When syncing with upstream, inspect new database migration scripts first:

```bash
git diff <old_commit> <new_commit> --stat -- cuebot/src/main/resources/conf/ddl/postgres/migrations/
```

If new migrations exist, **perform a database backup prior to deployment** (Section 2).

### 1.3 Executing Image Upgrades

In Portainer -> Stacks -> `opencue` -> **Environment variables**, update the five `OPENCUE_*_IMAGE` tag values (switching to **Advanced mode** allows batch text editing). Then under **Actions** at the bottom:

1. Click **Save settings**. (**Pull and redeploy** remains disabled until settings are saved).
2. Click **Pull and redeploy** (in Web editor mode, labeled **Update the stack**).

Because new tags do not exist locally on the host, Portainer pulls them automatically. (The CE edition's "Re-pull image" is a paid commercial feature and not needed).

Git Repository stacks operate under identical rules: **git pushes never alter image versions automatically**. Tags live in Portainer environment variables and require intentional manual updates, ensuring operator awareness before irreversible migrations run.

- **In-flight frames are not interrupted**. Cuebot is stateless; worker nodes automatically re-register upon Cuebot restart, and frames continue rendering and report completion normally (empirically verified with 150-second frames across restarts).
- Existing containers continue running while new images download; service disruption is limited strictly to container recreation (~30 seconds).
- Docker pulls only modified layers. However, when rebuilding across distinct commits, cuebot and cueweb application layers typically diverge, requiring full downloads (~1 hour depending on studio bandwidth). Portainer displaying "In progress" is normal; if network interruptions occur, re-clicking resumes partially downloaded layers safely.

Reference: [`notes/sandbox/14`](../sandbox/14-registry-workflow.md).

### 1.4 Rollbacks

Revert image tags in Portainer environment variables -> Update stack. Rolling back across verified images is supported.

**Exception**: If an upgrade applied new database migrations, assess schema backwards compatibility before reverting Cuebot, restoring the pre-upgrade database backup if necessary.

**The Flyway image must never revert to versions lacking studio-specific migrations.** Once `R__Studio_widen_host_tags.sql` has applied to the DB, Flyway images missing this script fail validation on boot (`Detected applied migration not resolved locally`, exit code 1). The studio Flyway image includes this patch starting with build `1.34.4-1acac546` (Reference: [`notes/sandbox/32`](../sandbox/32-node-tag-limit.md)).

---

## 2. PostgreSQL Database Backup and Restore

The database holds job lifecycle states and historical records, not final render assets. Losing a single day's data represents "losing yesterday's historical records," not lost render output. **Daily backups are sufficient for typical production.**

### Backup

```bash
docker exec opencue-db pg_dump -U cuebot -d cuebot -Fc -f /tmp/cuebot.dump
docker cp opencue-db:/tmp/cuebot.dump ./cuebot-$(date +%Y%m%d).dump
```

### Restore

```bash
docker cp ./cuebot-YYYYMMDD.dump opencue-db:/tmp/restore.dump
docker exec opencue-db pg_restore -U cuebot -d cuebot --clean --if-exists /tmp/restore.dump
```

**`--if-exists` is mandatory.** When restoring to a freshly initialized database using only `--clean`, `pg_restore` emits hundreds of fatal errors attempting to drop non-existent entities (474 errors observed), exiting with code 1. Adding `--if-exists` ensures exit code 0 across both empty and populated databases (verified).

Prior to restoring, stop Cuebot (Portainer -> Containers -> Stop `opencue-cuebot`), perform the restore, and restart Cuebot to prevent concurrent write contention.

Verify restore status:

```bash
docker exec opencue-db psql -U cuebot -d cuebot -c \
  "select (select count(*) from host) hosts, (select count(*) from show) shows,
          (select max(version::int) from flyway_schema_history) schema_version"
```

Backups must be archived onto **physically separate storage hosts**. Cron backups require host shell access; under Portainer-only setups, deploy a containerized backup sidecar.

Reference: [`notes/sandbox/11` Section 6](../sandbox/11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups), [`notes/sandbox/16`](../sandbox/16-portainer-and-ssh-division.md).

---

## 3. Pruning Historical Database Records

Jobs completed longer than 72 hours are shifted to history tables (`job_history`, `layer_history`, `frame_history`). **OpenCue includes no automated pruning mechanism for history tables**, causing linear unbounded database growth.

Periodically purge historical records:

```sql
-- Step 1: Verify impacted row count
SELECT count(*) FROM job_history
WHERE int_ts_stopped > 0
  AND int_ts_stopped < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');

-- Step 2: Delete expired jobs (cascades automatically to layer_history and frame_history)
DELETE FROM job_history
WHERE int_ts_stopped > 0
  AND int_ts_stopped < EXTRACT(EPOCH FROM NOW() - INTERVAL '90 days');
```

**Condition `int_ts_stopped > 0` is strictly mandatory.** Active and in-flight jobs store `int_ts_stopped = 0`. Because `0 < (now - 90 days)` always evaluates to true, omitting this check **accidentally deletes historical logging for active in-progress jobs**.

Reference: [`notes/sandbox/11` Section 6](../sandbox/11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups), [`notes/sandbox/17` Scenario 12](../sandbox/17-troubleshooting.md#scenario-12-manual-database-purge-accidentally-deletes-active-or-running-job-history).

---

## 4. Frame Log Retention

Render nodes stream frame logs into network storage (`CUE_FRAME_LOG_DIR`). OpenCue does not manage filesystem log lifecycles. Ensure IT implements a scheduled retention cleanup policy on the storage server (e.g. deleting files older than 60 days).

Capacity estimation: Sandbox testing observed ~6.6 KB average per frame log, though verbose DCC render outputs can scale higher. Observe real-world capacity growth across the initial operational month.
Reference: [`notes/sandbox/15`](../sandbox/15-storage-planning.md).

---

## 5. Routine Operations Cheat Sheet

### Jobs

| Action | Command |
|---|---|
| Pause / Resume | `cueman -pause <job>` / `cueman -resume <job>` |
| Terminate and purge from list | `cueman -force -term <job>` |
| Retry failed frames | `cueman -force -retry <job>` |
| Retry frame subset | `cueman -force -retry <job> -range 10-20` |
| Eat (Drop) failed frames | `cueman -force -eat <job>` |
| Kill in-flight frames | `cueman -force -kill <job>` |
| List frame statuses | `cueman -lf <job>` |

**To clear completed jobs from UI queues, use `cueman -term`**. `cueadmin -kill` terminates running frames only, leaving the job record visible in the queue.

OpenCue classifies failed frames as **DEAD** (not FAILED). When an upstream frame is DEAD, downstream tasks block permanently in **DEPEND** until the upstream task is resolved.
Reference: [`notes/sandbox/20`](../sandbox/20-dependencies-and-operations.md).

### Render Nodes

| Action | Command |
|---|---|
| List hosts (Allocations, states) | `cueadmin -lh` |
| Lock / Unlock host | `cueadmin -force -lock -host <hostname>` / `-unlock` |
| Move host allocation | `cueadmin -force -move <allocation> -host <hostname>` |

**Removing Decommissioned Nodes**: When a node is powered off or removed, OpenCue marks it `DOWN` after ~5 minutes. Only then can host records be deleted. If a node is currently `UP`, locking via CLI fails because Cuebot cannot establish return callbacks to dead hosts:

```python
import opencue
opencue.api.findHost("RENDER01").delete()
```

**Cancelling Active Tasks on a Specific Host** (e.g. when an artist arrives in the morning):

```python
import opencue
for proc in opencue.api.getProcs(host=["WS01"]):
    proc.kill()
```

Cancelled frames return to the waiting queue and re-render on another available node without failing or incrementing retry counts.

### Shows

- Adding Shows: Append to `OPENCUE_INIT_SHOWS` and Update Stack in Portainer; the `init` container registers shows and binds default subscriptions automatically.
- **Shows that have processed jobs cannot be deleted; they can only be deactivated**:

  ```python
  import opencue
  show = opencue.api.findShow("projA")
  for sub in show.getSubscriptions():
      sub.delete()
  show.setActive(False)
  ```

Reference: [`notes/sandbox/20`](../sandbox/20-dependencies-and-operations.md).

### Services

- Adding Services: Append definitions to `OPENCUE_INIT_SERVICES` and Update Stack.
- **Modifying existing services**: Edit via CueGUI or CueWeb Services view. The `init` container is idempotent and never overwrites pre-existing service records.

### Adding New DCC Versions

Example scenario: Integrating Maya 2025 and Houdini 21.0.xxx. Submission tools and pipeline tool shares **require zero code modifications**; version tags are reported by DCCs dynamically and services are queried by tag matching.

The **version string** governs configuration mapping between `dcc.toml` and service tags:

| DCC | Version String (Reported by DCC) | Service Tag |
|---|---|---|
| Maya | `2025` | `maya_2025` |
| Houdini | Full release, e.g. `21.0.440` | `houdini_21_0_440` |
| Nuke | Full release, e.g. `15.1v5` | `nuke_15_1v5` |

Tags replace `.` with `_`. Version strings configured in `dcc.toml` must match reported versions **identically**, otherwise `ocrun` terminates with exit code 127 (`is not configured`).

1. **Server**: Add the service to `OPENCUE_INIT_SERVICES` with strict version binding tags only (never include `general`), e.g. `{"name":"maya2025","tags":["maya_2025"],"min_memory_gb":4}`, then Update Stack in Portainer; see [`01-server.md` Section 4](01-server.md#4-bootstrapping-shows-subscriptions-and-services).
2. **Render Nodes & Workstations with New DCCs Installed**:
   - In `C:\opencue\dcc.toml`, append version and executable paths; see [`02-render-nodes.md` Section 5](02-render-nodes.md#5-invoking-dcc-applications-ocrun).
   - In `C:\opencue\rqd.conf`, append both tags to `RQD_TAGS` (e.g. `maya2025 maya_2025`); see [`02-render-nodes.md` Section 6](02-render-nodes.md#6-dispatch-tags-rqd_tags).
   - **Restart RQD**: RQD reads tags only at startup (`dcc.toml` is re-parsed per frame).
   - Nodes lacking the new DCC version require no changes.
3. **Workstations Using New Versions**:
   - Maya: Module files placed in `Documents\maya\modules\` or shared `MAYA_MODULE_PATH` load across versions automatically; create shelf buttons in the new version UI; see [`03-workstations.md` Section 6](03-workstations.md#6-submitting-directly-from-maya).
   - Houdini: Package definitions placed in shared `HOUDINI_PACKAGE_DIR` load automatically; if deployed into `Documents\houdini<ver>\packages\`, copy to the new version folder; see [`03-workstations.md` Section 7](03-workstations.md#7-submitting-directly-from-houdini).
   - Nuke: `NUKE_PATH` is version-agnostic; no changes needed.
4. **Verification** (On one updated machine):
   - Run `C:\opencue\venv\Scripts\ocrun.exe` with no arguments; confirm new versions and executable paths display.
   - Run `cueadmin -lh` or check CueWeb Monitor Hosts; confirm node tags include the new DCC.
   - Submit a single test frame from the new DCC UI: confirm dialog title does **not** report `no service has the ... tag`, and verify the frame dispatches and renders successfully.

Empirically verified across Maya 2027, Houdini 22.0.429, and Nuke 17.0v1. When adding new versions, run regression test passes (Section 9). Monitor [Node Tag String Length Limits](02-render-nodes.md#node-tag-string-length-limits) when accumulating large numbers of tags.

---

## 6. Self-hosted Registry Garbage Collection

Applicable only when operating private registries using [`server/registry.portainer.yml`](server/registry.portainer.yml). Each image release consumes ~6 GB disk space.

Deleting images requires two prerequisites (otherwise the registry returns HTTP 404):

1. Registry must launch with `REGISTRY_STORAGE_DELETE_ENABLED=true` (included in template).
2. Manifest deletion requests must supply Accept header `application/vnd.oci.image.index.v1+json` (as `docker buildx` pushes OCI manifests).

After deleting manifests, execute `garbage-collect` inside the registry container to physically reclaim storage space.
Reference: [`notes/sandbox/14`](../sandbox/14-registry-workflow.md).

---

## 7. Troubleshooting Quick Reference

Consult the diagnostic index in [`17-troubleshooting.md`](../sandbox/17-troubleshooting.md).
Three most common zero-error silent stalls:

| Symptom | Root Cause |
|---|---|
| Frames stuck in `WAITING` | Tag mismatch, facility mismatch, or show missing allocation subscription |
| Frames stuck in `RUNNING` with zero log generation | Cuebot cannot reach render node port 8444 (DNS resolution failure or Windows Firewall) |
| Host status `LOCKED` | CueNIMBY schedule currently active, or schedule configured across midnight |

---

## 8. Pipeline Tool Distribution

### Distribution Principles

| Component | Ingestion Timing | Update Strategy |
|---|---|---|
| Submission Dialogs (`opencue_*_submit.py`) | Evaluated dynamically on each submission click | Safe to overwrite in place |
| In-DCC Launchers (`opencue_*_launcher.py`), Nuke `menu.py` | Ingested on DCC startup/import and cached in memory | Safe to overwrite; **running DCC sessions require restart** to reload |
| **Runtime Execution Scripts** (Houdini `opencue_houdini_render.py`, worker execution scripts) | Evaluated by worker nodes during frame execution (often hours post-submission) | **Pinned in versioned release directories; immutable post-release** |

Jobs store the absolute path to the execution script. Overwriting scripts in place while jobs are queued risks executing unverified code during render runtime.

### Directory Structure

```
P:\pipeline\opencue\
    client\maya\                 Maya submission tools (In-place updates)
    releases\
        2026.09.25\client\houdini\   Versioned release (Immutable post-release)
        2026.10.02\client\houdini\
```

Houdini submission files reside inside the same release directory. Submission dialogs resolve paths relative to their own location, ensuring jobs permanently bind to the tool release active at submission time.

### Publishing Releases

1. Create a versioned directory (e.g. `releases\2026.10.02\client\houdini\`), copying the three `.py` files from [`client/houdini/`](client/houdini/).
2. Update `opencue.json` in the studio shared `HOUDINI_PACKAGE_DIR` to point to the new directory.
3. Takes effect when artists restart Houdini. Existing queued jobs continue referencing the legacy release directory.

**Rollback**: Update `opencue.json` back to the prior release directory.

### Pruning Legacy Releases

Confirm no active or queued jobs reference the target release directory before pruning:

```python
import opencue
for job in opencue.api.getJobs(include_finished=False):
    for layer in job.getLayers():
        if "releases/2026.09.25/" in layer.data.command:
            print(job.name())
```

Delete only when the script returns zero references.

---

## 9. Post-Upstream Regression Testing

Maya, Houdini, and Nuke submission tools interface with internal CueSubmit classes:

| Class Dependency | Tool Consumer |
|---|---|
| `SettingsWidgets.InMayaSettings`, `Constants.MAYA_RENDER_CMD`, `Submission.buildMayaCmd` | Maya |
| Shell layer `commandTextBox` (Inherits Shell layer for command dispatch) | Houdini, Nuke |
| `Widgets.CueSelectPulldown`, `CueLabelToggle`, `CueSubmitWidget.chunkInput`, `frameBox.frameSpecInput` | Houdini |
| `JobTypes.JobTypes.SETTINGS_MAP` | All DCC tools |

After syncing upstream releases or upgrading client `cuesubmit` packages, execute the headless test suite:

```bat
set QT_QPA_PLATFORM=offscreen
C:\opencue\venv\Scripts\python.exe notes\sandbox\lab\check_submit_tools.py
```

This verifies assembled command lines, services, frame ranges, and chunk parameters across all three dialogs **without submitting jobs**.
All checks must output `PASS`. Append `--submit` to execute live test jobs to verify full pipeline execution.
Test script located at [`notes/sandbox/lab/check_submit_tools.py`](../sandbox/lab/check_submit_tools.py).
