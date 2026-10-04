# 16 — Division of Responsibilities: Portainer vs. SSH

**Portainer handles deployment operations; ongoing maintenance predominantly requires host-level access.**
This matrix defines operational boundaries to facilitate access discussions with studio IT.

Status notation:
- Verified empirically
- Unverified, standard Docker feature
- Mitigated via containerized workarounds

## Capabilities Supported via Portainer

| Operation | Status |
|---|---|
| Create stack from compose content | Supported (`POST /api/stacks/create/standalone/string`) |
| Update stack and environment variables | Supported (`PUT /api/stacks/{id}`) |
| Pull images from registry and recreate containers | Supported (`pullImage: true`) |
| Inspect container health and port bindings | Supported |
| Perform upgrades and rollbacks | Supported via environment variable updates |
| Inspect container stdout/stderr logs | Standard Portainer feature |
| Execute in-container commands (`exec`) | Standard Portainer feature |
| Restart / stop individual containers | Standard Portainer feature |
| Provision volumes and bridge networks | Standard Portainer feature |

Portainer provides complete coverage for stack deployment and release management.

## Operations Requiring Host Privileges (SSH)

### 1. Image Building (The Primary Justification for Private Registries)

Portainer lacks local build contexts; `build:` directives cannot be executed.
Because CueWeb and REST Gateway **do not provide public prebuilt images**, local builds are unavoidable, necessitating the entire registry pipeline (build server, registry with TLS, 6 GB/version storage, garbage collection).

With SSH access, this complexity can be bypassed by building directly on the host (`git pull && docker compose up -d --build`).

### 2. Scheduled Maintenance Jobs

| Maintenance Task | Reference | Supported via Portainer Alone |
|---|---|---|
| PostgreSQL historical table purging | [`11` Section 6](11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups) | No (Mitigable) |
| `pg_dump` logical backups | [`11` Section 6](11-production-risks-and-todos.md#6-postgresql-data-retention-and-backups) | No (Mitigable) |
| Registry garbage collection | [`14-registry-workflow.md`](14-registry-workflow.md) | No (Mitigable) |
| Frame log retention purging | [`15-storage-planning.md`](15-storage-planning.md) | No (Mitigable) |
| Docker build cache pruning | [`15-storage-planning.md`](15-storage-planning.md) | No |
| Host disk monitoring and alerts | [`15-storage-planning.md`](15-storage-planning.md) | No |

Without automated purging, database history grows unbounded and backups do not occur.

### 3. Docker Daemon Configuration

Modifications to `/etc/docker/daemon.json` require host privileges and daemon restarts:
- `insecure-registries`: Required if the private registry lacks valid TLS certificates.
- Default log rotation drivers: Prevents uncontrolled container log growth.
- `data-root`: Migrates Docker storage to dedicated partitions.

Notice the circular constraint: Running an insecure registry requires modifying `daemon.json`, which requires SSH. Operating strictly through Portainer requires **valid TLS certificates on the registry**.

### 4. Operating System Infrastructure

- Systemd daemon auto-start upon host reboot.
- Firewall configurations (Opening port 8443 to worker subnets).
- Storage mounts (Mounting SMB shares for CueWeb).
- TLS certificate distribution.

## Workaround: Containerizing Maintenance Tasks

Tasks flagged as mitigable can be encapsulated inside a dedicated maintenance container deployed via Portainer:

```yaml
  maintenance:
    image: ${OPENCUE_MAINTENANCE_IMAGE}
    container_name: opencue-maintenance
    depends_on:
      db:
        condition: service_healthy
    environment:
      PGHOST: db
      PGUSER: ${POSTGRES_USER}
      PGPASSWORD: ${POSTGRES_PASSWORD}
      PGDATABASE: ${POSTGRES_DB}
      HISTORY_RETENTION_DAYS: "90"
      LOG_RETENTION_DAYS: "30"
    volumes:
      - ${FRAME_LOG_MOUNT_SOURCE}:${FRAME_LOG_MOUNT_TARGET}
      - backup-data:/backup
    networks:
      - opencue
    restart: unless-stopped
```

Running an internal cron utility (e.g., `supercronic`), this container manages:
- Database historical table purging (with `int_ts_stopped > 0` guards).
- Executing `pg_dump` into mounted backup volumes.
- Deleting expired frame logs.

### Mounting Shared Storage via CIFS Docker Volumes

If studio IT restricts host-level SMB mounting, Docker supports native CIFS volumes:

```yaml
volumes:
  frame-logs:
    driver: local
    driver_opts:
      type: cifs
      device: "//fileserver/opencue/logs"
      o: "username=...,password=...,ro"
```

**Constraints**:
1. **The Host Kernel Must Support CIFS**: Docker relies on the host's `cifs.ko` kernel module and `mount.cifs` (`cifs-utils`). Minimal OS distributions missing these packages will fail volume creation.
2. **Credential Management**: SMB credentials must be managed via Portainer environment variables or Docker secrets.

Testing CIFS support on target hosts:

```bash
docker volume create --driver local --opt type=cifs --opt device=//fileserver/share --opt o=guest,ro cifstest
docker run --rm -v cifstest:/mnt alpine ls /mnt
docker volume rm cifstest
```
- `permission denied`: Kernel supports CIFS; credentials merely failed.
- `cifs filesystem not supported`: Missing kernel modules; requires host package installation via SSH.

## Operations Unavoidably Requiring Host Privileges

- Image building (unless maintaining an external build server and registry).
- Modifying `/etc/docker/daemon.json`.
- Configuring host firewall rules and systemd persistence.
- Exporting backups off-host to cold storage.
- Low-level daemon troubleshooting.

## Access Negotiation Strategies with IT

Rather than requesting unconditional SSH root access, frame requests around operational requirements:

1. **Deployments and updates proceed entirely through Portainer**, maintaining IT governance and audit trails.
2. **Scheduled maintenance requires host execution** (database maintenance, backups, log retention).
3. **If IT restricts host privileges**, request IT-managed cron jobs, or formally document the operational trade-offs (unbounded database expansion, absence of automated recovery backups).

| Scenario | Viability | Operational Overhead |
|---|---|---|
| Full SSH Access | Simplest | Registry optional; build and maintain on-host |
| Portainer + Limited SSH (cron) | Recommended | Registry required; fully supported maintenance |
| Portainer Only | Deployable with caveats | Mandatory registry TLS; maintenance must be containerized; off-host backup sync requires separate IT solution |
