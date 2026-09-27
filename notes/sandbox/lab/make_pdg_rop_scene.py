"""建立 34 篇用的 PDG 算圖節點測試場景。

用法：hython make_pdg_rop_scene.py
以 hou_submit_test.hip（make_houdini_submit_scene.py 產生）為基礎，另存為 pdg_rop_test.hip。

/obj/topnet_rop：
    geo      ROP Geometry TOP：直接輸出 /obj/geo1/box1，frame 1-5
    fetch    ROP Fetch → /obj/geo1/rop_out（SOP 層的 ROP Geometry），沿用 ROP 的 frame 1-3，整段一個 work item
    karma    ROP Fetch → /stage/karma_render/rop_usdrender（Karma LOP 內的 USD Render ROP），frame 1-3，每格一個 work item
    opencue  OpenCue scheduler
輸出都改到 P:/projects/opencue_test/render/pdg_rop/。
"""
import hou

OUT = "P:/projects/opencue_test/render/pdg_rop/"

hou.hipFile.load("P:/projects/opencue_test/scenes/hou_submit_test.hip",
                 suppress_save_prompt=True, ignore_load_warnings=True)
hou.node("/obj/geo1/rop_out").parm("sopoutput").set(OUT + "fetch.$F4.bgeo.sc")
hou.node("/stage/karma_render").parm("picture").set(OUT + "karma.$F4.exr")

net = hou.node("/obj").createNode("topnet", "topnet_rop")
sched = net.createNode("pdg_opencuescheduler", "opencue")
sched.parm("oc_show").set("testing")
sched.parm("pdg_workingdir").set("$HIP/pdg_work_rop")
net.parm("topscheduler").set(sched.path())

geo = net.createNode("ropgeometry", "geo")
geo.parm("soppath").set("/obj/geo1/box1")
geo.parm("sopoutput").set(OUT + "geo.$F4.bgeo.sc")
geo.parm("framegeneration").set(1)  # Frame Range（預設是 Single Frame）
geo.parmTuple("f").deleteAllKeyframes()
geo.parmTuple("f").set((1, 5, 1))

fetch = net.createNode("ropfetch", "fetch")
fetch.parm("roppath").set("/obj/geo1/rop_out")
fetch.parm("framegeneration").set(3)  # ROP Node Configuration：沿用 ROP 的範圍

karma = net.createNode("ropfetch", "karma")
karma.parm("roppath").set("/stage/karma_render/rop_usdrender")
karma.parm("framegeneration").set(1)  # Frame Range：每格一個 work item
karma.parmTuple("range").deleteAllKeyframes()
karma.parmTuple("range").set((1, 3, 1))

net.layoutChildren()
hou.hipFile.save("P:/projects/opencue_test/scenes/pdg_rop_test.hip")
print("saved", hou.hipFile.path())
