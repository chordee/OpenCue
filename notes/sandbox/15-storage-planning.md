# 15 — Storage Capacity Planning

Consolidated storage metrics and operational planning based on empirical measurements (11 jobs / 34 frames, including commercial Houdini, Maya, and Nuke renders).

## Empirical Measurements

| Component | Measured Usage | Extrapolation Guidance |
|---|---|---|
| Frame Logs (`.rqlog`) | 19 files, average **6.6 KB** (3.9–10 KB) | **Do not extrapolate** (Toy scenes) |
| Render Outputs | 16 files, average **239 KB** | 320×240 test frames; **Do not extrapolate** |
| PostgreSQL Database | **13 MB** | Baseline schema overhead |
| Docker Images | 59.4 GB (10.9 GB reclaimable) | Includes existing host images |
| Docker Build Cache | **50.0 GB** (16.0 GB reclaimable) | See Build Server section |
| Docker Volumes | 6.7 GB (2.7 GB reclaimable) | |
| Docker Containers | 579 MB (561 MB reclaimable) | Stopped container overhead |
| Windows Node Scratch | 56 KB | `C:\opencue\tmp` |

## Growth Profiles Across Subsystems

### 1. Build Server: Build Cache Is the Largest Hidden Footprint

**50 GB generated after a handful of test builds.**
Docker buildx cache does not auto-purge by default. Rebuilding Next.js (CueWeb) and Gradle (Cuebot) continuously adds layer cache.

```bash
docker system df                             # Check usage
docker builder prune                         # Remove unused cache
docker builder prune --keep-storage 20GB     # Enforce cache cap
```

Set retention caps in CI pipelines. Building CueWeb also demands multiple gigabytes of memory.

### 2. Private Registry: ~6 GB per Version

Footprint per release:
- cueweb: 2.52 GB
- flyway: 2.15 GB
- cuebot: 1.06 GB
- rest-gateway: 184 MB

Retaining 10 versions requires ~60 GB. Execute garbage-collection routines periodically after deleting manifests (see [`14-registry-workflow.md`](14-registry-workflow.md)).

### 3. PostgreSQL Database: Unbounded Growth Without Purging

Baseline starts at 13 MB. Cuebot relocates jobs completed for over 72 hours into historical tables (`job_history`, `layer_history`, `frame_history`), **with zero automated deletion routines** (see [`11` Section 6](11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups)).

Recommendations:
- Establish a retention policy (e.g., 90 days) using scheduled purge scripts.
- Guard deletion scripts with `int_ts_stopped > 0` to protect active jobs.
- Perform `VACUUM FULL` or `pg_repack` to reclaim physical disk space.
- Automate logical backups via `pg_dump`.

### 4. Frame Logs: High Volume

Average test size of 6.6 KB reflects trivial workloads. Real production renders generate verbose shader outputs, warnings, and profiling data, easily averaging 1–5 MB per frame.

Volume scales with throughput:
`50,000 frames/day × 1 MB/file ≈ 50 GB/day`

Recommendations:
- Enforce log retention limits (e.g., 30 days) on shared storage.
- Deleting raw `.rqlog` files does not corrupt Cuebot database history (CueWeb simply returns HTTP 404 on missing logs).

### 5. Render Outputs: Largest Overall Footprint

Test outputs (239 KB/frame) cannot be extrapolated. Production 2K/4K EXR renders consume dozens to hundreds of megabytes per frame. Storage quotas belong to pipeline storage administration. Note that CueWeb web previews require 8-bit proxy formats (PNG/JPEG), as browsers cannot decode EXR natively.

### 6. Docker Host: Container Log Rotation

Container stdout/stderr logs using the default `json-file` driver **have no file size caps by default**.
Configure log rotation in compose manifests:

```yaml
logging:
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"
```

Maintain host health via routine pruning:

```bash
docker container prune
docker image prune
```

### 7. Windows Render Node Scratch Directories

Local temporary paths to monitor:
- `C:\opencue\tmp`: RQD subprocess scratch directories.
- `C:\opencue\tmp\nuke`: Nuke local disk cache.
- DCC user caches (Houdini, Maya).

Schedule cleanup scripts or flush scratch folders during `rqd-start.bat` launch (ensuring active frames are not deleted).

## Storage Questions for Studio IT

| Area | Topic |
|---|---|
| Shared Storage | Frame log and render output quotas, retention management |
| Registry Server | Storage allocation, retention limits per release |
| Build Server | Storage sizing (build cache consumes tens of GBs), RAM allocation |
| Linux Host | Root disk sizing, isolation from other services |
| Backup Targets | Backup destinations and retention cycles for DB and registry volumes |
