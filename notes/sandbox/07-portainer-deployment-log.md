# 07 — Portainer Deployment Log

Verification Objective: **Can OpenCue be deployed under the constraint of having Portainer access only, without SSH access?**

Conclusion: **Yes.** Furthermore, a private registry is unnecessary if the container images are already present on the target Docker daemon.

## Environment

- Portainer CE **2.39.1**, `https://localhost:9443`
- Endpoint: `Id=3`, Name `local`, `unix:///var/run/docker.sock`
- Target Docker Engine: Docker 29.6.2 / 16 CPUs / 19.2 GiB RAM

## Stack File Used

[`notes/deploy/server/opencue.portainer.yml`](../deploy/server/opencue.portainer.yml), with the following adaptations compared to upstream compose:

1. **Eliminated `build:` directives entirely**, relying exclusively on `image:`
2. **Excludes `rqd`** — the server host does not execute renders
3. **PostgreSQL port 5432 is not published**
4. All variable configuration parameters are driven by environment variables (see [`notes/deploy/server/env.example`](../deploy/server/env.example))
5. Explicitly named network (`opencue`) and volume (`opencue-db-data`)
6. Explicit memory resource limits applied

## Deployment Procedure (API Approach)

### 1. Acquire API Token

Portainer UI → Profile Avatar (top right) → My account → Access tokens → Add access token.
The token is displayed only once.

### 2. Verify Endpoint ID

```bash
curl -sk -H "X-API-Key: $TOKEN" https://localhost:9443/api/endpoints
```

The returned `Id` corresponds to the `endpointId` required in subsequent API calls.

### 3. Assemble JSON Payload

Portainer's API expects JSON with the following structure:

```json
{
  "name": "opencue",
  "stackFileContent": "<full yml content as string>",
  "env": [{"name": "POSTGRES_USER", "value": "cuebot"}, ...]
}
```

Note: `env` is an **array** of `{name, value}` pairs, rather than a standard key-value map.

### 4. Create Stack

```bash
curl -sk -X POST \
  -H "X-API-Key: $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @payload.json \
  "https://localhost:9443/api/stacks/create/standalone/string?endpointId=3"
```

A successful response returns a stack object with `Status: 1` indicating active status.

## Verification Results

```
NAMES            STATUS                      PORTS
opencue-cuebot   Up (healthy)                0.0.0.0:8443->8443/tcp
opencue-flyway   Exited (0)
opencue-db       Up (healthy)                5432/tcp
```

All three architectural design intents were satisfied:

| Design Intent | Verification |
|---|---|
| Cuebot public access | Port `8443` is published; `cueadmin -lh` and `cueadmin -ls` respond normally |
| DB isolated internally | PORTS column displays only `5432/tcp`, with **no `0.0.0.0:` host mapping** |
| flyway one-shot lifecycle | Container exhibits `Exited (0)`, with cuebot starting sequentially afterwards |
| Custom network / volume | `opencue` and `opencue-db-data` created exactly as defined |

**Zero private registry dependency was introduced.** Because Portainer and the local Docker CLI share the same underlying daemon, the stack directly utilized locally built images `opencue-cuebot:latest` and `opencue-flyway:latest`.

(Production environments should migrate to explicit image tags from an image registry, as production servers lack local build contexts.)

## Critical Verification: External Render Node

The stack deliberately excludes RQD. To validate the target architecture ("Cuebot inside Docker, render nodes external"), an independent RQD container **outside the stack** was launched:

```bash
docker run -d --name render01 --hostname render01 --network opencue \
  -e OPENRQD__GRPC__CUEBOT_ENDPOINTS=cuebot:8443 \
  -e OPENRQD__MACHINE__USE_IP_AS_HOSTNAME=false \
  -v /tmp/rqd/logs:/tmp/rqd/logs \
  -v /tmp/rqd/shots:/tmp/rqd/shots \
  --entrypoint /bin/sh \
  opencue-rqd:latest \
  -c 'id -u chordee >/dev/null 2>&1 || useradd --uid 2000 --gid 1000 -M chordee; exec /app/openrqd'
```

Outcome:

```
Host       Cores  Mem     State  Alloc          Thread
render01   8.0    18.5G   UP     local.general  AUTO
```

Submitted 2 jobs (6 frames total) → **All SUCCEEDED**.

**This validates that the target architecture is fully feasible**: A Cuebot stack deployed via Portainer (without rqd) paired with externally lifecycle-managed render nodes forms a complete, functional render farm.

## Items Not Yet Verified at Time of Writing

> **Note**: This section reflects findings at the time of initial testing. Several items have since been validated.
> **Refer to [`19-verification-summary.md`](19-verification-summary.md) for the definitive status matrix.**

| Item | Notes |
|---|---|
| True cross-machine network | In this test, render01 and cuebot shared a Docker bridge network with internal DNS. Production Windows nodes traverse physical LAN and production DNS/IP |
| RQD on Windows | The render node tested here was a Linux container. Windows-native RQD requires dedicated verification, with `run_as_user` known to be unsupported on Windows |
| Registry workflow | Tested directly using local daemon images. Production requires validating the full "build → push → Portainer pull" pipeline |
| Portainer UI workflow | Conducted entirely via API. If studio IT only provides UI access, the workflow for pasting compose manifests and environment variables requires validation |
| Stack update workflow | Validated stack creation only; `PUT /api/stacks/{id}` update and rollback operations remain untested |

## Postscript: NAS Is Unsuitable as a Staging Platform

We initially considered staging on a Synology NAS running Portainer (a true Linux + Docker host). However, the NAS processor is a **Realtek RTD1296 (ARM)** CPU, differing from the x86 Linux production architecture. Images built locally on x86 cannot run natively on ARM without setting up multi-architecture build pipelines. Considering the production target is x86, investment in ARM staging yielded low return on effort and was postponed.
