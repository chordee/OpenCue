# 06 — Resource Usage Benchmarks

Empirical measurements conducted to determine "target host specification requirements", rather than estimates.

## Test Conditions

- Environment: WSL2 Ubuntu 24.04, Docker Desktop (16 CPUs / 19.2 GiB available)
- Stack: db + flyway + cuebot + rqd (full sandbox)
- Workload: `load_test_jobs.py simple -n 50 --sleep-seconds 2-5 --batch-size 10`
  (50 jobs, 3 frames each, 150 frames total)

## Measurement Results

### Idle (Startup completed, no active jobs)

| Container | CPU | Memory |
|---|---|---|
| cuebot | 0.52% | **406 MiB** |
| db | 0.02% | 33 MiB |
| rqd | 0.00% | 3 MiB |

### Under Load (Peak 50-job dispatching)

| Container | CPU | Memory |
|---|---|---|
| cuebot | **40.6%** | **534 MiB** |
| db | 19.0% | 70 MiB |
| rqd | 14.4% | 11 MiB |

### Post-Load (Frames completing sequentially)

| Container | CPU | Memory |
|---|---|---|
| cuebot | 0.62% | 555 MiB |
| db | 0.19% | 80 MiB |
| rqd | 1.35% | 13 MiB |

(`docker stats` calculates CPU% where "1 core = 100%".)

## Conclusions

**Under this workload, the entire stack peaked at ~620 MiB RAM and less than 1 CPU core.**

Furthermore, the target production environment **does not run rqd on the server** (the host server does not execute renders), so only cuebot + db are required:
**Peak ~600 MiB RAM, ~0.6 CPU cores.**

Cuebot is a Java (Spring Boot) service. Memory starts at 406 MiB and climbs gradually under load to 555 MiB, **with no runaway consumption observed**. It is the only component in the stack warranting memory monitoring.

**Subsequent Benchmark** ([`24`](24-dispatch-and-monitoring.md)): Under two nodes and a burst of 500 frames, Cuebot used 683 MiB and DB used 127 MiB, remaining well within container resource limits (4G / 2G). The optional monitoring stack (Prometheus + Grafana + exporter) added approximately 130 MiB.

## Host Sizing Interpretation

| Specification | Assessment |
|---|---|
| 2 GB RAM | Bare minimum. Headroom is extremely tight after accounting for host OS usage; not recommended. |
| 4 GB RAM | Feasible. Providing a 2G limit for the cuebot container leaves sufficient headroom. |
| 8 GB+ RAM | Plentiful, comfortably accommodating CueWeb and monitoring stacks. |
| CPU | 2+ cores is sufficient; peak usage in this test was under 1 core. |

**Important Caveat**: This benchmark used only **1 render node and 150 frames**. In an enterprise production farm, Cuebot workload scales with `render node count × concurrent frames` — every RQD sends a host report every 5 seconds, which Cuebot processes and writes to the DB. With dozens of nodes, baseline workload will be noticeably higher than this test.

Therefore, the table above applies to evaluation, prototyping, and small-scale farms. When scaling to dozens of Windows render nodes, remeasurement is required, particularly regarding Cuebot Java heap and PostgreSQL connection pool sizing.

## Storage Considerations

This test duration was too brief to reflect long-term storage trends. Key areas to monitor include:

- PostgreSQL `db-data`: Job and frame history accumulates continuously.
  Cuebot archives jobs to historical tables 72 hours after completion (`history.archive_jobs_cutoff_hours`), but **this is a table move, not deletion, with no automated purge mechanism**, causing database size to grow indefinitely. See [`11-production-risks-and-todos.md` Section 6](11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups) for details and `pg_dump` backup routines.
- Frame Logs: Written by render nodes to shared storage, **consuming no host server space**, though total volume becomes substantial (one `.rqlog` per frame).

**For complete storage capacity planning (including benchmark figures, growth characteristics, and cleanup strategies), refer to [`15-storage-planning.md`](15-storage-planning.md)** — covering build machine cache, registry, PostgreSQL, frame logs, render outputs, Docker host, and Windows node local temporary directories.
