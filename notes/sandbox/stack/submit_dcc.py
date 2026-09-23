#!/usr/bin/env python
"""把 DCC 算圖工作投到 OpenCue 農場（Houdini / Maya / Nuke）。

設計要點見 notes/sandbox/12-Houdini真實算圖.md：

1. 指令以「串列」形式傳入，避免 shlex 吃掉 Windows 路徑的反斜線
2. 呼叫每台節點相同路徑的包裝腳本，不寫死 DCC 安裝位置
3. 用 layer tag 綁定 DCC 版本，Cuebot 只派給真的裝了該版本的節點
4. frame 編號由 RQD 注入的 CUE_IFRAME 傳遞，指令本身與 frame 無關

用法：
    python submit_dcc.py houdini --frames 1-4
    python submit_dcc.py maya    --frames 1-3
    python submit_dcc.py nuke    --frames 1-3
"""
import argparse
import sys

import outline
import outline.cuerun
from outline.modules.shell import Shell

BIN = "C:/opencue/bin"

PRESETS = {
    "houdini": {
        "version": "22_0_429",
        "tag": "houdini_22_0_429",
        "command": [BIN + "/hython-22.0.429.bat",
                    "C:/opencue/scripts/houdini_render_frame.py"],
        "env": {"OPENCUE_RENDER_OUT": "C:/opencue/render",
                "OPENCUE_RENDERER": "karma"},
    },
    "maya": {
        "version": "2027",
        "tag": "maya_2027",
        "command": [BIN + "/maya-render-2027.bat",
                    "C:/opencue/scenes/test.ma",
                    "C:/opencue/render/maya",
                    "sw"],
        "env": {},
    },
    "nuke": {
        "version": "17_0v1",
        "tag": "nuke_17_0v1",
        "command": [BIN + "/nuke-17.0v1.bat",
                    "C:/opencue/scripts/nuke_render_frame.py"],
        "env": {"OPENCUE_RENDER_OUT": "C:/opencue/render/nuke"},
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("app", choices=sorted(PRESETS))
    ap.add_argument("--show", default="testing")
    ap.add_argument("--shot", default="testshot")
    ap.add_argument("--frames", default="1-3")
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    preset = PRESETS[args.app]
    # 【重要】只放版本 tag，不要加 general。
    # Cuebot 的比對是 regex：host.str_tags ~* ('(?x)' || layer.str_tags || '\y')
    # layer 的多個 tag 會以 " | " 串接，而 | 在 regex 裡是「或」——
    # 加上 general 等於「任何有 general 的節點都符合」，版本綁定完全失效。
    tags = [preset["tag"]]
    short_name = "%s_render_%s" % (args.app, preset["version"])

    print("job     :", short_name)
    print("frames  :", args.frames)
    print("tags    :", tags)
    print("command :", preset["command"])

    if args.dry_run:
        print("(dry run)")
        return 0

    layer = Shell(
        "%s_render" % args.app,
        command=preset["command"],      # 串列，不是字串
        range=args.frames,
        tags=tags,
        env=preset["env"],
    )
    ol = outline.Outline(short_name, shot=args.shot, show=args.show)
    ol.add_layer(layer)
    outline.cuerun.launch(ol, pause=args.paused, use_pycuerun=False)
    print("已送出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
