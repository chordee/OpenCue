# OpenCue submit window for Nuke.
#
# Runs OUTSIDE Nuke with the studio's OpenCue Python (C:\opencue\venv), started
# by opencue_nuke_launcher.py with a JSON file that describes the script, its
# Write nodes, the frame range and the Nuke version. Shows the standard
# CueSubmit window with a Nuke panel:
#     render command  ocrun nuke <version> Nuke<major.minor> -F #FRAMESPEC#
#                     [-X Write1,Write2] -x <script>
#     service         the one whose tags hold nuke_<version>
#
# CueSubmit's own Nuke job type is not used: it sends "-X [All]" when no Write
# node is picked, "-X a, b" for several, and "-F #IFRAME#", which renders only
# the first frame of a chunk. The Shell job type sends the command as built here.
#
# Chinese documentation: notes/deploy/03.

import argparse
import json
import os
import sys

from qtpy import QtWidgets

import opencue
from cuesubmit import JobTypes
from cuesubmit.ui import SettingsWidgets
from cuesubmit.ui import Style
from cuesubmit.ui import Submit
from cuesubmit.ui import Widgets

RENDER_CMD = "ocrun nuke {version} {program} -F #FRAMESPEC#{writes} -x {script}"
VERSION_TAG = "nuke_{version}"


def program_name(version):
    """17.0v1 -> Nuke17.0"""
    return "Nuke" + version.split("v")[0]


class NukeSettings(SettingsWidgets.BaseSettingsWidget):
    """Script file and the Write nodes to render (all of them by default)."""

    # pylint: disable=keyword-arg-before-vararg,unused-argument
    def __init__(self, info=None, parent=None, *args, **kwargs):
        super(NukeSettings, self).__init__(parent=parent)
        self.groupBox.setTitle("Nuke options")
        self.version = info["version"]
        self.writes = info["writes"]
        self.scriptInput = Widgets.CueLabelLineEdit("Nuke Script:", info["script"])
        self.writeSelector = Widgets.CueSelectPulldown(
            "Write Nodes", emptyText="[pick at least one]", options=self.writes)
        self.writeSelector.setChecked(self.writes)
        self.groupLayout.addWidget(self.scriptInput)
        self.groupLayout.addWidget(self.writeSelector)
        self.scriptInput.textChanged.connect(lambda: self.dataChanged.emit(None))
        self.writeSelector.optionsMenu.triggered.connect(lambda: self.dataChanged.emit(None))

    def getCommandData(self):
        checked = self.writeSelector.getChecked()
        # All of them: leave -X out, Nuke renders every enabled Write node.
        writes = "" if not checked or len(checked) == len(self.writes) \
            else " -X " + ",".join(checked)
        command = RENDER_CMD.format(version=self.version,
                                    program=program_name(self.version),
                                    writes=writes, script=self.scriptInput.text())
        return {"commandTextBox": command, "script": self.scriptInput.text(),
                "writes": checked}

    def setCommandData(self, commandData):
        self.scriptInput.setText(commandData.get("script", self.scriptInput.text()))
        self.writeSelector.setChecked(commandData.get("writes", self.writes))


class NukeJobTypes(JobTypes.JobTypes):
    # Submission sends a Shell layer's commandTextBox as the command.
    SETTINGS_MAP = {JobTypes.JobTypes.SHELL: NukeSettings}


def find_service(version):
    tag = VERSION_TAG.format(version=version.replace(".", "_"))
    for service in opencue.api.getDefaultServices():
        if tag in service.tags():
            return service.name()
    return None


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--info", required=True)
    return parser.parse_args(argv)


def build_window(info):
    window = QtWidgets.QMainWindow()
    widget = Submit.CueSubmitWidget(
        settingsWidgetType=NukeJobTypes.SHELL,
        jobTypes=NukeJobTypes,
        info=info,
        parent=window)
    widget.frameBox.frameSpecInput.setText(info["range"])
    widget.layerNameInput.setText("render")

    service = find_service(info["version"])
    widget.servicesSelector.clearChecked()
    if service:
        widget.servicesSelector.setChecked([service])
    widget.jobDataChanged()

    window.setStyleSheet(Style.MAIN_WINDOW)
    window.setCentralWidget(widget)
    title = "Submit Nuke {0} to OpenCue".format(info["version"])
    if not service:
        title += " - no service for this version, pick one"
    window.setWindowTitle(title)
    window.resize(650, 1000)
    return window, widget


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    with open(args.info) as f:
        info = json.load(f)
    os.remove(args.info)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window, _ = build_window(info)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
