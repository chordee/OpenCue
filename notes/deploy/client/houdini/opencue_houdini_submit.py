# OpenCue submit window for Houdini.
#
# Runs OUTSIDE Houdini with the studio's OpenCue Python (C:\opencue\venv),
# started by opencue_houdini_launcher.py with a JSON file that describes the hip
# file, its render nodes and the Houdini version. Shows the standard CueSubmit
# window with a Houdini panel:
#     render command  ocrun houdini <version> hython opencue_houdini_render.py
#                     <hip> <node> #FRAMESPEC#
#     service         the one whose tags hold houdini_<version>
#
# Chinese documentation: notes/deploy/03.

import argparse
import json
import os
import sys

from qtpy import QtWidgets

import opencue
from FileSequence import FrameSet
from cuesubmit import JobTypes
from cuesubmit.ui import SettingsWidgets
from cuesubmit.ui import Style
from cuesubmit.ui import Submit
from cuesubmit.ui import Widgets

# Next to this file, on the network share, so render nodes reach it too.
RENDER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "opencue_houdini_render.py").replace("\\", "/")
RENDER_CMD = "ocrun houdini {version} hython {script} {hip} {node} #FRAMESPEC#"
VERSION_TAG = "houdini_{version}"


class HoudiniSettings(SettingsWidgets.BaseSettingsWidget):
    """Hip file, one render node, and whether its whole range is one task."""

    # pylint: disable=keyword-arg-before-vararg,unused-argument
    def __init__(self, info=None, parent=None, *args, **kwargs):
        super(HoudiniSettings, self).__init__(parent=parent)
        self.groupBox.setTitle("Houdini options")
        self.version = info["version"]
        self.nodes = dict((n["path"], n) for n in info["nodes"])
        self.hipInput = Widgets.CueLabelLineEdit("Houdini File:", info["hip"])
        self.nodeSelector = Widgets.CueSelectPulldown(
            "Render Node", options=sorted(self.nodes), multiselect=False)
        self.nodeSelector.setChecked([info["selected"]])
        self.wholeRange = Widgets.CueLabelToggle(
            "Whole range as one task (simulation)",
            tooltip="Cook every frame in order in a single task. "
                    "Required for simulations; leave off to render frames in parallel.")
        self.groupLayout.addWidget(self.hipInput)
        self.groupLayout.addWidget(self.nodeSelector)
        self.groupLayout.addWidget(self.wholeRange)
        self.hipInput.textChanged.connect(lambda: self.dataChanged.emit(None))
        self.nodeSelector.optionsMenu.triggered.connect(lambda: self.dataChanged.emit(None))
        self.wholeRange.valueChanged.connect(lambda: self.dataChanged.emit(None))

    def node(self):
        return self.nodeSelector.getChecked()[0]

    def getCommandData(self):
        command = RENDER_CMD.format(version=self.version, script=RENDER_SCRIPT,
                                    hip=self.hipInput.text(), node=self.node())
        return {"commandTextBox": command, "hip": self.hipInput.text(),
                "node": self.node(), "wholeRange": bool(self.wholeRange.getter())}

    def setCommandData(self, commandData):
        self.hipInput.setText(commandData.get("hip", self.hipInput.text()))
        if commandData.get("node"):
            self.nodeSelector.setChecked([commandData["node"]])
        self.wholeRange.setter(int(commandData.get("wholeRange", False)))


class HoudiniJobTypes(JobTypes.JobTypes):
    # Submission sends a Shell layer's commandTextBox as the command.
    SETTINGS_MAP = {JobTypes.JobTypes.SHELL: HoudiniSettings}


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
        settingsWidgetType=HoudiniJobTypes.SHELL,
        jobTypes=HoudiniJobTypes,
        info=info,
        parent=window)

    def update_chunk():
        # A simulation runs as one task: chunk = every frame in the range.
        settings = widget.settingsWidget
        if settings.wholeRange.getter():
            try:
                size = FrameSet(widget.frameBox.frameSpecInput.text()).size()
            except Exception:  # pylint: disable=broad-except
                return
            widget.chunkInput.setText(str(size))
        else:
            widget.chunkInput.setText("1")

    def node_changed():
        node = widget.settingsWidget.nodes[widget.settingsWidget.node()]
        widget.frameBox.frameSpecInput.setText(node["range"])
        widget.settingsWidget.wholeRange.setter(int(node["simulation"]))
        update_chunk()

    widget.settingsWidget.nodeSelector.optionsMenu.triggered.connect(node_changed)
    widget.settingsWidget.wholeRange.valueChanged.connect(update_chunk)
    widget.frameBox.frameSpecInput.textChanged.connect(update_chunk)
    node_changed()

    service = find_service(info["version"])
    widget.servicesSelector.clearChecked()
    if service:
        widget.servicesSelector.setChecked([service])
    widget.jobDataChanged()

    window.setStyleSheet(Style.MAIN_WINDOW)
    window.setCentralWidget(widget)
    title = "Submit Houdini {0} to OpenCue".format(info["version"])
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
