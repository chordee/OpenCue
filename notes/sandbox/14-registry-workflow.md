# 14 — Image Registry Pipeline

[Note `13-cueweb-and-rest-gateway.md`](13-cueweb-and-rest-gateway.md) confirmed that building images internally is a requirement. This document validates the complete pipeline:
**build → push → Portainer pull**.

## Why an Image Registry Is Mandatory

| Factor | Description |
|---|---|
| Unpublished Images | `opencue/cueweb` and `opencue/rest-gateway` return HTTP 404 on Docker Hub |
| Outdated Official Images | `opencue/cuebot` tags stop at `1.19.1`; master builds `1.34.4` |
| No Portainer Build Context | Portainer deployments support `image:` only; `build:` directives are unsupported |
| Build-Time Auth Injection | `NEXT_PUBLIC_AUTH_PROVIDER` in CueWeb is a build argument and cannot be set at runtime |

## Deploying a Local Registry

Template available at [`notes/deploy/server/registry.portainer.yml`](../deploy/server/registry.portainer.yml). Minimal deployment command:

```bash
docker run -d --name opencue-registry --restart unless-stopped \
  -p 5000:5000 -v opencue-registry-data:/var/lib/registry registry:2
```

Verification:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/v2/
# 200
```

**Keep the registry as independent infrastructure separate from the OpenCue stack**: its lifecycle is decoupled from OpenCue, and stack updates depend on registry availability.

## Tagging Conventions

**Do not use `latest`.** We adopted:

```
<version>-<commit-short-sha>
1.34.4-fe0b32bf
```

Derived from `VERSION.in` (`1.34`) plus build metadata and `git rev-parse --short HEAD`. Every production container can be traced to exact source revisions.

## Pushing Images

```bash
VER=1.34.4-$(git rev-parse --short HEAD)
REG=localhost:5000/opencue

docker tag opencue-cuebot:latest        $REG/cuebot:$VER
docker tag opencue-flyway:latest        $REG/flyway:$VER
docker tag opencue/rest-gateway:latest  $REG/rest-gateway:$VER
docker tag opencue/cueweb:latest        $REG/cueweb:$VER

for n in cuebot flyway rest-gateway cueweb; do
    docker push $REG/$n:$VER
done
```

Note: Compose automatically names `opencue-cuebot` and `opencue-flyway`, whereas explicit compose `image:` directives label `opencue/rest-gateway` and `opencue/cueweb`.

Verify registry contents:

```bash
curl -s http://localhost:5000/v2/_catalog
{"repositories":["opencue/cuebot","opencue/cueweb","opencue/flyway","opencue/rest-gateway"]}

curl -s http://localhost:5000/v2/opencue/cuebot/tags/list
{"name":"opencue/cuebot","tags":["1.34.4-fe0b32bf"]}
```

## Deploying from Registry via Portainer

Configure stack environment variables to target registry tags:

```
OPENCUE_CUEBOT_IMAGE=localhost:5000/opencue/cuebot:1.34.4-fe0b32bf
OPENCUE_FLYWAY_IMAGE=localhost:5000/opencue/flyway:1.34.4-fe0b32bf
OPENCUE_REST_GATEWAY_IMAGE=localhost:5000/opencue/rest-gateway:1.34.4-fe0b32bf
OPENCUE_CUEWEB_IMAGE=localhost:5000/opencue/cueweb:1.34.4-fe0b32bf
```

Trigger stack updates with `pullImage: true`:

```bash
curl -sk -X PUT -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  --data-binary @payload.json \
  "https://localhost:9443/api/stacks/3?endpointId=3"
```

### Verification: Purging Local Tags Prior to Pull

To verify that images are genuinely pulled rather than reusing local images, delete local tags first:

```bash
for n in cuebot flyway rest-gateway cueweb; do
    docker rmi localhost:5000/opencue/$n:1.34.4-fe0b32bf
done
docker images | grep localhost:5000     # Should be empty
```

Trigger update via Portainer API:

```
NAMES                  IMAGE                                                 STATUS
opencue-cueweb         localhost:5000/opencue/cueweb:1.34.4-fe0b32bf         Up (healthy)
opencue-rest-gateway   localhost:5000/opencue/rest-gateway:1.34.4-fe0b32bf   Up (healthy)
opencue-cuebot         localhost:5000/opencue/cuebot:1.34.4-fe0b32bf         Up (healthy)
opencue-flyway         localhost:5000/opencue/flyway:1.34.4-fe0b32bf         Exited (0)
opencue-db             postgres:15.1                                         Up (healthy)
```

Local registry tags reappeared, confirming successful pull operations. Farm operations remained uninterrupted:

```
Host             ... State  Locked  Alloc
LAPTOP-ULJICLO8  ... UP     LOCKED  local.desktop     <- Windows RQD reregistered cleanly

docker exec opencue-cuebot ls /opt/opencue/*.jar
/opt/opencue/cuebot-1.34-custom-all.jar

POST /api/job/getjobs  ->  HTTP 200
```

## Production Requirements

### Remote Registries Require TLS

Docker requires HTTPS for non-localhost endpoints. Deploying across separate servers requires:
- Configuring valid TLS certificates on the registry (Recommended).
- Adding `insecure-registries` in `/etc/docker/daemon.json` on all Docker hosts (Requires host root privileges).

### Authentication

Minimal registries lack authentication. Production deployments require basic auth (`htpasswd`) or token authentication, configured under Portainer Registry settings.

### Storage Capacity Planning

Image tags accumulate. While `registry.portainer.yml` enables `REGISTRY_STORAGE_DELETE_ENABLED`, **disk space is only recovered after executing garbage-collect**:

```bash
docker exec opencue-registry \
  bin/registry garbage-collect /etc/docker/registry/config.yml
```

Image footprint per version:
- cueweb: 2.52 GB
- flyway: 2.15 GB
- cuebot: 1.06 GB
- rest-gateway: 184 MB
Total ≈ 6 GB per build. Retaining 10 versions consumes ~60 GB.

### Backups

Back up `opencue-registry-data` volume or maintain reproducible CI pipelines.

## Complete Production Pipeline

```
Build Server                    Registry                  Linux Host
  git clone <repo>
  git checkout <tag>
  docker compose build
    cuebot / flyway
    rest-gateway / cueweb
  docker tag  ...:<ver>-<sha>
  docker push  ──────────────>  registry.studio.local
                                  /opencue/cuebot:<ver>-<sha>
                                  /opencue/flyway:<ver>-<sha>
                                  /opencue/rest-gateway:<ver>-<sha>
                                  /opencue/cueweb:<ver>-<sha>
                                        │
                                        │ pull
                                        ▼
                                                        Portainer Stack
                                                          Update image tag
                                                          environment variables
                                                          to trigger release
```

## Upgrade and Rollback Verification

Validated by building two identifiable images without recompiling Java:

```dockerfile
FROM localhost:5000/opencue/cuebot:1.34.4-fe0b32bf
RUN echo "ROLLBACK_TEST_V2" > /opt/opencue/VERSION_MARKER
LABEL opencue.rollback.test="v2"
```

Updating stack variable `OPENCUE_CUEBOT_IMAGE` to `...:1.34.4-v2test` deployed the marker file.
Reverting the variable to `...:1.34.4-fe0b32bf` cleanly rolled back and removed the marker.
Total API update latency: **53 seconds** (including pull and container recreation).

## In-Flight Frame Survival During Cuebot Upgrades

A 150-second frame was submitted. While in `RUNNING` status on `render02`, the Cuebot stack was upgraded.
- Frame process (`sleep 150`) ran continuously without termination.
- Upon Cuebot restoration, RQD reported completion and the frame transitioned to `SUCCEEDED`.

**Cuebot is stateless with respect to executing frames**: RQD manages subprocesses independently. Upgrades do not require draining active render jobs. Note that no new frames dispatch during the brief restart window (~1 minute).

## Registry Deletion Mechanics

### Prerequisite 1: `REGISTRY_STORAGE_DELETE_ENABLED` Must Be Set at Launch

Manifest deletion fails unless the registry starts with `REGISTRY_STORAGE_DELETE_ENABLED=true`.

### Prerequisite 2: Modern Buildx Uses OCI Manifests

Standard Docker v2 headers return HTTP 404 when querying modern digests. Always provide comprehensive `Accept` headers:

```bash
# 1. Fetch Digest
DIGEST=$(curl -s -I \
  -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
  http://registry/v2/<repo>/manifests/<tag> \
  | grep -i docker-content-digest | tr -d '\r' | cut -d' ' -f2)

# 2. Delete Manifest
curl -X DELETE http://registry/v2/<repo>/manifests/$DIGEST

# 3. Garbage Collection
docker exec <registry_container> \
  bin/registry garbage-collect /etc/docker/registry/config.yml
```
