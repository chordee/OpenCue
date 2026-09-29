# OpenCue render script for Houdini.
#
# Runs on the render node under hython, in the command that
# opencue_houdini_submit.py builds:
#     ocrun houdini <version> hython opencue_houdini_render.py <hip> <node> <framespec>
# <framespec> is Cuebot's #FRAMESPEC# token, the frames of this task: "7",
# "1-10", "1-9x2". A task renders its frames in one call, in order, so a
# simulation submitted as a single task cooks from its first frame.
#
# With --export-usd, the task instead saves the node's USD stage to one file
# (all frames of <framespec> as time samples) for the husk layer to render:
#     ... opencue_houdini_render.py --export-usd <usd> <hip> <node> <framespec>
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


def stage_node(node):
    """The LOP whose stage the render node renders."""
    kind = node.type().name()
    if kind == "karma":
        return node
    if kind == "usdrender":
        return node.parm("loppath").evalAsNode()
    if kind == "usdrender_rop":
        return node.inputs()[0] if node.inputs() else None
    raise RuntimeError("not a USD render node: " + node.path())


def export_usd(node, usd, spec):
    lop = stage_node(node)
    if lop is None:
        raise RuntimeError("no LOP stage to export for " + node.path())
    frames = [f for start, end, step in parse_framespec(spec) for f in (start, end)]
    rop = hou.node("/out").createNode("usd", "opencue_export_usd")
    rop.parm("loppath").set(lop.path())
    rop.parm("lopoutput").set(usd)
    print("[opencue] {0} -> {1}, frames {2}-{3}".format(lop.path(), usd, min(frames), max(frames)))
    sys.stdout.flush()
    render(rop, min(frames), max(frames), 1)


def main(argv):
    usd = None
    if argv and argv[0] == "--export-usd":
        usd, argv = argv[1], argv[2:]
    hip, path, spec = argv
    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    node = hou.node(path)
    if node is None:
        raise RuntimeError("node not found: " + path)
    if usd:
        export_usd(node, usd, spec)
        return
    for start, end, step in parse_framespec(spec):
        print("[opencue] {0} frames {1}-{2} step {3}".format(path, start, end, step))
        sys.stdout.flush()
        render(node, start, end, step)


if __name__ == "__main__":
    main(sys.argv[1:])
