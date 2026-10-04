# 24 — Dispatch Behavior, High-Volume Frames, and Monitoring

Empirical benchmark testing of secondary operational features identified in [`19-verification-summary.md`](19-verification-summary.md).

Test Fleet Topology:

| Node | Role | Allocation | Cores |
|---|---|---|---|
| `LAPTOP-ULJICLO8` | Windows native RQD (Simulating artist workstation) | `local.desktop` | 8 |
| `render02` | Linux container, Rust RQD (Simulating dedicated render node) | `local.general` | 8 |

---

## 1. Concurrent Workstation and Dedicated Node Fleet

### 1. Unified Job Distributed Across Diverse Fleets

Submitted non-OS-specific test tasks invoking `hostname`.

**40-Frame Job**: Routed entirely to `render02`; finished in 36 seconds before `LAPTOP` completed its polling interval.

**500-Frame Job**:

| Node | Frame Count | Average Frame Duration |
|---|---|---|
| `render02` | 393 | 5.96s |
| `LAPTOP` | 107 | ~1.4s |

`LAPTOP` dispatching timeline:
- 06:35:13: Job submitted.
- 06:36:59: `LAPTOP` picked up initial task batch (~1m 45s after submission).
- 06:36:59–06:37:10: Executed 83 frames in rapid succession.
- 06:37:30: Executed 8 frames.
- 06:37:49: Executed 14 frames.

**Observations**:
- Cuebot dispatches subsequent frames immediately to worker nodes as tasks finish; secondary nodes join when their periodic report boundaries align.
- For short tasks (1–6 seconds), initialization latency distorts distribution ratios. Under real production workloads lasting minutes to hours, frame distribution converges toward physical core ratios.

### 2. Workstation Preemption During Active Rendering (Morning Workday Scenario)

Simulated via `host.lock()`:

```
06:45:31  Frame starts (ping -n 121, ~2 minutes duration)
06:45:35  Host locked: LAPTOP -> LOCKED; submitted new Windows frame
06:47:33  Initial frame finishes: SUCCEEDED, exit 0; pending frame holds in WAITING
06:47:44  Host unlocked
06:48:03  Pending frame dispatched and completed (19s after unlock)
```

**Host locking does not terminate active executing frames**; it merely prevents dispatching new work. Running tasks proceed until natural completion.

### 3. Immediate Frame Termination via Operator Preemption

```python
host = opencue.api.findHost("LAPTOP-ULJICLO8")
host.lock()
for proc in opencue.api.getProcs(host=["LAPTOP-ULJICLO8"]):
    proc.kill()
```

Outcome:
- Windows subprocess terminated immediately.
- Frame **returned to `WAITING`** with exit status 1; retry counts did not increment (not counted as render failure).
- Re-routed to the next available worker from scratch.

**Operational Decision**: Routine morning workday locking should avoid killing active frames automatically. Operators cancel tasks manually through CueGUI when interactive workstation resources are urgently required.

---

## 2. High-Volume Workload Stress Test

Submitted 500 frames (1 core requested per frame):

| Metric | Result |
|---|---|
| Total Duration | ~4.5 minutes (06:35:13 → 06:39:41) |
| Outcome | 500 frames SUCCEEDED; **0 frames DEAD** |
| Cuebot Memory Footprint | 683 MiB (Prior peak was 555 MiB) |
| PostgreSQL Memory Footprint | 127 MiB |
| Submission Latency | ~1 second |

Throughput across 16 test cores reached ~1.85 frames/second. In production environments, DCC rendering times form the primary bottleneck rather than Cuebot scheduling overhead.

---

## 3. Portainer Git Mode: Manifest Edits Recreate Targeted Services Only

Validating granular update behaviors: commit `20338f8e` modified only Cuebot arguments (`--metrics.prometheus.collector=${CUEBOT_METRICS_COLLECTOR:-false}`). Pushing to `studio/release`:

| Container | Prior Startup Time | Post-Update Startup Time |
|---|---|---|
| db | 05:40:49 | 05:40:49 |
| cuebot | 05:41:03 | **07:00:30 (Recreated)** |
| rest-gateway | 05:41:14 | 05:41:14 |
| cueweb | 05:41:20 | 05:41:20 |
| init | 06:14:31 | 07:00:45 (One-shot sweep) |

Only Cuebot recreated. Downstream dependent services (`rest-gateway`) remained uninterrupted.

Updating environment variables directly in Portainer requires triggering **Pull and redeploy**, which performs a complete recreation cycle across all stack containers (~58s). External networks bound to other stacks remain unaffected.

---

## 4. Monitoring Infrastructure: Prometheus + Grafana

### Cuebot Telemetry

Internal metrics exposed on port 8080 (`/metrics`):
- Default: `cue_frames_completed_total`, `cue_jobs_completed_total`, `cue_host_reports_received_total`, `cue_job_core_seconds`.
- With `metrics.prometheus.collector=true`: Thread pool and queue metrics (booking, dispatch, manage, report queues), `cue_cores_idle`, `cue_cores_total`.

Label notice: Base metrics use `cuebot_host`; queue metrics use `cuebot_hosts`.

### Inline Configuration Deployment

To avoid mounting host files in Portainer web editor, configurations are embedded via compose `configs`:

```yaml
configs:
  prometheus_config:
    content: |
      scrape_configs:
        - job_name: cuebot
          static_configs: [{targets: ['cuebot:8080']}]
```

Deployed via [`notes/deploy/server/monitoring.portainer.yml`](../deploy/server/monitoring.portainer.yml).

### Resource Footprint

| Container | Memory | CPU |
|---|---|---|
| prometheus | 26 MiB | ~0% |
| grafana | 94 MiB | 0.4% |
| db-exporter | 8 MiB | ~0% |

### Upstream Grafana Dashboard Compatibility

- `PostgreSQL.json`: Fully functional.
- `cuebot.json`: **Largely obsolete**. Last updated in 2021; references 9 deleted metrics (`cue_booked_procs`, etc.) and incorrectly applies `rate()` over gauge metrics. Custom dashboards are recommended (see [`05` Issue #19](05-upstream-issues.md#19-upstream-cuebot-grafana-dashboard-is-outdated)).

---

## 5. Loki Log Backend (Evaluated Only, Not Tested)

| Aspect | Analysis | Reference |
|---|---|---|
| Global Scope | Controlled globally via `log.loki.url`; reroutes all frame logs to Loki, bypassing disk | `opencue.properties:94-101` |
| Failure Mode | Source code indicates **RQD aborts frames if Loki endpoints become unreachable** | `opencue.properties` |
| RQD Dependencies | `loki-urllib3-client` listed under test dependencies only; omitted in standard RQD | `rqd/pyproject.toml` |
| Missing Dependency Behavior | `LokiLogger.__init__` silently aborts on `ImportError`, triggering runtime attribute errors | `rqd/rqlogging.py:124-130` |
| CueWeb Integration | Enabled at build-time via `NEXT_PUBLIC_LOKI_URL`; disabled in GHCR images | `cueweb/lib/loki` |

**Conclusion**: Do not deploy Loki. File-based logging is reliable. Centralized logging introduces single points of failure capable of terminating rendering across the entire fleet.
