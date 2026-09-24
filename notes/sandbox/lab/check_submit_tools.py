#!/usr/bin/env python
"""Maya / Houdini 投遞視窗的回歸測試。

兩個投遞工具依賴 CueSubmit 的內部類別與欄位（InMayaSettings、MAYA_RENDER_CMD、
Shell layer 的 commandTextBox、CueSelectPulldown、chunkInput）。同步上游 CueSubmit
之後先跑這支，確認組出的指令、service、frame 範圍、chunk 都沒變。

在 OpenCue venv 執行，需要連得到 Cuebot（service 以 tag 反查）：

    set QT_QPA_PLATFORM=offscreen
    C:\\opencue\\venv\\Scripts\\python.exe check_submit_tools.py            只檢查，不送出
    C:\\opencue\\venv\\Scripts\\python.exe check_submit_tools.py --submit   檢查後實際送出

預期值依本機 sandbox（Maya 2027、Houdini 22.0.429、service maya2027 / houdini2204）。
"""
import argparse
import os
import sys

from qtpy import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.join(HERE, "..", "..", "deploy", "client")
sys.path.insert(0, os.path.join(CLIENT, "maya"))
sys.path.insert(0, os.path.join(CLIENT, "houdini"))

import opencue_houdini_submit  # noqa: E402
import opencue_maya_submit  # noqa: E402
from cuesubmit import Submission  # noqa: E402

HIP = "C:/opencue/scenes/hou_submit_test.hip"
HOUDINI_INFO = {
    "hip": HIP, "version": "22.0.429", "selected": "/obj/geo1/convert_cache",
    "nodes": [
        {"path": "/obj/geo1/convert_cache", "type": "filecache::2.0", "range": "1-4",
         "simulation": False},
        {"path": "/obj/geo1/sim_cache", "type": "filecache::2.0", "range": "1-10",
         "simulation": True},
    ],
}
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


def check_maya(submit):
    print("--- Maya")
    args = opencue_maya_submit.parse_args([
        "--file", "C:/opencue/scenes/test.ma", "--version", "2027", "--range", "1-2",
        "--cameras", "front", "persp", "renderCam1", "--renderable", "renderCam1"])
    window, widget = opencue_maya_submit.build_window(args)
    layer = fill(widget, "check_maya")
    check("service", layer.services, ["maya2027"])
    check("range", layer.layerRange, "1-2")
    check("command", Submission.buildLayerCommand(layer),
          "ocrun maya 2027 Render -r file -s #FRAME_START# -e #FRAME_END# "
          "-cam renderCam1 C:/opencue/scenes/test.ma")
    if submit:
        widget.submit()
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
        layer = fill(widget, "check_houdini_" + path.rsplit("/", 1)[-1])
        check(path + " service", layer.services, ["houdini2204"])
        check(path + " range", layer.layerRange, expected_range)
        check(path + " chunk", str(layer.chunk), expected_chunk)
        check(path + " command", Submission.buildLayerCommand(layer),
              "ocrun houdini 22.0.429 hython {0} {1} {2} #FRAMESPEC#".format(script, HIP, path))
        if submit:
            widget.submit()
    window.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="實際送出 job")
    args = ap.parse_args()
    app = QtWidgets.QApplication(sys.argv)  # noqa: F841
    check_maya(args.submit)
    check_houdini(args.submit)
    print("\n{0} failure(s)".format(len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
