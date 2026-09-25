#!/usr/bin/env python
"""把 DCC 算圖工作投到 OpenCue 農場（Houdini / Maya / Nuke）。

設計要點見 notes/sandbox/12-Houdini真實算圖.md：

1. 指令以「串列」形式傳入，避免 shlex 吃掉 Windows 路徑的反斜線
2. 以 ocrun <產品> <版本> <程式> 呼叫 DCC，安裝位置由各節點的 dcc.toml 決定
   （notes/sandbox/26-ocrun取代wrapper.md）
3. 用 layer tag 綁定 DCC 版本，Cuebot 只派給真的裝了該版本的節點
4. frame 編號由 Cuebot 的 #IFRAME# token 或 RQD 注入的 CUE_IFRAME 傳遞

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

PRESETS = {
    "houdini": {
        "version": "22_0_429",
        "tag": "houdini_22_0_429",
        "command": ["ocrun", "houdini", "22.0.429", "hython",
                    "P:/projects/opencue_test/scripts/houdini_render_frame.py"],
        "env": {"OPENCUE_RENDER_OUT": "P:/projects/opencue_test/render",
                "OPENCUE_RENDERER": "karma"},
    },
    "maya": {
        "version": "2027",
        "tag": "maya_2027",
        "command": ["ocrun", "maya", "2027", "Render",
                    "-r", "sw", "-s", "#IFRAME#", "-e", "#IFRAME#",
                    "-rd", "P:/projects/opencue_test/render/maya",
                    "P:/projects/opencue_test/scenes/test.ma"],
        "env": {},
    },
    "nuke": {
        "version": "17_0v1",
        "tag": "nuke_17_0v1",
        "command": ["ocrun", "nuke", "17.0v1", "Nuke17.0", "-t",
                    "P:/projects/opencue_test/scripts/nuke_render_frame.py"],
        "env": {"OPENCUE_RENDER_OUT": "P:/projects/opencue_test/render/nuke"},
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
