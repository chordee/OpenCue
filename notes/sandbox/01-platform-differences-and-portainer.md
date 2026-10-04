# 01 — Platform Differences & Portainer Considerations

This document analyzes aspects of the upstream `docker-compose.yml` (located at repo root) that are **suitable only for sandbox prototyping and cause failure on production Linux hosts or Portainer**. While preserved verbatim during initial sandbox testing, each item must be adapted for production.

## 1. `build:` vs. `image:`

Upstream status: `cuebot`, `flyway`, and `rqd` services compile from source via `build:`:

```yaml
cuebot:
  build:
    context: ./
    dockerfile: ./cuebot/Dockerfile
  # image: opencue/cuebot   <- Upstream commented option
```

**Why this is problematic**: When deploying stacks via Portainer, `build:` requires a complete build context (the entire source repo) on the host filesystem, whereas Portainer stacks are typically fed a standalone compose YAML. Even when deploying via Git repository mode, in-situ builds severely slow deployments down and clutter production hosts with transient build artifacts.

**Production Solution**: Pre-build images via CI/CD and publish to a container registry (e.g. GHCR `ghcr.io/chordee/opencue/*` or internal registries). The compose definition should strictly reference `image:` with deterministic, pinned version tags (never `latest`).

## 2. `${HOME}` Environment Variable

Upstream status:

```yaml
rqd:
  volumes:
    - ${HOME}/.opencue/sessions:${HOME}/.opencue/sessions
```

**Why this is problematic**: `${HOME}` evaluates against the interactive shell executing `docker compose`. When Portainer deploys stacks as a system daemon, `HOME` is often unset, expanding into an empty string resulting in corrupted mounts: `/.opencue/sessions:/.opencue/sessions`.

**Production Solution**: Define storage paths explicitly in the stack `.env` file, such as `OPENCUE_SESSION_DIR=/opt/opencue/sessions`, referenced symmetrically across compose definitions. Portainer stack editors support explicit environment variable configuration out of the box.

## 3. macOS-specific `/var/folders`

Upstream status:

```yaml
rqd:
  volumes:
    - /var/folders:/var/folders:ro
```

`/var/folders` is a macOS-specific temporary path (`$TMPDIR` targets this location). On Linux Docker hosts, this directory does not exist; Docker automatically provisions an empty, root-owned host folder and mounts it. While non-fatal, it pollutes the host root filesystem needlessly.

**Production Solution**: Remove this mount entirely.

## 4. Bind Mounts Under `/tmp`

Upstream status: `/tmp/rqd/logs`, `/tmp/rqd/shots`, and `/tmp/opencue`.

**Why this is problematic**: `/tmp` is wiped on host reboot (or mounted on tmpfs) on modern Linux distributions. Frame execution logs are the primary evidence for post-mortem render troubleshooting; hosting them under `/tmp` guarantees total loss of log retention.

**Production Solution**: Map to persistent paths (e.g. `/opt/opencue/logs`) or named volumes. In multi-node farms, this **must map to shared network storage (NFS/SMB) accessible at identical paths across all nodes**, otherwise log paths stored in Cuebot cannot be resolved by peer hosts.

## 5. Passwords Hardcoded in Compose

Upstream status: `POSTGRES_PASSWORD=cuebot_password`, duplicated again verbatim inside cuebot's `command:` parameter.

**Production Solution**: Abstract credentials into `.env` or Docker secrets. Note that credentials appear in multiple service definitions; desynchronization will cause connection rejections.

## 6. Indiscriminate Port Publishing

Upstream status: Ports 5432 (PostgreSQL), 8443 (Cuebot gRPC), and 8444 (RQD) are all published globally to the host interface.

Acceptable in local sandboxes, but exposing PostgreSQL publicly in production represents an acute security risk.
**Production Solution**: Publish only ports requiring external ingress (Cuebot gRPC, CueWeb); isolate internal databases to the internal Docker network. Portainer should ideally sit behind an authenticated reverse proxy.

## 7. Session Path Alignment (Determining Client Host Location)

This represents the primary rationale for **validating the sandbox inside WSL2 Ubuntu rather than native Windows paths**.

When `pyoutline` queues a job, it writes `outline.yaml` into the session directory and embeds that **exact path string** into the frame's execution command line. When RQD receives the task, it must read that file using that **identical path string**.

- If the client runs on native Windows: the path string is `C:\Users\chordee\.opencue\sessions\...`, which Linux container RQD daemons cannot parse -> the frame fails immediately.
- If the client runs inside WSL Ubuntu: the path string is `/home/chordee/.opencue/sessions/...`, bind-mounted symmetrically into the container -> path strings match seamlessly.

**Implication for Production Farms**: Submitting artist workstations and worker render nodes must resolve shared storage assets using identical path conventions. While sandboxes simulate this via Docker bind mounts, production multi-machine farms must solve this via unified NFS/SMB mount paths.

## 8. CueWeb Build-time Variables

As documented in upstream compose headers: CueWeb is a Next.js application, where `NEXT_PUBLIC_*` variables are **baked into client-side JS bundles at image build time**. If an image is baked with `http://localhost:8448`, client browsers on other machines will throw `ECONNREFUSED`.

**Production Solution**: Supply the correct external endpoint URL as a Docker build argument during image generation; runtime environment variables cannot mutate baked Next.js client variables. This is a common pitfall in Portainer, where administrators often expect environment variables to take effect dynamically at runtime.
