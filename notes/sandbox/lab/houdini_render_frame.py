"""OpenCue 農場測試用的 Houdini 算圖腳本。

以 hython 執行，每次算一個 frame。frame 編號來自 RQD 注入的環境變數
CUE_IFRAME，所以不需要在 job 指令裡做字串代換。

輸出目錄由 OPENCUE_RENDER_OUT 指定，預設 C:/opencue/render。
正式環境應指向共享儲存的 UNC 路徑。

算圖器由 OPENCUE_RENDERER 選擇：
    karma  (預設) 真正的 path tracer，行程內執行
    opengl        視埠算圖，最快，適合做連線測試

注意：Mantra (ifd ROP) 需要獨立的 render 授權，本機測試環境沒有，
      因此不提供該選項。
"""
import os
import sys
import time

import hou


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


frame = env_int("CUE_IFRAME", 1)
out_dir = os.environ.get("OPENCUE_RENDER_OUT", "C:/opencue/render").replace("\\", "/")
res = (env_int("OPENCUE_RES_X", 320), env_int("OPENCUE_RES_Y", 240))

print("=" * 60)
print("Houdini      :", hou.applicationVersionString())
print("Python       :", sys.version.split()[0])
print("License      :", hou.licenseCategory())
print("Frame        :", frame)
print("Output dir   :", out_dir)
print("Resolution   :", res)
print("CUE_JOB      :", os.environ.get("CUE_JOB"))
print("Render host  :", os.environ.get("CUE_FRAME_ID") and os.uname()[1] if hasattr(os, "uname") else os.environ.get("COMPUTERNAME"))
print("=" * 60)

if not os.path.isdir(out_dir):
    os.makedirs(out_dir)

hou.setFrame(frame)

obj = hou.node("/obj")

# 會隨 frame 變化的幾何，讓每張圖不一樣
geo = obj.createNode("geo", "render_geo")
torus = geo.createNode("torus")
torus.parm("rows").set(40)
torus.parm("cols").set(40)
xform = geo.createNode("xform")
xform.setFirstInput(torus)
xform.parm("rx").setExpression("$F * 9")
xform.parm("ry").setExpression("$F * 6")
xform.setDisplayFlag(True)
xform.setRenderFlag(True)

light = obj.createNode("hlight", "key_light")
light.parmTuple("t").set((3, 4, 5))
light.parm("light_intensity").set(4)

cam = obj.createNode("cam", "render_cam")
cam.parmTuple("t").set((0, 0, 6))
cam.parm("resx").set(res[0])
cam.parm("resy").set(res[1])

renderer = os.environ.get("OPENCUE_RENDERER", "karma").lower()

if renderer == "opengl":
    rop = hou.node("/out").createNode("opengl", "gl_test")
    rop.parm("camera").set(cam.path())
    picture = "%s/test.$F4.png" % out_dir
    rop.parm("picture").set(picture)
    rop.parm("tres").set(True)
    rop.parm("res1").set(res[0])
    rop.parm("res2").set(res[1])
    ext = "png"
else:
    rop = hou.node("/out").createNode("karma", "karma_test")
    rop.parm("camera").set(cam.path())
    picture = "%s/test.$F4.exr" % out_dir
    rop.parm("picture").set(picture)
    ext = "exr"

print("Renderer     :", renderer)

start = time.time()
rop.render(frame_range=(frame, frame, 1), verbose=True)
elapsed = time.time() - start

expected = "%s/test.%04d.%s" % (out_dir, frame, ext)
ok = os.path.isfile(expected)
size = os.path.getsize(expected) if ok else 0

print("=" * 60)
print("Render time  : %.2fs" % elapsed)
print("Output file  :", expected)
print("Exists       :", ok, "(%d bytes)" % size)
print("=" * 60)

sys.exit(0 if ok else 1)
