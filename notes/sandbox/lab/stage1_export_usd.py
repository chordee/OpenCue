"""兩階段派工的第 1 階段：以 hython 建立場景並匯出 USD。

第 2 階段由 husk 直接算這個 USD，不需要再開 Houdini。

輸出路徑由 OPENCUE_USD_OUT 指定；frame 範圍由 OPENCUE_FRAME_START /
OPENCUE_FRAME_END 指定（USD 會包含這段時間的動畫取樣）。
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


out_usd = os.environ.get("OPENCUE_USD_OUT", "C:/opencue/render/twostage.usda").replace("\\", "/")
f1 = env_int("OPENCUE_FRAME_START", 1)
f2 = env_int("OPENCUE_FRAME_END", 3)

print("=" * 60)
print("Stage 1 : USD export")
print("Houdini :", hou.applicationVersionString())
print("Output  :", out_usd)
print("Frames  : %d-%d" % (f1, f2))
print("CUE_JOB :", os.environ.get("CUE_JOB"))
print("=" * 60)

out_dir = os.path.dirname(out_usd)
if out_dir and not os.path.isdir(out_dir):
    os.makedirs(out_dir)

stage = hou.node("/stage")

sphere = stage.createNode("sphere")

# 讓幾何隨 frame 移動，這樣每一格算出來的圖才會不同
xform = stage.createNode("xform")
xform.setFirstInput(sphere)
xform.parm("primpattern").set("/sphere1")
try:
    xform.parm("ty").setExpression("sin($F * 60) * 1.5")
    xform.parm("ry").setExpression("$F * 30")
except Exception as e:
    print("xform 參數設定略過:", e)

light = stage.createNode("domelight")
light.setFirstInput(xform)

cam = stage.createNode("camera")
cam.setFirstInput(light)
cam.parmTuple("t").set((0, 0, 8))

rs = stage.createNode("karmarendersettings")
rs.setFirstInput(cam)
campath = cam.parm("primpath").eval() if cam.parm("primpath") else "/cameras/camera1"
rs.parm("camera").set(campath)

rop = stage.createNode("usd_rop")
rop.setFirstInput(rs)
rop.parm("lopoutput").set(out_usd)
# trange=1 表示輸出整段 frame 範圍，USD 內才會有動畫取樣
try:
    rop.parm("trange").set(1)
    rop.parm("f1").set(f1)
    rop.parm("f2").set(f2)
except Exception as e:
    print("frame range 設定略過:", e)

start = time.time()
rop.render()
elapsed = time.time() - start

ok = os.path.isfile(out_usd)
size = os.path.getsize(out_usd) if ok else 0
print("=" * 60)
print("Export time : %.2fs" % elapsed)
print("Exists      :", ok, "(%d bytes)" % size)
print("Camera prim :", campath)
print("=" * 60)

sys.exit(0 if ok else 1)
