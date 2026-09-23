#!/usr/bin/env python
"""把 Houdini 算圖工作投到 OpenCue 農場。

這支腳本示範三件在正式環境很重要的事：

1. **指令以「串列」形式傳入**
   pyoutline 的 prep_shell_command()（outline/io.py:53）只有在指令是字串時
   才會呼叫 shlex.split()，而 shlex 在 POSIX 模式會把 Windows 路徑的反斜線
   當成跳脫字元吃掉。傳串列就完全繞過這個問題。

2. **不寫死 DCC 安裝路徑**
   指令呼叫的是每台節點都放在相同位置的包裝腳本
   C:\opencue\bin\hython-<version>.bat，由它去指向本機實際的安裝位置。
   不同機器裝在不同磁碟機也沒關係。

3. **用 layer tag 綁定 DCC 版本**
   節點透過 RQD_TAGS 廣告自己裝了哪些版本，job 用對應的 tag 要求，
   Cuebot 就只會把工作派給真的能跑的機器。

用法：
    python submit_houdini.py --frames 1-4 --version 22_0_429
"""
import argparse
import os
import sys

import outline
import outline.cuerun
from outline.modules.shell import Shell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", default="testing")
    ap.add_argument("--shot", default="testshot")
    ap.add_argument("--name", default="houdini_render")
    ap.add_argument("--frames", default="1-4", help="frame range, e.g. 1-4")
    ap.add_argument("--version", default="22_0_429",
                    help="Houdini version tag suffix, e.g. 22_0_429")
    ap.add_argument("--wrapper-dir", default="C:/opencue/bin")
    ap.add_argument("--script", default="C:/opencue/scripts/houdini_render_frame.py")
    ap.add_argument("--out", default="C:/opencue/render",
                    help="算圖輸出目錄。正式環境應為共享儲存的 UNC 路徑")
    ap.add_argument("--renderer", default="karma", choices=["karma", "opengl"])
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # 版本 tag 的點號在檔名裡是點、在 tag 裡是底線
    dotted = args.version.replace("_", ".")
    wrapper = "%s/hython-%s.bat" % (args.wrapper_dir, dotted)
    version_tag = "houdini_%s" % args.version

    # 【重點】串列形式，不是字串
    command = [wrapper, args.script]

    layer = Shell(
        "houdini_render",
        command=command,
        range=args.frames,
        # 只放版本 tag。Cuebot 的 tag 比對是 regex 且以 | 分隔（即「或」），
        # 多加 general 會讓版本綁定失效。詳見 notes/sandbox/12。
        tags=[version_tag],
        env={
            "OPENCUE_RENDER_OUT": args.out,
            "OPENCUE_RENDERER": args.renderer,
        },
    )

    short_name = "%s_%s" % (args.name, args.version)

    print("job      :", short_name)
    print("frames   :", args.frames)
    print("tags     :", [version_tag])
    print("command  :", command)
    print("output   :", args.out)
    print("renderer :", args.renderer)

    if args.dry_run:
        print("(dry run, 未送出)")
        return 0

    ol = outline.Outline(short_name, shot=args.shot, show=args.show)
    ol.add_layer(layer)
    outline.cuerun.launch(ol, pause=args.paused, use_pycuerun=False)
    print("已送出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
