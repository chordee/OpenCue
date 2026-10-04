"""Stage 1 of two-stage dispatch: build scene and export USD via hython.

Stage 2 renders the exported USD directly using husk, without opening Houdini.

Output path specified by OPENCUE_USD_OUT; frame range specified by OPENCUE_FRAME_START /
OPENCUE_FRAME_END (USD will contain animation samples for this range).
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


out_usd = os.environ.get("OPENCUE_USD_OUT", "P:/projects/opencue_test/render/twostage.usda").replace("\\", "/")
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

# Animate geometry over time so each rendered frame differs
xform = stage.createNode("xform")
xform.setFirstInput(sphere)
xform.parm("primpattern").set("/sphere1")
try:
    xform.parm("ty").setExpression("sin($F * 60) * 1.5")
    xform.parm("ry").setExpression("$F * 30")
except Exception as e:
    print("xform parameter setting skipped:", e)

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
# trange=1 exports full frame range so USD contains animation samples
try:
    rop.parm("trange").set(1)
    rop.parm("f1").set(f1)
    rop.parm("f2").set(f2)
except Exception as e:
    print("frame range setting skipped:", e)

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
