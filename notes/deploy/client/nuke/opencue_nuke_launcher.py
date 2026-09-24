# OpenCue submit launcher for Nuke.
#
# Runs INSIDE Nuke, any version (Python 2.7 or 3.x). It only uses nuke and the
# standard library: it collects the script path, its enabled Write nodes, the
# frame range and the Nuke version, then starts opencue_nuke_submit.py with the
# studio's OpenCue Python, which shows the CueSubmit window. Nothing from
# OpenCue has to be installed into Nuke's own Python, and Nuke is not blocked
# while the window is open.
#
# Menu command (Python):
#     import opencue_nuke_launcher; opencue_nuke_launcher.submit()
#
# Chinese documentation: notes/deploy/03.

import json
import os
import subprocess
import tempfile

import nuke

PYTHON = os.environ.get("OPENCUE_PYTHON", r"C:\opencue\venv\Scripts\pythonw.exe")
SUBMIT_SCRIPT = os.environ.get(
    "OPENCUE_NUKE_SUBMIT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencue_nuke_submit.py"))

CREATE_NO_WINDOW = 0x08000000

# Nuke points these at its own Python and Qt. The OpenCue Python is a different
# install and must not see them.
_INHERITED_PREFIXES = ("PYTHON", "QT_", "QTDIR", "PYSIDE")


def _script():
    name = nuke.root().name()
    if name == "Root":
        nuke.message("Save the script before submitting.")
        return None
    if nuke.modified():
        if not nuke.ask("The script has unsaved changes. Save now?"):
            return None
        nuke.scriptSave()
    return name


def _writes(group=None):
    group = group or nuke.root()
    writes = [n.fullName() for n in nuke.allNodes("Write", group=group)
              if not n["disable"].value()]
    for child in nuke.allNodes("Group", group=group):
        writes.extend(_writes(child))
    return writes


def _clean_env():
    return dict((k, v) for k, v in os.environ.items()
                if not k.upper().startswith(_INHERITED_PREFIXES))


def build_command():
    script = _script()
    if not script:
        return None
    writes = _writes()
    if not writes:
        nuke.message("No enabled Write node found in this script.")
        return None
    root = nuke.root()
    info = {"script": script, "version": nuke.NUKE_VERSION_STRING, "writes": writes,
            "range": "{0}-{1}".format(int(root["first_frame"].value()),
                                      int(root["last_frame"].value()))}
    handle, path = tempfile.mkstemp(prefix="opencue_nuke_", suffix=".json")
    with os.fdopen(handle, "w") as f:
        json.dump(info, f)
    return [PYTHON, SUBMIT_SCRIPT, "--info", path]


def submit():
    cmd = build_command()
    if not cmd:
        return
    if not os.path.exists(PYTHON):
        nuke.message("OpenCue Python not found: " + PYTHON)
        return
    # Do not wait: the submit window runs on its own and Nuke stays usable.
    subprocess.Popen(cmd, env=_clean_env(), creationflags=CREATE_NO_WINDOW)
