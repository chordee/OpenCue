"""Houdini render script for OpenCue farm testing.

Executed via hython, rendering one frame per task. Frame number is provided
by RQD injected environment variable CUE_IFRAME, eliminating the need for command string token replacement.

Output directory specified by OPENCUE_RENDER_OUT, defaulting to P:/projects/opencue_test/render.
Production setups should point to shared storage UNC paths.

Renderer selected via OPENCUE_RENDERER:
    karma  (default) Path tracer, executes in-process
    opengl          Viewport render, fastest, ideal for connectivity testing

Note: Mantra (ifd ROP) requires a standalone render license, unavailable in local test environments,
      and is therefore omitted.
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
out_dir = os.environ.get("OPENCUE_RENDER_OUT", "P:/projects/opencue_test/render").replace("\\", "/")
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

# Animate geometry over frames so each rendered frame differs
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
