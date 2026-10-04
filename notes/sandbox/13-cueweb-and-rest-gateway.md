# 13 — CueWeb and REST Gateway Integration

## Finding: Container Images Are Not Published and Must Be Built Locally

Attempting to pull upstream prebuilt images revealed they are not available on Docker Hub:

```
opencue/cuebot        -> HTTP 200
opencue/rqd           -> HTTP 200
opencue/cueweb        -> HTTP 404
opencue/rest-gateway  -> HTTP 404
```

Pull attempts trigger misleading authentication errors (`pull access denied for opencue/cueweb, repository does not exist or may require 'docker login'`).

Building container images internally and deploying a private registry is mandatory.

### Additional Benefits of Internal Image Builds

| Advantage | Details |
|---|---|
| Version Consistency | Public `opencue/cuebot` tags lag at `1.19.1`; master builds `1.34.4` |
| Mandatory for Auth | `NEXT_PUBLIC_AUTH_PROVIDER` (github/okta/google/ldap) is a **build-time argument**; cannot be configured via runtime environment variables |
| Customization | External preview tools, log viewer commands, and progress bars are configured via build args |
| Supply Chain Control | Enterprise security standards and base image patching |

Image sizes:
- `opencue/cueweb:latest`: 2.52 GB
- `opencue/rest-gateway:latest`: 184 MB

Next.js compilation consumes multiple gigabytes of memory during build; ensure build machines have adequate RAM headroom.

## Stack Architecture

Configuration added to [`notes/deploy/server/opencue.portainer.yml`](../deploy/server/opencue.portainer.yml):

### REST Gateway Is Not Published Publicly

```yaml
rest-gateway:
  image: ${OPENCUE_REST_GATEWAY_IMAGE}
  environment:
    CUEBOT_ENDPOINT: cuebot:8443
    JWT_SECRET: ${JWT_SECRET}
  # No ports: exposed
```

Only CueWeb requires direct access. Active container state:

```
NAMES                  STATUS          PORTS
opencue-cueweb         Up (healthy)    0.0.0.0:3000->3000/tcp
opencue-rest-gateway   Up (healthy)    8448/tcp          <- Internal only
opencue-cuebot         Up (healthy)    0.0.0.0:8443->8443/tcp
opencue-db             Up (healthy)    5432/tcp          <- Internal only
```

### Server-Side Proxying for `NEXT_PUBLIC_*` Variables

Upstream architecture handles Next.js endpoints cleanly:

```yaml
NEXT_PUBLIC_OPENCUE_ENDPOINT: http://rest-gateway:8448
NEXT_PUBLIC_URL: ""          # Empty string = Browser requests use same-origin relative URLs
```

- **Browser** queries CueWeb relative paths (`/api/...`).
- **Next.js Server** proxies requests internally to `http://rest-gateway:8448`.

Browsers do not need to resolve internal container names, avoiding rebuilds when deployments change network topology. Keep `NEXT_PUBLIC_URL` empty.

## REST Gateway JWT Verification

Tested from within the container network:

```bash
docker run --rm --network opencue curlimages/curl -s \
  -X POST http://rest-gateway:8448/show.ShowInterface/GetShows \
  -H "Authorization: Bearer $TOKEN" -d '{}'
```

| Scenario | Response |
|---|---|
| Missing token | **HTTP 401** |
| Valid JWT token | JSON payload containing Show details |

Security notice: Generate `JWT_SECRET` with at least 32 cryptographically random bytes.

## CueWeb Functional Verification

```
Root URL               HTTP 200
/api/job/getjobs       Returns complete active job listing
```

Retrieved active DCC jobs (Houdini, Maya, Nuke) with correct metadata.

## Cross-Platform Frame Log Handling

### Problem

Job metadata returned from `/api/job/getjobs`:

```json
"logDir": "C:/opencue/logs/testing/testshot/logs/..."
```

Cuebot stores the path as written by the Windows worker node, but CueWeb runs inside Linux.

Requesting logs via CueWeb:

```
GET /api/getlog?path=C:/opencue/logs/...
-> HTTP 400 {"error":"Query parameter 'path' is required"}
```

In `cueweb/app/api/getlog/route.ts:66`:

```javascript
if (!filePath || filePath.includes("\0") || !path.isAbsolute(filePath)) {
  return NextResponse.json({ error: "..." }, { status: 400 });
}
```

On Linux, `C:/opencue/logs/...` fails `path.isAbsolute()`. CueWeb has no built-in path mapping functionality.

### Solution: Configure Forward-Slash UNC Paths

POSIX systems treat paths starting with `//` as valid absolute paths.

Empirical verification:

```
GET /api/getlog?path=/mnt/logs/.../xxx.rqlog    -> HTTP 200
GET /api/getlog?path=//mnt/logs/.../xxx.rqlog   -> HTTP 200
```

Setting `CUE_FRAME_LOG_DIR=//fileserver/opencue/logs` satisfies both systems:
- Windows RQD resolves `\\fileserver\opencue\logs` natively.
- Linux CueWeb mounts the share at `/fileserver/opencue/logs`, which matches `//fileserver/...`.

## Route Allow-List Configurations

| Environment Variable | Route Location | Default Behavior | Purpose |
|---|---|---|---|
| `CUEWEB_LOG_ROOTS` | `api/getlog/route.ts` | **Permissive** (Unrestricted) | Whitelist for `.rqlog` frame log downloads |
| `CUEWEB_PREVIEW_ROOTS` | `api/frame/preview/route.ts` | **Fail-closed** (Rejects all, 403) | Whitelist for rendered image previews |

Omitting `CUEWEB_LOG_ROOTS` allows arbitrary container filesystem reads via `/api/getlog`. **Always configure `CUEWEB_LOG_ROOTS` in production.**

Configured mounts:

```yaml
environment:
  CUEWEB_LOG_ROOTS: ${CUEWEB_LOG_ROOTS}          # -> /mnt/logs
  CUEWEB_PREVIEW_ROOTS: ${CUEWEB_PREVIEW_ROOTS}  # -> /mnt/render
volumes:
  - ${FRAME_LOG_MOUNT_SOURCE}:${FRAME_LOG_MOUNT_TARGET}:ro
  - ${RENDER_OUT_MOUNT_SOURCE}:${RENDER_OUT_MOUNT_TARGET}:ro
```

Tested previewing Nuke PNG output:

```
/api/frame/preview?path=/mnt/render/nuke/nuke.0001.png
-> HTTP 200 content-type: image/png (74,615 bytes)
```

Web browsers do not decode EXR files natively; EXR formats return HTTP 415.

## EXR Preview Approaches

Browsers lack native EXR decoders. CueWeb handles unsupported formats by displaying placeholder icons.

### Approach 1: External Desktop Viewers (Recommended)

CueWeb includes built-in support for launching external viewers in `cueweb/components/ui/frame-extra-dialogs.tsx`:
- `NEXT_PUBLIC_PREVIEW_COMMAND`: Command string for copy-pasting (e.g., `rv {paths}`).
- `NEXT_PUBLIC_PREVIEW_URL`: Custom URI scheme launcher (e.g., `openrv://{paths}`).

Configured at build time:

```bash
docker compose build cueweb \
  --build-arg NEXT_PUBLIC_PREVIEW_COMMAND='rv {paths}' \
  --build-arg NEXT_PUBLIC_PREVIEW_URL='openrv://{paths}'
```

### Approach 2: Server-Side Thumbnail Generation

Install `ffmpeg` in `cueweb/Dockerfile` and transcode linear EXR frames into sRGB PNG thumbnails on-the-fly (`ffmpeg -apply_trc iec61966_2_1 -i in.exr -vf scale=320:-1 out.png`).

### Approach 3: Client-Side WebAssembly Decoding

Stream raw EXR bytes to browsers using three.js `EXRLoader` onto HTML5 `<canvas>`. Retains multi-channel AOVs and exposure controls at the expense of high network transfer overhead.

**Recommendation**: Deploy Approach 1 first.

## CueWeb Job Submission (`app/cuesubmit/page.tsx`)

CueWeb provides a browser-based submission interface. However, hybrid farms face three limitations:

1. **Lacks Layer Tag Inputs**: Submissions default layer tags to `general | desktop`. Because tags evaluate with regex OR, jobs cannot be locked to specific DCC versions and may dispatch to incapable nodes.
2. **Lacks Target OS Specification**: Prevents automatic per-OS frame log routing.
3. **Default Memory (256 MB) Is Insufficient**: Memory defaults to 256 MB. While Cuebot defaults `dispatcher.oom_frame_overboard_allowed_threshold = -1.0` (preventing frame kills), underestimating memory causes Cuebot to over-subscribe nodes and risk OS-level OOM crashes. Always input realistic limits (e.g., 2g for Houdini).

**Production Guideline**: Studio submissions should rely on Python submission scripts ([`notes/sandbox/lab/submit_dcc.py`](lab/submit_dcc.py)) or native DCC plugins rather than the basic CueWeb submission form.
