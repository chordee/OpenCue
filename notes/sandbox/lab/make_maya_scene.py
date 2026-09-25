import os
import maya.standalone
maya.standalone.initialize(name="python")

import maya.cmds as cmds

out_scene = os.environ.get("OUT_SCENE", "P:/projects/opencue_test/scenes/test.ma")
os.makedirs(os.path.dirname(out_scene), exist_ok=True)

cmds.file(new=True, force=True)

sphere = cmds.polySphere(r=2, name="testSphere")[0]
cmds.setKeyframe(sphere, attribute="rotateY", t=1, v=0)
cmds.setKeyframe(sphere, attribute="rotateY", t=10, v=180)

cmds.directionalLight(rotation=(-45, 30, 0), intensity=1.5)

cam = cmds.camera(name="renderCam")[0]
cmds.setAttr(cam + ".translateZ", 10)
cmds.setAttr(cam + ".renderable", 1)
for c in cmds.ls(cameras=True):
    if c != cmds.listRelatives(cam, shapes=True)[0]:
        try:
            cmds.setAttr(c + ".renderable", 0)
        except Exception:
            pass

cmds.setAttr("defaultRenderGlobals.currentRenderer", "mayaSoftware", type="string")
cmds.setAttr("defaultRenderGlobals.imageFormat", 32)   # 32 = PNG
cmds.setAttr("defaultRenderGlobals.animation", 1)
cmds.setAttr("defaultRenderGlobals.putFrameBeforeExt", 1)
cmds.setAttr("defaultRenderGlobals.extensionPadding", 4)
cmds.setAttr("defaultResolution.width", 320)
cmds.setAttr("defaultResolution.height", 240)

cmds.file(rename=out_scene)
cmds.file(save=True, type="mayaAscii")
print("scene saved:", out_scene, os.path.isfile(out_scene))

maya.standalone.uninitialize()
