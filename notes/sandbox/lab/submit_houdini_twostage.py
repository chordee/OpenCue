#!/usr/bin/env python
"""Houdini 兩階段派工：hython 產 USD -> husk 算圖。

這是 Houdini 大場景的實務做法，也是 chain 相依在真實 pipeline 上的應用：

    階段 1  hython  建立場景並匯出 USD      （1 個 frame）
       |    depend_all（LayerOnLayer）
       v
    階段 2  husk    直接算那個 USD          （N 個 frame，可平行）

husk 不需要開啟完整的 Houdini session，啟動比 hython 快。

用法：
    python submit_houdini_twostage.py --frames 1-3
"""
import argparse
import sys
import time

import outline
import outline.cuerun
from outline.modules.shell import Shell

VERSION = "22.0.429"
VERSION_TAG = "houdini_22_0_429"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", default="testing")
    ap.add_argument("--shot", default="testshot")
    ap.add_argument("--frames", default="1-3")
    ap.add_argument("--usd", default="C:/opencue/render/twostage.usda")
    ap.add_argument("--out", default="C:/opencue/render/twostage.$F4.exr")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    f1, _, f2 = args.frames.partition("-")
    f2 = f2 or f1

    name = "houdini_twostage_%d" % int(time.time())
    ol = outline.Outline(name, shot=args.shot, show=args.show)

    # 階段 1：匯出 USD。只有一個 frame。
    stage1 = Shell(
        "export_usd",
        command=["ocrun", "houdini", VERSION, "hython",
                 "C:/opencue/scripts/stage1_export_usd.py"],
        range="1-1",
        tags=[VERSION_TAG],
        env={
            "OPENCUE_USD_OUT": args.usd,
            "OPENCUE_FRAME_START": f1,
            "OPENCUE_FRAME_END": f2,
        },
    )

    # 階段 2：husk 算圖。frame 可平行。
    stage2 = Shell(
        "husk_render",
        command=["ocrun", "houdini", VERSION, "husk", "--make-output-path",
                 "-f", "#IFRAME#", "-n", "1", "-o", args.out, args.usd],
        range=args.frames,
        tags=[VERSION_TAG],
    )

    # 【重點】整層相依：階段 2 的所有 frame 都要等階段 1 全部完成
    stage2.depend_all(stage1)

    ol.add_layer(stage1)
    ol.add_layer(stage2)

    print("job     :", name)
    print("階段 1  :", stage1.get_arg("command"), "range=1-1")
    print("階段 2  :", stage2.get_arg("command"), "range=%s" % args.frames)
    print("相依    : husk_render depend_all export_usd")

    if args.dry_run:
        print("(dry run)")
        return 0

    # 先暫停送出，確保相依接線完成後才開始派工（見 notes/sandbox/20）
    outline.cuerun.launch(ol, pause=True, use_pycuerun=False)
    print("已送出（暫停狀態），請 resume 後開始執行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
