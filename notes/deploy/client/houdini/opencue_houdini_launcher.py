# OpenCue submit launcher for Houdini.
#
# Runs INSIDE Houdini, any version (Python 2.7 or 3.x). It only uses hou and the
# standard library: it collects the hip file, the render nodes with their frame
# ranges, and the Houdini version, then starts opencue_houdini_submit.py with the
# studio's OpenCue Python, which shows the CueSubmit window. Nothing from OpenCue
# has to be installed into Houdini's own Python.
#
# Shelf tool script (Python):
#     import opencue_houdini_launcher; opencue_houdini_launcher.submit()
#
# Chinese documentation: notes/deploy/03.

import json
import os
import subprocess
import tempfile

import hou

PYTHON = os.environ.get("OPENCUE_PYTHON", r"C:\opencue\venv\Scripts\pythonw.exe")
SUBMIT_SCRIPT = os.environ.get(
    "OPENCUE_HOUDINI_SUBMIT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencue_houdini_submit.py"))

CREATE_NO_WINDOW = 0x08000000

# Houdini points these at its own Python and Qt. The OpenCue Python is a
# different version and must not see them.
_INHERITED_PREFIXES = ("PYTHON", "QT_", "QTDIR", "PYSIDE")

# Nodes that are not RopNodes but write to disk through an execute button.
# opencue_houdini_render.py sets their frame range and presses it. Add a type
# here only after testing it.
_OTHER_RENDER_TYPES = ("filecache::2.0", "karma")

# Parameters that suggest "this cache is a simulation": it has to be cooked
# from its first frame, in order, so it cannot be split into one task per frame.
# Only a default for the submit window; DOP, TOP and third-party cache nodes
# are not recognised, so the artist has to check it.
_SIMULATION_PARMS = ("cachesim", "initsim")


def _message(text, buttons=("OK",)):
    if hou.isUIAvailable():
        return buttons[hou.ui.displayMessage(text, buttons=buttons, title="OpenCue")]
    print("OpenCue: " + text)
    return buttons[-1]


def _hip():
    if hou.hipFile.isNewFile():
        _message("Save the hip file before submitting.")
        return None
    # hython reports unsaved changes even right after a save, so only ask in
    # the Houdini UI.
    if hou.isUIAvailable() and hou.hipFile.hasUnsavedChanges():
        if _message("The hip file has unsaved changes. Save now?", ("Save", "Cancel")) != "Save":
            return None
        hou.hipFile.save()
    return hou.hipFile.path()


def _is_render_node(node):
    # Every ROP, plus the listed non-ROP nodes that write to disk.
    if not (isinstance(node, hou.RopNode) or node.type().name() in _OTHER_RENDER_TYPES):
        return False
    # opencue_houdini_render.py drives the frame range through these.
    if node.parm("trange") is None or node.parm("f1") is None:
        return False
    return not getattr(node, "isBypassed", lambda: False)()


def _frame_range(node):
    if node.parm("trange").evalAsString() == "off":
        frame = int(hou.frame())
        return "{0}-{0}".format(frame)
    start, end, step = [int(v) for v in node.parmTuple("f").eval()]
    spec = "{0}-{1}".format(start, end)
    return spec + ("x{0}".format(step) if step > 1 else "")


def _is_simulation(node):
    for name in _SIMULATION_PARMS:
        parm = node.parm(name)
        if parm is not None and parm.eval():
            return True
    return False


def _nodes():
    nodes = [n for n in hou.node("/").allSubChildren(recurse_in_locked_nodes=False)
             if _is_render_node(n)]
    return [{"path": n.path(), "type": n.type().name(),
             "range": _frame_range(n), "simulation": _is_simulation(n)} for n in nodes]


def _selected(nodes):
    paths = [n["path"] for n in nodes]
    for node in hou.selectedNodes():
        if node.path() in paths:
            return node.path()
    return paths[0] if paths else ""


def _clean_env():
    return dict((k, v) for k, v in os.environ.items()
                if not k.upper().startswith(_INHERITED_PREFIXES))


def build_command():
    hip = _hip()
    if not hip:
        return None
    nodes = _nodes()
    if not nodes:
        _message("No render node (ROP, File Cache, Karma) found in this hip file.")
        return None
    info = {"hip": hip, "version": hou.applicationVersionString(),
            "nodes": nodes, "selected": _selected(nodes)}
    handle, path = tempfile.mkstemp(prefix="opencue_houdini_", suffix=".json")
    with os.fdopen(handle, "w") as f:
        json.dump(info, f)
    return [PYTHON, SUBMIT_SCRIPT, "--info", path]


def submit():
    cmd = build_command()
    if not cmd:
        return
    if not os.path.exists(PYTHON):
        _message("OpenCue Python not found: " + PYTHON)
        return
    # Do not wait: the submit window runs on its own and Houdini stays usable.
    subprocess.Popen(cmd, env=_clean_env(), creationflags=CREATE_NO_WINDOW)
