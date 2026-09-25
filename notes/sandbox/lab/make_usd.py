import hou, os

out_usd = os.environ.get("OUT_USD", "P:/projects/opencue_test/render/scene.usda")
stage = hou.node("/stage")

sphere = stage.createNode("sphere")
light  = stage.createNode("domelight")
light.setFirstInput(sphere)
cam    = stage.createNode("camera")
cam.setFirstInput(light)
cam.parmTuple("t").set((0, 0, 6))

rs = stage.createNode("karmarendersettings")
rs.setFirstInput(cam)

# 解析度需先切換 res_mode 才可手動指定
rm = rs.parm("res_mode")
if rm:
    print("res_mode menu:", rm.menuItems())
    try:
        rm.set(1)
    except Exception as e:
        print("res_mode set failed:", e)
try:
    rs.parmTuple("resolution").set((320, 240))
    print("resolution set ok")
except Exception as e:
    print("resolution set failed:", e)

campath = cam.parm("primpath").eval() if cam.parm("primpath") else "/cameras/camera1"
rs.parm("camera").set(campath)
print("camera prim:", campath)

rop = stage.createNode("usd_rop")
rop.setFirstInput(rs)
rop.parm("lopoutput").set(out_usd)
rop.render(frame_range=(1, 1, 1))

ok = os.path.isfile(out_usd)
print("USD written:", ok, os.path.getsize(out_usd) if ok else 0, "bytes")
