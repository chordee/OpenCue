# OpenCue submit window for rendering an existing USD file with husk, without
# opening Houdini.
#
# Runs with the studio's OpenCue Python (C:\opencue\venv):
#     C:\opencue\venv\Scripts\python.exe opencue_husk_submit.py [file.usd]
# or drop a USD file on opencue_husk_submit.bat. Shows the standard CueSubmit
# window with a husk panel:
#     render command  ocrun houdini <version> husk --make-output-path
#                     --frame #IFRAME# --frame-count 1 [--renderer ...]
#                     [--settings/--camera/--output/--res overrides] [args] <usd>
#     service         the one whose tags hold houdini_<version>
# The Houdini versions offered are the ones some service is tagged for.
#
# Chinese documentation: notes/deploy/03.

import os
import re
import sys

from qtpy import QtWidgets

import opencue
from cuesubmit import JobTypes
from cuesubmit.ui import SettingsWidgets
from cuesubmit.ui import Style
from cuesubmit.ui import Submit
from cuesubmit.ui import Widgets

from opencue_houdini_submit import (HUSK_CMD, add_env_box, env_error, find_service,
                                    service_error)

VERSION_TAG = re.compile(r"^houdini_(\d+)_(\d+)_(\d+)$")

# husk uses Karma CPU when no renderer is given, even for a stage set to XPU.
RENDERERS = {"Karma CPU": "BRAY_HdKarma", "Karma XPU": "BRAY_HdKarmaXPU",
             "No --renderer": None}


def houdini_versions():
    """Houdini versions some service is tagged for, newest first."""
    versions = set()
    for service in opencue.api.getDefaultServices():
        for tag in service.tags():
            match = VERSION_TAG.match(tag)
            if match:
                versions.add(tuple(int(n) for n in match.groups()))
    return [".".join(str(n) for n in v) for v in sorted(versions, reverse=True)]


# Overrides of what the USD file sets; an empty field keeps the file's value.
OVERRIDES = (("settings", "Render Settings:", "--settings", "/Render/rendersettings"),
             ("camera", "Camera:", "--camera", "/cameras/shotCam"),
             ("output", "Output:", "--output", "P:/projects/show/render/shot.$F4.exr"),
             ("res", "Resolution:", "--res", "1920x1080"))
RESOLUTION = re.compile(r"^(\d+)\s*[xX ]\s*(\d+)$")


def husk_command(version, usd, renderer, extra, overrides=None):
    args = []
    if RENDERERS.get(renderer):
        args += ["--renderer", RENDERERS[renderer]]
    for key, _, flag, _ in OVERRIDES:
        value = (overrides or {}).get(key, "").strip()
        if not value:
            continue
        match = RESOLUTION.match(value) if key == "res" else None
        args += [flag] + (list(match.groups()) if match else [value])
    args += extra.split()
    return HUSK_CMD.format(version=version, usd=usd, args="".join(a + " " for a in args))


# Each task renders the frame OpenCue hands it; these would change that.
FRAME_FLAGS = ("-f", "--frame", "-n", "--frame-count", "-i", "--frame-inc", "--frame-list")


def extra_error(extra):
    for arg in extra.split():
        # -f5: a short option with its value attached.
        if arg.split("=", 1)[0] in FRAME_FLAGS or arg[:2] in ("-f", "-n", "-i"):
            return ("Extra husk arguments must not set frames ({0}): OpenCue sets the "
                    "frame of each task.".format(arg))
    return None


def overrides_error(overrides):
    for key, label, _, _ in OVERRIDES:
        value = overrides.get(key, "").strip()
        if not value:
            continue
        if key == "res":
            if not RESOLUTION.match(value):
                return "Resolution must be WIDTHxHEIGHT, for example 1920x1080."
        elif " " in value or "%" in value:
            return "{0} must not contain spaces or %: {1}".format(label.rstrip(":"), value)
    return None


class HuskSettings(SettingsWidgets.BaseSettingsWidget):
    """USD file, Houdini version, renderer and extra husk arguments."""

    # pylint: disable=keyword-arg-before-vararg,unused-argument
    def __init__(self, versions=None, usd="", parent=None, *args, **kwargs):
        super(HuskSettings, self).__init__(parent=parent)
        self.groupBox.setTitle("husk options")
        self.usdInput = Widgets.CueLabelLineEdit("USD File:", usd)
        self.versionSelector = Widgets.CueSelectPulldown(
            "Houdini Version", options=versions or ["(no Houdini service)"],
            multiselect=False)
        self.rendererSelector = Widgets.CueSelectPulldown(
            "Renderer", options=list(RENDERERS), multiselect=False)
        self.overrideInputs = dict(
            (key, Widgets.CueLabelLineEdit(
                label, tooltip="Leave empty to use the USD file's value. Example: " + example))
            for key, label, _, example in OVERRIDES)
        self.argsInput = Widgets.CueLabelLineEdit(
            "Extra husk arguments:", tooltip="Any other husk options, for example --res-scale 50")
        for widget in ([self.usdInput, self.versionSelector, self.rendererSelector]
                       + [self.overrideInputs[key] for key, _, _, _ in OVERRIDES]
                       + [self.argsInput]):
            self.groupLayout.addWidget(widget)
        self.envInput = add_env_box(self)
        for widget in [self.usdInput, self.argsInput] + list(self.overrideInputs.values()):
            widget.textChanged.connect(lambda: self.dataChanged.emit(None))
        self.versionSelector.optionsMenu.triggered.connect(lambda: self.dataChanged.emit(None))
        self.rendererSelector.optionsMenu.triggered.connect(lambda: self.dataChanged.emit(None))

    def version(self):
        return self.versionSelector.getChecked()[0]

    def overrides(self):
        return dict((key, widget.text()) for key, widget in self.overrideInputs.items())

    def getCommandData(self):
        renderer = self.rendererSelector.getChecked()[0]
        return {"commandTextBox": husk_command(self.version(), self.usdInput.text(),
                                               renderer, self.argsInput.text(),
                                               self.overrides()),
                "usd": self.usdInput.text(), "version": self.version(),
                "renderer": renderer, "extra": self.argsInput.text(),
                "overrides": self.overrides(), "env": self.envInput.toPlainText()}

    def setCommandData(self, commandData):
        self.usdInput.setText(commandData.get("usd", self.usdInput.text()))
        if commandData.get("version"):
            self.versionSelector.setChecked([commandData["version"]])
        if commandData.get("renderer"):
            self.rendererSelector.setChecked([commandData["renderer"]])
        self.argsInput.setText(commandData.get("extra", ""))
        for key, widget in self.overrideInputs.items():
            widget.setText(commandData.get("overrides", {}).get(key, ""))
        self.envInput.setPlainText(commandData.get("env", ""))


class HuskJobTypes(JobTypes.JobTypes):
    # Submission sends a Shell layer's commandTextBox as the command.
    SETTINGS_MAP = {JobTypes.JobTypes.SHELL: HuskSettings}


def usd_error(usd):
    if not usd:
        return "Set the USD file."
    if " " in usd:
        return "The USD path must not contain spaces: {0}".format(usd)
    if not os.path.isabs(usd):
        # A render node runs the task in its own directory.
        return "The USD path must be absolute: {0}".format(usd)
    if not os.path.isfile(usd):
        return "USD file not found: {0}".format(usd)
    return None


class HuskSubmitWidget(Submit.CueSubmitWidget):
    """Refuses a job that could run on a node without the chosen Houdini."""

    def validate(self, jobData):
        for layer in jobData.get("layers") or []:
            error = (usd_error(layer.cmd.get("usd"))
                     or overrides_error(layer.cmd.get("overrides", {}))
                     or extra_error(layer.cmd.get("extra", ""))
                     or service_error(layer.services, layer.cmd.get("version", ""))
                     or env_error(layer.cmd))
            if not error and str(layer.chunk) != "1":
                error = "husk renders one frame per task: set the chunk size to 1."
            if error:
                return self.errorInJobData("ERROR: Job not submitted!\n" + error)
        return super(HuskSubmitWidget, self).validate(jobData)


def build_window(usd="", versions=None):
    versions = houdini_versions() if versions is None else versions
    window = QtWidgets.QMainWindow()
    widget = HuskSubmitWidget(
        settingsWidgetType=HuskJobTypes.SHELL,
        jobTypes=HuskJobTypes,
        versions=versions,
        usd=usd.replace("\\", "/"),
        parent=window)

    def version_changed():
        # The service follows the version, as the tag pins the nodes.
        service = find_service(widget.settingsWidget.version())
        widget.servicesSelector.clearChecked()
        if service:
            widget.servicesSelector.setChecked([service])
        widget.jobDataChanged()

    widget.settingsWidget.versionSelector.optionsMenu.triggered.connect(version_changed)
    name = os.path.splitext(os.path.basename(usd))[0] if usd else ""
    widget.jobNameInput.setText(name)
    widget.layerNameInput.setText("husk")
    widget.chunkInput.setText("1")
    version_changed()

    window.setStyleSheet(Style.MAIN_WINDOW)
    window.setCentralWidget(widget)
    title = "Submit USD to OpenCue (husk)"
    if not versions:
        title += " - no service has a houdini_<version> tag"
    window.setWindowTitle(title)
    window.resize(650, 1000)
    return window, widget


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window, _ = build_window(argv[0] if argv else "")
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
