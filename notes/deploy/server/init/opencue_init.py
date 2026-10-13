"""部署後初始化：確保 show、subscription、service 存在。可重複執行。

全部由環境變數設定，未設定的項目直接略過：

  CUEBOT_HOSTS           cuebot:8443
  OPENCUE_INIT_SHOWS     逗號分隔的 show 名稱，例如 projA,projB
  OPENCUE_INIT_ALLOCS    新 show 要訂閱的 allocation，預設 local.general,local.desktop,cloud.general
  OPENCUE_INIT_SUB_CORES 每個 subscription 的 size 與 burst（核心數），預設 1000
  OPENCUE_INIT_SERVICES  JSON 陣列，例如
                         [{"name":"houdini2204","tags":["houdini_22_0_429"],
                           "min_cores":1,"min_memory_gb":4}]

已存在的 show / subscription / service 不會被修改，避免蓋掉在介面上做的調整。
"""

import json
import os
import sys
import time

import opencue
from opencue.exception import EntityNotFoundException
from opencue_proto import service_pb2

GB = 1024 * 1024  # OpenCue 的記憶體單位是 KB


def wait_for_cuebot(timeout=300):
    deadline = time.time() + timeout
    while True:
        try:
            opencue.api.getShows()
            return
        except Exception as e:  # Cuebot 剛起來時 gRPC 會拒絕連線
            if time.time() > deadline:
                raise
            print("等待 Cuebot：%s" % e)
            time.sleep(5)


def ensure_show(name, allocs, cores):
    try:
        show = opencue.api.findShow(name)
        print("show %s 已存在" % name)
    except EntityNotFoundException:
        show = opencue.api.createShow(name)
        print("建立 show %s" % name)

    existing = {s.allocation() for s in show.getSubscriptions()}
    for alloc_name in allocs:
        if alloc_name in existing:
            print("  subscription %s.%s 已存在" % (alloc_name, name))
            continue
        show.createSubscription(opencue.api.findAllocation(alloc_name), cores, cores)
        print("  建立 subscription %s.%s（%d 核）" % (alloc_name, name, cores))


def ensure_service(spec):
    name = spec["name"]
    if opencue.api.getService(name) is not None:  # 找不到時回傳 None，不會丟例外
        print("service %s 已存在" % name)
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
    print("建立 service %s，tags=%s" % (name, spec["tags"]))


def split(value):
    return [v.strip() for v in value.split(",") if v.strip()]


def main():
    shows = split(os.getenv("OPENCUE_INIT_SHOWS", ""))
    allocs = split(os.getenv("OPENCUE_INIT_ALLOCS", "local.general,local.desktop,cloud.general"))
    cores = int(os.getenv("OPENCUE_INIT_SUB_CORES", "1000"))
    services = json.loads(os.getenv("OPENCUE_INIT_SERVICES", "") or "[]")

    if not shows and not services:
        print("沒有設定 OPENCUE_INIT_SHOWS 或 OPENCUE_INIT_SERVICES，不需要初始化")
        return 0

    wait_for_cuebot()
    for name in shows:
        ensure_show(name, allocs, cores)
    for spec in services:
        ensure_service(spec)
    print("初始化完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
