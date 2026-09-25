#!/usr/bin/env python
"""Maya / Houdini / Nuke 投遞視窗的回歸測試。

兩個投遞工具依賴 CueSubmit 的內部類別與欄位（InMayaSettings、MAYA_RENDER_CMD、
Shell layer 的 commandTextBox、CueSelectPulldown、chunkInput）。同步上游 CueSubmit
之後先跑這支，確認組出的指令、service、frame 範圍、chunk 都沒變。

在 OpenCue venv 執行，需要連得到 Cuebot（service 以 tag 反查）：

    set QT_QPA_PLATFORM=offscreen
    C:\\opencue\\venv\\Scripts\\python.exe check_submit_tools.py            只檢查，不送出
    C:\\opencue\\venv\\Scripts\\python.exe check_submit_tools.py --submit   檢查後實際送出

預期值依本機 sandbox（Maya 2027、Houdini 22.0.429、Nuke 17.0v1、service maya2027 / houdini2204 / nuke17）。
"""
import argparse
import os
import sys

from qtpy import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(HERE, "..", "..", "deploy", "client")

# The tools are imported from the repo by default. Point these at the installed
# copies (for example P:/pipeline/opencue/client/maya) to test an installation.
ap = argparse.ArgumentParser()
ap.add_argument("--submit", action="store_true", help="實際送出 job")
ap.add_argument("--maya-dir", default=os.path.join(CLIENT, "maya"))
ap.add_argument("--houdini-dir", default=os.path.join(CLIENT, "houdini"))
ap.add_argument("--nuke-dir", default=os.path.join(CLIENT, "nuke"))
ARGS = ap.parse_args()
sys.path.insert(0, ARGS.maya_dir)
sys.path.insert(0, ARGS.houdini_dir)
sys.path.insert(0, ARGS.nuke_dir)

import opencue_houdini_submit  # noqa: E402
import opencue_maya_submit  # noqa: E402
import opencue_nuke_submit  # noqa: E402
from cuesubmit import Submission  # noqa: E402

HIP = "P:/projects/opencue_test/scenes/hou_submit_test.hip"
HOUDINI_INFO = {
    "hip": HIP, "version": "22.0.429", "selected": "/obj/geo1/convert_cache",
    "nodes": [
        {"path": "/obj/geo1/convert_cache", "type": "filecache::2.0", "range": "1-4",
         "simulation": False},
        {"path": "/obj/geo1/sim_cache", "type": "filecache::2.0", "range": "1-10",
         "simulation": True},
    ],
}
NUKE_SCRIPT = "P:/projects/opencue_test/scenes/nuke_submit_test.nk"
NUKE_INFO = {"script": NUKE_SCRIPT, "version": "17.0v1", "range": "1-5",
             "writes": ["WriteA", "Comp.WriteB"]}
FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print("{0}  {1}: {2!r}".format("PASS" if ok else "FAIL", label, actual))
    if not ok:
        print("      expected: {0!r}".format(expected))
        FAILURES.append(label)


def fill(widget, name):
    widget.jobNameInput.setText(name)
    widget.shotInput.setText("sh010")
    widget.layerNameInput.setText(name)
    widget.jobDataChanged()
    return widget.jobTreeWidget.currentLayerData


def check_services(widget, good, builtin):
    """Only a service with the version tag may pass validate()."""
    for services, expected in ((builtin, False), ([], False), ([good], True)):
        widget.servicesSelector.clearChecked()
        widget.servicesSelector.setChecked(services)
        widget.jobDataChanged()
        check("validate with services {0}".format(services),
              widget.validate(widget.getJobData()), expected)


def check_maya(submit):
    print("--- Maya")
    args = opencue_maya_submit.parse_args([
        "--file", "P:/projects/opencue_test/scenes/test.ma", "--version", "2027", "--range", "1-2",
        "--cameras", "front", "persp", "renderCam1", "--renderable", "renderCam1"])
    window, widget = opencue_maya_submit.build_window(args)
    layer = fill(widget, "check_maya")
    check("service", layer.services, ["maya2027"])
    check("range", layer.layerRange, "1-2")
    check("command", Submission.buildLayerCommand(layer),
          "ocrun maya 2027 Render -r file -s #FRAME_START# -e #FRAME_END# "
          "-cam renderCam1 P:/projects/opencue_test/scenes/test.ma")
    check_services(widget, "maya2027", ["maya"])
    if submit:
        widget.submit()
    for action in widget.settingsWidget.cameraSelector.optionsMenu.actions():
        if action.text() == "front":
            action.trigger()
    check("camera change reaches the layer",
          widget.jobTreeWidget.currentLayerData.cmd["camera"], "front")
    window.close()


def select_node(widget, path):
    for action in widget.settingsWidget.nodeSelector.optionsMenu.actions():
        if action.text() == path:
            action.trigger()


def check_houdini(submit):
    print("--- Houdini")
    window, widget = opencue_houdini_submit.build_window(HOUDINI_INFO)
    script = opencue_houdini_submit.RENDER_SCRIPT
    for path, expected_range, expected_chunk in (
            ("/obj/geo1/convert_cache", "1-4", "1"),
            ("/obj/geo1/sim_cache", "1-10", "10")):
        select_node(widget, path)
        check(path + " layer name", widget.layerNameInput.text(), path.rsplit("/", 1)[-1])
        layer = fill(widget, "check_houdini_" + path.rsplit("/", 1)[-1])
        check(path + " service", layer.services, ["houdini2204"])
        check(path + " range", layer.layerRange, expected_range)
        check(path + " chunk", str(layer.chunk), expected_chunk)
        check(path + " command", Submission.buildLayerCommand(layer),
              "ocrun houdini 22.0.429 hython {0} {1} {2} #FRAMESPEC#".format(script, HIP, path))
        check_services(widget, "houdini2204", ["houdini"])
        if submit:
            widget.submit()
    window.close()


def check_nuke(submit):
    print("--- Nuke")
    window, widget = opencue_nuke_submit.build_window(NUKE_INFO)
    layer = fill(widget, "check_nuke_all")
    check("service", layer.services, ["nuke17"])
    check("range", layer.layerRange, "1-5")
    check("command, all writes", Submission.buildLayerCommand(layer),
          "ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -x " + NUKE_SCRIPT)
    check_services(widget, "nuke17", ["nuke"])
    if submit:
        widget.submit()
    for action in widget.settingsWidget.writeSelector.optionsMenu.actions():
        if action.text() == "Comp.WriteB":
            action.trigger()
    layer = fill(widget, "check_nuke_one")
    check("command, one write", Submission.buildLayerCommand(layer),
          "ocrun nuke 17.0v1 Nuke17.0 -F #FRAMESPEC# -X WriteA -x " + NUKE_SCRIPT)
    if submit:
        widget.submit()
    for action in widget.settingsWidget.writeSelector.optionsMenu.actions():
        if action.text() == "WriteA":
            action.trigger()
    check("no write checked is rejected", widget.validate(widget.getJobData()), False)
    window.close()


def main():
    app = QtWidgets.QApplication(sys.argv[:1])  # noqa: F841
    print("tools:", opencue_maya_submit.__file__, opencue_houdini_submit.__file__,
          opencue_nuke_submit.__file__, sep="\n  ")
    check_maya(ARGS.submit)
    check_houdini(ARGS.submit)
    check_nuke(ARGS.submit)
    print("\n{0} failure(s)".format(len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
