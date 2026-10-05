# 23 — Portainer Git Repository Deployment Mode

Rather than pasting raw YAML manifests into Portainer's web editor, Portainer can **track Git repositories directly**, pulling manifest updates automatically or via webhooks.

Validated on Portainer CE 2.39.1 against repository `chordee/OpenCue` on branch `studio/main`.

---

## 1. Migrating from Web Editor Stack to Git Stack

### Avoiding Name Collisions

The compose manifest declares explicit `container_name`, network, and volume definitions. Launching a Git stack alongside an existing web editor stack triggers naming conflicts.

### Safe Migration Procedure: Stop the Existing Stack

1. Perform database backup (see [`notes/deploy/04` Section 2](../deploy/04-operations.md#2-postgresql-database-backup-and-restore)).
2. Stop the existing stack in Portainer UI.
3. Create new Git repository stack.

**Stopping vs. Deleting**:
Stopping a stack halts and unbinds container ports while **preserving all named volumes** (`opencue-db-data`).
Because the Git stack specifies identical volume names, it seamlessly binds to existing PostgreSQL data:

| Entity | Prior to Migration | After Migration |
|---|---|---|
| Hosts | 2 | 2 |
| Services | 13 | 13 |
| Shows | 3 | 3 |
| Job History | 41 | 41 |

Both nodes reregistered as `UP` / `OPEN`; CueWeb responded with HTTP 200.

### Creating the Repository Stack

Portainer UI: Stacks → Add stack → Build method: **Repository**:

| Field | Configuration |
|---|---|
| Repository URL | `https://github.com/chordee/OpenCue` |
| Repository reference | `refs/heads/studio/main` |
| Compose path | `notes/deploy/server/opencue.portainer.yml` |
| Authentication | Disabled (Public repository) |
| Environment variables | Match existing web editor configuration |

API invocation:

```json
POST /api/stacks/create/standalone/repository?endpointId=3
{
  "name": "opencue-git",
  "repositoryURL": "https://github.com/chordee/OpenCue",
  "repositoryReferenceName": "refs/heads/studio/main",
  "composeFile": "notes/deploy/server/opencue.portainer.yml",
  "repositoryAuthentication": false,
  "env": [ ... ]
}
```

Completed in ~52 seconds. Portainer stores tracking metadata:
`"ConfigHash": "80c571c1a633e4f595a7ef50ccc13379a50a0d4f"`.

---

## 2. Update Mechanisms

### 1. Manual "Pull and redeploy"

UI: Stack view → **Pull and redeploy**. API: `PUT /api/stacks/{id}/git/redeploy`.

**Behavior**: Forces recreation of all containers even if repository contents have not changed, inducing ~63 seconds of service interruption. Reserve this action for forced rebuilds.

### 2. Automated Polling

UI: Stack view → **GitOps updates** → Mechanism: **Polling**, configure check interval (e.g., 5m).

**Behavior**: If no new commits exist on the tracked branch, no deployment actions occur.

### 3. Webhooks

UI: Stack view → GitOps updates → Mechanism: **Webhook**. Generates target endpoint:

```
POST https://<portainer>/api/stacks/webhooks/<uuid>
```

- Supported in Portainer Community Edition (CE).
- Unauthenticated (UUID acts as bearer secret).
- Returns HTTP 204 without redeploying if repository state has not diverged.

---

## 3. Deployment Behavior on Upstream Commits

### Verification: Documentation-Only Commits

Pushed commit `637f02ef` updating documentation without modifying YAML manifests (polling interval set to 1 minute):

```
05:51:54  Commit pushed to GitHub
05:53:00  Portainer detects new commit; ConfigHash updates to 637f02ef
          Deployment completes: "Stack deployment successful"
```

Container startup timestamps:

| Container | Startup Timestamp | Status |
|---|---|---|
| db | 05:40:49 | **Uninterrupted** |
| cuebot | 05:41:03 | **Uninterrupted** |
| rest-gateway | 05:41:14 | **Uninterrupted** |
| cueweb | 05:41:20 | **Uninterrupted** |
| flyway | 05:52:59 → Exit (0) | Executed one-shot migration check |
| init | 05:53:03 → Exit (0) | Executed one-shot idempotency check |

**Portainer updates mirror `docker compose up -d`**: Containers whose definitions are unchanged remain uninterrupted. One-shot containers (`flyway`, `init`) execute harmless idempotency sweeps without restarting core daemons.

**Takeaway: Documentation and deployment configurations can reside within the same repository.** Pushing documentation updates will not disrupt farm operations.

### Recreating Modified Containers vs. Manual Redeploy

| Trigger | Unchanged Repository | Changed Repo (Unmodified Service Configs) |
|---|---|---|
| Automated (Polling / Webhook) | No action | Re-runs one-shot containers only |
| Manual "Pull and redeploy" | **Recreates all containers** | Recreates all containers |

### Image Upgrades Remain Manual

Image tags reside in Portainer environment variables rather than Git manifests. Pushing Git commits will not trigger image version upgrades. Upgrades require updating environment variables in Portainer and redeploying.

Separation of concerns:
- **Stack Architecture (Ports, networks, limits)**: Git-tracked, automated.
- **Image Versions (Database migration risks)**: Managed manually via Portainer variables.
- **Secrets and Mount Paths**: Maintained securely in Portainer environment settings.

---

## 4. Production Branch Tracking: `studio/release`

### Challenge

Tracking `studio/main` causes every commit to trigger deployment evaluations. Pushing experimental documentation or unverified code updates may deploy inadvertently.

### Strategy

```
studio/main       Active development and engineering documentation
    │  Fast-forward merge after validation
    ▼
studio/release    Portainer tracks this release branch exclusively
```

Update stack reference to `refs/heads/studio/release` (`POST /api/stacks/{id}/git`). Branch switching does not restart running services.

### Verification Matrix

| Action | Stored ConfigHash | One-shot Tasks (`init`) | Core Daemon (`cuebot`) |
|---|---|---|---|
| Switch target to `studio/release` | `ed47b2d4` | No run | Uninterrupted |
| Push to `studio/main` (`004f267d`), wait 3m | **Unchanged** (`ed47b2d4`) | **No run** | Uninterrupted |
| Fast-forward `studio/release` to `004f267d` | Updates to `004f267d` | Executed | Uninterrupted |

Deployments execute only when `studio/release` advances. Recommended polling interval in production: 5 to 15 minutes.
