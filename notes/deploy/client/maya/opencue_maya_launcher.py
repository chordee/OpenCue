# OpenCue submit launcher for Maya.
#
# Runs INSIDE Maya, any version (Python 2.7 or 3.x). It only uses maya.cmds and
# subprocess: it collects the scene path, cameras, frame range and Maya version,
# then starts opencue_maya_submit.py with the studio's OpenCue Python, which
# shows the CueSubmit window. Nothing from OpenCue has to be installed into
# Maya's own Python, so every Maya version on the machine shares one install.
#
# Shelf button command (Python):
#     import opencue_maya_launcher; opencue_maya_launcher.submit()
#
# Chinese documentation: notes/deploy/03.

import os
import subprocess

import maya.cmds as cmds

PYTHON = os.environ.get("OPENCUE_PYTHON", r"C:\opencue\venv\Scripts\pythonw.exe")
SUBMIT_SCRIPT = os.environ.get(
    "OPENCUE_MAYA_SUBMIT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencue_maya_submit.py"))

CREATE_NO_WINDOW = 0x08000000

# Maya points these at its own Python and Qt. The OpenCue Python is a different
# version and must not see them.
_INHERITED_PREFIXES = ("PYTHON", "QT_", "QTDIR", "PYSIDE")


def _scene():
    scene = cmds.file(query=True, sceneName=True)
    if not scene:
        cmds.confirmDialog(title="OpenCue", message="Save the scene before submitting.",
                           button=["OK"])
        return None
    if cmds.file(query=True, modified=True):
        answer = cmds.confirmDialog(
            title="OpenCue", message="The scene has unsaved changes. Save now?",
            button=["Save", "Cancel"], defaultButton="Save",
            cancelButton="Cancel", dismissString="Cancel")
        if answer != "Save":
            return None
        cmds.file(save=True)
    return scene


def _cameras():
    shapes = cmds.ls(type="camera") or []
    return sorted(set(cmds.listRelatives(shapes, parent=True) or []))


def _version():
    return cmds.about(version=True).split()[0]


def _frame_range():
    start = int(cmds.getAttr("defaultRenderGlobals.startFrame"))
    end = int(cmds.getAttr("defaultRenderGlobals.endFrame"))
    return "{0}-{1}".format(start, end)


def _clean_env():
    return dict((k, v) for k, v in os.environ.items()
                if not k.upper().startswith(_INHERITED_PREFIXES))


def build_command():
    scene = _scene()
    if not scene:
        return None
    return ([PYTHON, SUBMIT_SCRIPT,
             "--file", scene,
             "--version", _version(),
             "--range", _frame_range(),
             "--cameras"] + _cameras())


def submit():
    cmd = build_command()
    if not cmd:
        return
    if not os.path.exists(PYTHON):
        cmds.confirmDialog(title="OpenCue", message="OpenCue Python not found: " + PYTHON,
                           button=["OK"])
        return
    # Do not wait: the submit window runs on its own and Maya stays usable.
    subprocess.Popen(cmd, env=_clean_env(), creationflags=CREATE_NO_WINDOW)
