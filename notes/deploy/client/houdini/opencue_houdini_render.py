# OpenCue render script for Houdini.
#
# Runs on the render node under hython, in the command that
# opencue_houdini_submit.py builds:
#     ocrun houdini <version> hython opencue_houdini_render.py <hip> <node> <framespec>
# <framespec> is Cuebot's #FRAMESPEC# token, the frames of this task: "7",
# "1-10", "1-9x2". A task renders its frames in one call, in order, so a
# simulation submitted as a single task cooks from its first frame.
#
# ASCII ONLY. Python 2.7 compatible, for any hython.

import re
import sys

import hou


def parse_framespec(spec):
    """'1-9x2,12' -> [(1, 9, 2), (12, 12, 1)]"""
    ranges = []
    for item in spec.split(","):
        match = re.match(r"^(-?\d+)(?:-(-?\d+)(?:x(\d+))?)?$", item.strip())
        if not match:
            raise ValueError("unsupported frame spec: " + spec)
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        step = int(match.group(3)) if match.group(3) else 1
        ranges.append((start, end, step))
    return ranges


def render(node, start, end, step):
    if isinstance(node, hou.RopNode):
        node.render(frame_range=(start, end, step), verbose=True, output_progress=True)
    else:
        # File Cache SOP and Karma LOP are not RopNodes, but they have the same
        # frame range parameters and an execute button.
        node.parm("trange").set(1)
        node.parmTuple("f").set((start, end, step))
        node.parm("execute").pressButton()
    errors = node.errors()
    if errors:
        raise RuntimeError("\n".join(errors))


def main(argv):
    hip, path, spec = argv
    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    node = hou.node(path)
    if node is None:
        raise RuntimeError("node not found: " + path)
    for start, end, step in parse_framespec(spec):
        print("[opencue] {0} frames {1}-{2} step {3}".format(path, start, end, step))
        sys.stdout.flush()
        render(node, start, end, step)


if __name__ == "__main__":
    main(sys.argv[1:])
