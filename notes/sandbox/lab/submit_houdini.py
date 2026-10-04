#!/usr/bin/env python
"""Submit Houdini render jobs to OpenCue farm.

Demonstrates three critical production practices:

1. **Commands passed as lists**
   pyoutline prep_shell_command() (outline/io.py:53) calls shlex.split() only when command
   is a string; in POSIX mode shlex strips backslashes on Windows. Passing a list bypasses this.

2. **Decoupled DCC install paths**
   Command invokes ocrun houdini <version> hython ...; ocrun resolves local paths from
   node-specific dcc.toml, supporting divergent drive letters.

3. **Bind DCC version via layer tags**
   Nodes advertise installed versions via RQD_TAGS; jobs request matching tags,
   ensuring Cuebot only dispatches to eligible machines.

Usage:
    python submit_houdini.py --frames 1-4 --version 22_0_429
"""
import argparse
import os
import sys

import outline
import outline.cuerun
from outline.modules.shell import Shell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", default="testing")
    ap.add_argument("--shot", default="testshot")
    ap.add_argument("--name", default="houdini_render")
    ap.add_argument("--frames", default="1-4", help="frame range, e.g. 1-4")
    ap.add_argument("--version", default="22_0_429",
                    help="Houdini version tag suffix, e.g. 22_0_429")
    ap.add_argument("--script", default="P:/projects/opencue_test/scripts/houdini_render_frame.py")
    ap.add_argument("--out", default="P:/projects/opencue_test/render",
                    help="Render output directory. In production, must be shared storage UNC path")
    ap.add_argument("--renderer", default="karma", choices=["karma", "opengl"])
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Version uses dots in ocrun and underscores in tags
    dotted = args.version.replace("_", ".")
    version_tag = "houdini_%s" % args.version

    # [CRITICAL] List format, not string
    command = ["ocrun", "houdini", dotted, "hython", args.script]

    layer = Shell(
        "houdini_render",
        command=command,
        range=args.frames,
        # Only specify version tag. Cuebot tag matching is regex-based with | delimiter (OR logic);
        # appending general bypasses version binding. See notes/sandbox/12-real-dcc-rendering.md.
        tags=[version_tag],
        env={
            "OPENCUE_RENDER_OUT": args.out,
            "OPENCUE_RENDERER": args.renderer,
        },
    )

    short_name = "%s_%s" % (args.name, args.version)

    print("job      :", short_name)
    print("frames   :", args.frames)
    print("tags     :", [version_tag])
    print("command  :", command)
    print("output   :", args.out)
    print("renderer :", args.renderer)

    if args.dry_run:
        print("(dry run, not submitted)")
        return 0

    ol = outline.Outline(short_name, shot=args.shot, show=args.show)
    ol.add_layer(layer)
    outline.cuerun.launch(ol, pause=args.paused, use_pycuerun=False)
    print("Submitted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
