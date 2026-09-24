# OpenCue submit window for Maya scenes.
#
# Runs OUTSIDE Maya with the studio's OpenCue Python (C:\opencue\venv), started
# by opencue_maya_launcher.py. Shows the standard CueSubmit window, prefilled
# with the scene, cameras and frame range, and bound to the Maya version the
# scene came from:
#     render command  C:/opencue/bin/Render-<version>.bat
#     service         maya<version>
#
# Chinese documentation: notes/deploy/03.

import argparse
import sys

from qtpy import QtWidgets

from cuesubmit import Constants
from cuesubmit import JobTypes
from cuesubmit.ui import SettingsWidgets
from cuesubmit.ui import Style
from cuesubmit.ui import Submit

RENDER_WRAPPER = "C:/opencue/bin/Render-{version}.bat"
SERVICE = "maya{version}"


class MayaJobTypes(JobTypes.JobTypes):
    MAYA = "Maya"
    SETTINGS_MAP = {MAYA: SettingsWidgets.InMayaSettings}


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--range", required=True)
    parser.add_argument("--cameras", nargs="*", default=[])
    return parser.parse_args(argv)


def build_window(args):
    # Submission.buildMayaCmd reads this at submit time.
    Constants.MAYA_RENDER_CMD = RENDER_WRAPPER.format(version=args.version)

    window = QtWidgets.QMainWindow()
    widget = Submit.CueSubmitWidget(
        settingsWidgetType=MayaJobTypes.MAYA,
        jobTypes=MayaJobTypes,
        filename=args.file,
        cameras=args.cameras,
        parent=window)
    widget.frameBox.frameSpecInput.setText(args.range)
    widget.servicesSelector.clearChecked()
    widget.servicesSelector.setChecked([SERVICE.format(version=args.version)])
    widget.jobDataChanged()

    window.setStyleSheet(Style.MAIN_WINDOW)
    window.setCentralWidget(widget)
    window.setWindowTitle("Submit Maya {0} to OpenCue".format(args.version))
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
