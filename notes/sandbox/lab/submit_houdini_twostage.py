#!/usr/bin/env python
"""Houdini two-stage dispatch: hython exports USD -> husk renders images.

Standard production workflow for large Houdini scenes and live pipeline dependency chaining:

    Stage 1  hython  Builds scene and exports USD       (1 frame)
       |     depend_all (LayerOnLayer)
       v
    Stage 2  husk    Renders exported USD directly      (N frames, parallel)

husk avoids initializing full Houdini sessions, launching much faster than hython.

Usage:
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
    ap.add_argument("--usd", default="P:/projects/opencue_test/render/twostage.usda")
    ap.add_argument("--out", default="P:/projects/opencue_test/render/twostage.$F4.exr")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    f1, _, f2 = args.frames.partition("-")
    f2 = f2 or f1

    name = "houdini_twostage_%d" % int(time.time())
    ol = outline.Outline(name, shot=args.shot, show=args.show)

    # Stage 1: Export USD. Exactly one frame.
    stage1 = Shell(
        "export_usd",
        command=["ocrun", "houdini", VERSION, "hython",
                 "P:/projects/opencue_test/scripts/stage1_export_usd.py"],
        range="1-1",
        tags=[VERSION_TAG],
        env={
            "OPENCUE_USD_OUT": args.usd,
            "OPENCUE_FRAME_START": f1,
            "OPENCUE_FRAME_END": f2,
        },
    )

    # Stage 2: husk rendering. Frames run in parallel.
    stage2 = Shell(
        "husk_render",
        command=["ocrun", "houdini", VERSION, "husk", "--make-output-path",
                 "-f", "#IFRAME#", "-n", "1", "-o", args.out, args.usd],
        range=args.frames,
        tags=[VERSION_TAG],
    )

    # [KEY] Layer-level dependency: all frames in Stage 2 wait for Stage 1 to complete
    stage2.depend_all(stage1)

    ol.add_layer(stage1)
    ol.add_layer(stage2)

    print("job     :", name)
    print("Stage 1 :", stage1.get_arg("command"), "range=1-1")
    print("Stage 2 :", stage2.get_arg("command"), "range=%s" % args.frames)
    print("Dependency : husk_render depend_all export_usd")

    if args.dry_run:
        print("(dry run)")
        return 0

    # Submit in paused state to ensure dependency wiring completes before dispatch starts (see notes/sandbox/20-dependencies-and-operations.md)
    outline.cuerun.launch(ol, pause=True, use_pycuerun=False)
    print("Submitted (paused state); resume to begin execution")
    return 0


if __name__ == "__main__":
    sys.exit(main())
