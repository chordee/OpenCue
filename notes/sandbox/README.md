# OpenCue Sandbox Research & Test Logs

Detailed notes documenting the complete process of standing up an OpenCue sandbox environment locally, pitfalls encountered, and adaptations necessary for production deployment on Linux + Portainer.

## Context & Objectives

- Local host is Windows 11, but the **target production Docker host is Linux**, fronted by Portainer.
- Testing was intentionally **conducted entirely inside WSL2 Ubuntu** rather than native Windows paths.
  Rationale: Paths, permissions, and bind-mount behaviors match the production Linux host; notes can be migrated directly without Windows-specific workarounds.
- Repo fork: `chordee/OpenCue`, active working branch `studio/main` (originally `demo/sandbox-test`), production release branch `studio/release` (default branch on GitHub).

## Division of Responsibilities: `notes/sandbox/` vs. `notes/deploy/`

| Directory | Scope |
|---|---|
| **[`notes/deploy/`](../deploy/README.md)** | **Production Deployment**: Step-by-step instructions, production configs, and pre-built GHCR image references. |
| `notes/sandbox/` (This directory) | **Test Logs & Evidence**: Testing logs, pitfall retrospectives, source code analysis, and empirical benchmarks. |

**To deploy OpenCue, begin with [`notes/deploy/README.md`](../deploy/README.md).** This sandbox directory serves as technical evidence and architectural rationale; consult it when troubleshooting or seeking the reasoning behind operational decisions.

## Topic Index

| File | Content Summary |
|---|---|
| [`00-environment-and-prerequisites.md`](00-environment-and-prerequisites.md) | Local test environment inventory, component versions, and directory structures |
| [`01-platform-differences-and-portainer.md`](01-platform-differences-and-portainer.md) | Upstream compose limitations on Linux Docker hosts and Portainer |
| [`02-target-architecture.md`](02-target-architecture.md) | Target studio architecture, network topology, and end-to-end frame lifecycle diagram |
| [`03-containers.md`](03-containers.md) | In-depth breakdown of each container role, configuration, and production considerations |
| [`04-deployment-process.md`](04-deployment-process.md) | Step-by-step startup log, pitfall retrospectives, and resolution evidence |
| [`05-upstream-issues.md`](05-upstream-issues.md) | Upstream OpenCue project bugs/omissions discovered and suggested patches |
| [`06-resource-usage.md`](06-resource-usage.md) | Empirical CPU/memory resource consumption metrics for host sizing |
| [`07-portainer-deployment-log.md`](07-portainer-deployment-log.md) | Full workflow for deploying and verifying stacks via Portainer API |
| [`08-windows-node-log.md`](08-windows-node-log.md) | Native Windows RQD installation, configuration, and 5 critical pitfalls |
| [`09-nimby-and-hybrid-fleet.md`](09-nimby-and-hybrid-fleet.md) | Workstation vs. dedicated node division, CueNIMBY schedule verification |
| [`10-windows-client-tools.md`](10-windows-client-tools.md) | CueGUI / CueSubmit installation and config paths on Windows |
| [`11-production-risks-and-todos.md`](11-production-risks-and-todos.md) | Production scalability considerations: DNS, UNC, firewalls, bootstrapping, backups |
| [`12-real-dcc-rendering.md`](12-real-dcc-rendering.md) | Real Houdini / Maya / Nuke rendering, multi-version coexistence, environment pitfalls |
| [`13-cueweb-and-rest-gateway.md`](13-cueweb-and-rest-gateway.md) | Web UI deployment, JWT authentication, and cross-platform log viewer workarounds |
| [`14-registry-workflow.md`](14-registry-workflow.md) | Build -> push -> Portainer pull validation and private registry requirements |
| [`15-storage-planning.md`](15-storage-planning.md) | Empirical disk consumption metrics, growth characteristics, and pruning strategies |
| [`16-portainer-and-ssh-division.md`](16-portainer-and-ssh-division.md) | Division of capabilities between Portainer UI vs. host SSH root privileges |
| [`17-troubleshooting.md`](17-troubleshooting.md) | **Primary Troubleshooting Index**: Symptoms -> Root causes -> Diagnostic manual |
| [`18-role-checklists.md`](18-role-checklists.md) | Role-based preparation checklists (**Superseded by [`notes/deploy/`](../deploy/README.md)**) |
| [`19-verification-summary.md`](19-verification-summary.md) | **Authoritative Verification Table**: Exhaustive status of verified vs. unverified items |
| [`20-dependencies-and-operations.md`](20-dependencies-and-operations.md) | Job dependencies (chain / diamond / fan-in) and common administrative commands |
| [`21-service-and-resource-model.md`](21-service-and-resource-model.md) | Relational mapping of Layer, Username, Facility, Service, and Dependency entities |
| [`22-two-deployment-routes.md`](22-two-deployment-routes.md) | Single compose stack supporting both Portainer and native Docker Compose |
| [`23-portainer-git-mode.md`](23-portainer-git-mode.md) | Git repository deployment mode in Portainer; polling, webhook, and manual updates |
| [`24-dispatch-and-monitoring.md`](24-dispatch-and-monitoring.md) | Hybrid fleet dispatching, 500-frame stress tests, Prometheus/Grafana, and Loki analysis |
| [`25-maya-submission.md`](25-maya-submission.md) | Upstream Maya plugin limitations and decoupled two-tier submission tool validation |
| [`26-ocrun-wrapper.md`](26-ocrun-wrapper.md) | Cross-platform Python `ocrun` runner replacing per-version `.bat` wrappers |
| [`27-houdini-submission.md`](27-houdini-submission.md) | Houdini two-tier submission tool: supported nodes, simulation chunking, husk mode |
| [`28-maya-crash-reporting.md`](28-maya-crash-reporting.md) | Maya post-render crash reporter dialogs: resolving `ALLUSERSPROFILE` licensing omission |
| [`29-frame-timezone.md`](29-frame-timezone.md) | Resolving RQD hardcoded `PST8PDT` frame timezones via `[UseHostEnvVar]` |
| [`30-arnold-licensing.md`](30-arnold-licensing.md) | Arnold license checkout failures masquerading as false successes; `ocrun` error trapping |
| [`31-nuke-submission.md`](31-nuke-submission.md) | Nuke two-tier submission tool: bypassing upstream limitations, chunk frame specs |
| [`32-node-tag-limit.md`](32-node-tag-limit.md) | Resolving 128-character node tag registration crash via studio Flyway migration |
| [`33-rebuild-from-scratch.md`](33-rebuild-from-scratch.md) | End-to-end clean room rebuild from `notes/deploy/` on a blank DB |
| [`34-houdini-pdg-scheduler.md`](34-houdini-pdg-scheduler.md) | Custom Houdini PDG OpenCue scheduler architecture, design, and 300-work-item tests |
| [`lab/`](lab/) | Testing scripts (submission, rendering, mount checks) and sandbox `.env` records |

## Suggested Reading Order by Role

- **Architecture & Fundamentals**:
  Read [`02-target-architecture.md`](02-target-architecture.md) (with Frame lifecycle diagrams) and [`03-containers.md`](03-containers.md).
- **Production Deployment Engineers**:
  Follow **[`notes/deploy/README.md`](../deploy/README.md)** as the primary guide. Consult [`07-portainer-deployment-log.md`](07-portainer-deployment-log.md), [`08-windows-node-log.md`](08-windows-node-log.md), and [`14-registry-workflow.md`](14-registry-workflow.md) for background evidence.
- **Pipeline TDs & DCC Engineers**:
  Read [`09-nimby-and-hybrid-fleet.md`](09-nimby-and-hybrid-fleet.md), [`10-windows-client-tools.md`](10-windows-client-tools.md), [`12-real-dcc-rendering.md`](12-real-dcc-rendering.md), [`25-maya-submission.md`](25-maya-submission.md), [`27-houdini-submission.md`](27-houdini-submission.md), [`31-nuke-submission.md`](31-nuke-submission.md), and [`34-houdini-pdg-scheduler.md`](34-houdini-pdg-scheduler.md).
- **IT Infrastructure, Security & System Admins**:
  Read [`11-production-risks-and-todos.md`](11-production-risks-and-todos.md), [`15-storage-planning.md`](15-storage-planning.md), and [`16-portainer-and-ssh-division.md`](16-portainer-and-ssh-division.md).
- **Troubleshooting In-Flight Incidents**:
  Consult **[`17-troubleshooting.md`](17-troubleshooting.md)** directly to map error keywords to root causes and fixes.

## Glossary of Terms

| Component | Role |
|---|---|
| Cuebot | Core scheduler and brain of the render farm; exposes gRPC on port 8443 |
| RQD | Render Queue Daemon running on render nodes; executes frame commands |
| Flyway | Database schema migration utility; runs to completion on startup |
| PostgreSQL | Central relational database storing jobs, frames, layers, and host states |
| REST Gateway | Bridges gRPC into HTTP/JSON for CueWeb |
| CueWeb | Web-based monitoring and management portal |
| CueGUI | Desktop monitoring client (Cuetopia / CueCommander) |
| CueSubmit | Desktop and in-DCC job submission interface |
| CueNIMBY | Artist workstation tray utility managing availability schedules |
