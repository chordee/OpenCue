# opencue-init: Post-deployment initialization container (bootstraps show, subscription, service).
# Build context must be repo root to install proto and pycue from source.
FROM python:3.12-slim

ARG OPENCUE_VERSION=0.0.0

WORKDIR /build
COPY VERSION.in ./
COPY proto ./proto
COPY pycue ./pycue
# The repo's .dockerignore excludes ci/, but proto/pycue packaging configuration
# requires reading the version number from ../ci/generate_version_number.py.
# Create a dummy shim that outputs the desired version.
RUN mkdir ci && echo "__version__ = '${OPENCUE_VERSION}'" > ci/generate_version_number.py \
 && pip install --no-cache-dir ./proto ./pycue \
 && rm -rf /build

WORKDIR /app
COPY notes/deploy/server/init/opencue_init.py ./
CMD ["python", "-u", "opencue_init.py"]
