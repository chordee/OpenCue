# OpenCue submit window for Maya scenes.
#
# Runs OUTSIDE Maya with the studio's OpenCue Python (C:\opencue\venv), started
# by opencue_maya_launcher.py. Shows the standard CueSubmit window, prefilled
# with the scene, cameras and frame range, and bound to the Maya version the
# scene came from:
#     render command  ocrun maya <version> Render
#     service         the one whose tags hold maya_<version>
#
# Chinese documentation: notes/deploy/03.

import argparse
import re
import sys

from qtpy import QtWidgets

import opencue
from cuesubmit import Constants
from cuesubmit import JobTypes
from cuesubmit import Submission
from cuesubmit.ui import Command
from cuesubmit.ui import SettingsWidgets
from cuesubmit.ui import Style
from cuesubmit.ui import Submit

RENDER_CMD = "ocrun maya {version} Render"
VERSION_TAG = "maya_{version}"

# Environment box: one KEY=VALUE per line; blank lines and # lines are skipped.
ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse_env(text):
    """(variables, lines that are not KEY=VALUE) from the Environment box."""
    env, bad = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE.match(line)
        if match:
            env[match.group(1)] = match.group(2)
        else:
            bad.append(line)
    return env, bad


def env_error(command_data):
    bad = parse_env(command_data.get("env", ""))[1]
    if bad:
        return "Environment lines must be KEY=VALUE:\n" + "\n".join(bad)
    return None


def add_env_box(settings):
    """The Environment box; its text goes into getCommandData() as "env"."""
    box = Command.CueCommandTextBox()
    box.label.setText("Environment (KEY=VALUE per line):")
    box.commandBox.textChanged.connect(lambda: settings.dataChanged.emit(None))
    settings.groupLayout.addWidget(box)
    return box.commandBox


def _build_layer_with_env(layerData, command, lastLayer=None):
    """Upstream buildLayer leaves the layer's environment out; add it."""
    layer = _build_layer(layerData, command, lastLayer)
    for key, value in parse_env(layerData.cmd.get("env", ""))[0].items():
        layer.set_env(key, value)
    return layer


_build_layer = Submission.buildLayer
if not getattr(_build_layer, "adds_env", False):
    _build_layer_with_env.adds_env = True
    Submission.buildLayer = _build_layer_with_env


class MayaSettings(SettingsWidgets.InMayaSettings):
    """InMayaSettings with a single camera, and no -cam when none is chosen.

    Upstream sends the "[None]" label as the camera name when nothing is
    selected, and joins several cameras into "a, b". Render.exe accepts
    neither. Without -cam, Maya renders the scene's renderable cameras.
    """

    def __init__(self, *args, **kwargs):
        super(MayaSettings, self).__init__(*args, **kwargs)
        self.cameraSelector.multiselect = False
        # Upstream only watches the file field, so a camera change never reached the layer.
        self.cameraSelector.optionsMenu.triggered.connect(lambda: self.dataChanged.emit(None))
        self.envInput = add_env_box(self)

    def getCommandData(self):
        checked = self.cameraSelector.getChecked()
        return {"mayaFile": self.mayaFileInput.text(),
                "camera": checked[0] if checked else "",
                "env": self.envInput.toPlainText()}

    def setCommandData(self, commandData):
        super(MayaSettings, self).setCommandData(commandData)
        self.envInput.setPlainText(commandData.get("env", ""))


class MayaJobTypes(JobTypes.JobTypes):
    MAYA = "Maya"
    SETTINGS_MAP = {MAYA: MayaSettings}


def version_tag(version):
    return VERSION_TAG.format(version=version.replace(".", "_"))


def find_service(version):
    tag = version_tag(version)
    for service in opencue.api.getDefaultServices():
        if tag in service.tags():
            return service.name()
    return None


def service_error(services, version):
    """Every service of the layer must carry the version tag.

    Tags of several services are OR-ed, so one service without it (the
    built-in "maya" service is tagged general) lets the job run on any node.
    """
    tag = version_tag(version)
    if not services:
        return "Pick a service with the {0} tag.".format(tag)
    tags = dict((s.name(), s.tags()) for s in opencue.api.getDefaultServices())
    wrong = [name for name in services if tag not in tags.get(name, [])]
    if wrong:
        return ("Service {0} has no {1} tag, so the job could run on a node without "
                "this version. Pick a service with that tag.".format(", ".join(wrong), tag))
    return None


class MayaSubmitWidget(Submit.CueSubmitWidget):
    """Refuses a job whose services do not pin this Maya version."""

    def __init__(self, dccVersion, *args, **kwargs):
        super(MayaSubmitWidget, self).__init__(*args, **kwargs)
        self.dccVersion = dccVersion

    def validate(self, jobData):
        for layer in jobData.get("layers") or []:
            error = (service_error(layer.services, self.dccVersion)
                     or env_error(layer.cmd))
            if error:
                return self.errorInJobData("ERROR: Job not submitted!\n" + error)
        return super(MayaSubmitWidget, self).validate(jobData)


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--range", required=True)
    parser.add_argument("--cameras", nargs="*", default=[])
    parser.add_argument("--renderable", nargs="*", default=[])
    return parser.parse_args(argv)


def build_window(args):
    # Submission.buildMayaCmd reads this at submit time.
    Constants.MAYA_RENDER_CMD = RENDER_CMD.format(version=args.version)

    window = QtWidgets.QMainWindow()
    widget = MayaSubmitWidget(
        args.version,
        settingsWidgetType=MayaJobTypes.MAYA,
        jobTypes=MayaJobTypes,
        filename=args.file,
        cameras=args.cameras,
        parent=window)
    widget.frameBox.frameSpecInput.setText(args.range)
    if len(args.renderable) == 1:
        widget.settingsWidget.cameraSelector.setChecked(args.renderable)
    service = find_service(args.version)
    widget.servicesSelector.clearChecked()
    if service:
        widget.servicesSelector.setChecked([service])
    widget.jobDataChanged()

    window.setStyleSheet(Style.MAIN_WINDOW)
    window.setCentralWidget(widget)
    title = "Submit Maya {0} to OpenCue".format(args.version)
    if not service:
        title += " - no service has the {0} tag".format(version_tag(args.version))
    window.setWindowTitle(title)
    window.resize(650, 1000)
    return window, widget


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window, _ = build_window(args)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
