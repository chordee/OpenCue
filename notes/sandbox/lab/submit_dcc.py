#!/usr/bin/env python
"""Submit DCC render jobs to OpenCue farm (Houdini / Maya / Nuke).

Key architectural design points from notes/sandbox/12-real-dcc-rendering.md:

1. Commands passed as lists, preventing shlex from stripping Windows backslashes.
2. Invokes DCCs via ocrun <product> <version> <executable>, resolved dynamically by each node's dcc.toml
   (notes/sandbox/26-ocrun-wrapper.md).
3. Layer tags bind DCC versions so Cuebot only dispatches to nodes with that version installed.
4. Frame numbers passed via Cuebot's #IFRAME# token or RQD-injected CUE_IFRAME.

Usage:
    python submit_dcc.py houdini --frames 1-4
    python submit_dcc.py maya    --frames 1-3
    python submit_dcc.py nuke    --frames 1-3
"""
import argparse
import sys

import outline
import outline.cuerun
from outline.modules.shell import Shell

PRESETS = {
    "houdini": {
        "version": "22_0_429",
        "tag": "houdini_22_0_429",
        "command": ["ocrun", "houdini", "22.0.429", "hython",
                    "P:/projects/opencue_test/scripts/houdini_render_frame.py"],
        "env": {"OPENCUE_RENDER_OUT": "P:/projects/opencue_test/render",
                "OPENCUE_RENDERER": "karma"},
    },
    "maya": {
        "version": "2027",
        "tag": "maya_2027",
        "command": ["ocrun", "maya", "2027", "Render",
                    "-r", "sw", "-s", "#IFRAME#", "-e", "#IFRAME#",
                    "-rd", "P:/projects/opencue_test/render/maya",
                    "P:/projects/opencue_test/scenes/test.ma"],
        "env": {},
    },
    "nuke": {
        "version": "17_0v1",
        "tag": "nuke_17_0v1",
        "command": ["ocrun", "nuke", "17.0v1", "Nuke17.0", "-t",
                    "P:/projects/opencue_test/scripts/nuke_render_frame.py"],
        "env": {"OPENCUE_RENDER_OUT": "P:/projects/opencue_test/render/nuke"},
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("app", choices=sorted(PRESETS))
    ap.add_argument("--show", default="testing")
    ap.add_argument("--shot", default="testshot")
    ap.add_argument("--frames", default="1-3")
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    preset = PRESETS[args.app]
    # [IMPORTANT] Specify version tag only; do not include general.
    # Cuebot tag matching is regex-based: host.str_tags ~* ('(?x)' || layer.str_tags || '\y')
    # Multiple layer tags are concatenated with " | " which acts as regex OR:
    # adding general matches any node advertising general, bypassing version targeting.
    tags = [preset["tag"]]
    short_name = "%s_render_%s" % (args.app, preset["version"])

    print("job     :", short_name)
    print("frames  :", args.frames)
    print("tags    :", tags)
    print("command :", preset["command"])

    if args.dry_run:
        print("(dry run)")
        return 0

    layer = Shell(
        "%s_render" % args.app,
        command=preset["command"],      # List, not string
        range=args.frames,
        tags=tags,
        env=preset["env"],
    )
    ol = outline.Outline(short_name, shot=args.shot, show=args.show)
    ol.add_layer(layer)
    outline.cuerun.launch(ol, pause=args.paused, use_pycuerun=False)
    print("Submitted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
