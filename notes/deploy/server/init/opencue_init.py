"""Post-deployment initialization: ensures shows, subscriptions, and services exist. Idempotent.

All configured via environment variables; unconfigured items are skipped:

  CUEBOT_HOSTS           cuebot:8443
  OPENCUE_INIT_SHOWS     Comma-separated show names, e.g. projA,projB
  OPENCUE_INIT_ALLOCS    Allocations subscribed to by new shows, default local.general,local.desktop,cloud.general
  OPENCUE_INIT_SUB_CORES Size and burst cores for each subscription, default 1000
  OPENCUE_INIT_SERVICES  JSON array, e.g.
                         [{"name":"houdini2204","tags":["houdini_22_0_429"],
                           "min_cores":1,"min_memory_gb":4}]

Pre-existing shows, subscriptions, and services are not modified to avoid overwriting UI adjustments.
"""

import json
import os
import sys
import time

import opencue
from opencue.exception import EntityNotFoundException
from opencue_proto import service_pb2

GB = 1024 * 1024  # OpenCue memory unit is KB


def wait_for_cuebot(timeout=300):
    deadline = time.time() + timeout
    while True:
        try:
            opencue.api.getShows()
            return
        except Exception as e:  # Cuebot rejects connections during initial boot
            if time.time() > deadline:
                raise
            print("Waiting for Cuebot: %s" % e)
            time.sleep(5)


def ensure_show(name, allocs, cores):
    try:
        show = opencue.api.findShow(name)
        print("Show %s already exists" % name)
    except EntityNotFoundException:
        show = opencue.api.createShow(name)
        print("Created show %s" % name)

    existing = {s.allocation() for s in show.getSubscriptions()}
    for alloc_name in allocs:
        if alloc_name in existing:
            print("  Subscription %s.%s already exists" % (alloc_name, name))
            continue
        show.createSubscription(opencue.api.findAllocation(alloc_name), cores, cores)
        print("  Created subscription %s.%s (%d cores)" % (alloc_name, name, cores))


def ensure_service(spec):
    name = spec["name"]
    if opencue.api.getService(name) is not None:  # Returns None if not found, does not raise exception
        print("Service %s already exists" % name)
        return
    opencue.api.createService(service_pb2.Service(
        name=name,
        threadable=spec.get("threadable", False),
        min_cores=int(spec.get("min_cores", 1) * 100),
        max_cores=int(spec.get("max_cores", 0) * 100),
        min_memory=int(spec.get("min_memory_gb", 4) * GB),
        min_gpu_memory=0,
        tags=spec["tags"],
        timeout=0,
        timeout_llu=0,
        min_memory_increase=int(spec.get("min_memory_increase_gb", 2) * GB),
    ))
    print("Created service %s, tags=%s" % (name, spec["tags"]))


def split(value):
    return [v.strip() for v in value.split(",") if v.strip()]


def main():
    shows = split(os.getenv("OPENCUE_INIT_SHOWS", ""))
    allocs = split(os.getenv("OPENCUE_INIT_ALLOCS", "local.general,local.desktop,cloud.general"))
    cores = int(os.getenv("OPENCUE_INIT_SUB_CORES", "1000"))
    services = json.loads(os.getenv("OPENCUE_INIT_SERVICES", "") or "[]")

    if not shows and not services:
        print("Neither OPENCUE_INIT_SHOWS nor OPENCUE_INIT_SERVICES set; no initialization needed")
        return 0

    wait_for_cuebot()
    for name in shows:
        ensure_show(name, allocs, cores)
    for spec in services:
        ensure_service(spec)
    print("Initialization completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
