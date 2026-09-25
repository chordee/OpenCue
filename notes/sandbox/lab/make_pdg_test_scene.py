"""建立 34 篇用的 PDG 測試場景。

用法：hython make_pdg_test_scene.py [work item 數量，預設 300]

/obj/topnet1：
    gen      Generic Generator，N 個 work item
    work     Python Script（外部程序，Hython）：寫一個小檔案、設定屬性 square、睡 2 秒（有 slow.<index> 標記檔時 90 秒）；
             pdg_out 裡有 fail.<index> 標記檔時以 exit 1 結束
    collect  Python Script（外部程序，PDG Python）：讀上游的輸出檔與屬性，寫出彙整
    opencue  OpenCue scheduler（topnet 的預設 scheduler）
"""
import sys

import hou

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 300

WORK = '''import os, sys, time
out = os.path.join(os.environ["PDG_DIR"], "pdg_out", "work.{0:04d}.txt".format(work_item.index))
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    f.write(str(work_item.index))
work_item.addOutputFile(out, "file/text")
work_item.setIntAttrib("square", work_item.index * work_item.index)
time.sleep(90 if os.path.exists(os.path.join(os.path.dirname(out), "slow.{0}".format(work_item.index))) else 2)
if os.path.exists(os.path.join(os.path.dirname(out), "fail.{0}".format(work_item.index))):
    sys.exit(1)
'''

COLLECT = '''import os
src = work_item.inputResultData[0].path
out = os.path.join(os.environ["PDG_DIR"], "pdg_out", "collect.{0:04d}.txt".format(work_item.index))
with open(out, "w") as f:
    f.write("{0} {1}".format(work_item.intAttribValue("square"), src))
work_item.addOutputFile(out, "file/text")
'''

net = hou.node("/obj").createNode("topnet", "topnet1")
sched = net.createNode("pdg_opencuescheduler", "opencue")
sched.parm("oc_show").set("testing")
sched.parm("pdg_workingdir").set("$HIP/pdg_work")
net.parm("topscheduler").set(sched.path())

gen = net.createNode("genericgenerator", "gen")
gen.parm("itemcount").set(COUNT)

work = net.createNode("pythonscript", "work")
work.setInput(0, gen)
work.parm("pdg_cooktype").set(2)  # Cook (Out-of-Process), runs on Hython
work.parm("script").set(WORK)

collect = net.createNode("pythonscript", "collect")
collect.setInput(0, work)
collect.parm("pdg_cooktype").set(2)
collect.parm("pythonbin").set(1)  # PDG Python
collect.parm("script").set(COLLECT)

net.layoutChildren()
hou.hipFile.save("P:/projects/opencue_test/scenes/pdg_test.hip")
print("saved", hou.hipFile.path(), COUNT)
